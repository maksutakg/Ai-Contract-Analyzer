"""DOCX export of a revised contract from a ContractReport (stateless).

All clauses are written in order; rewritten clauses are replaced by the
suggestion, highlighted and labelled. An appendix table lists each change
(original, suggestion, reason, related risk). Word tracked changes are not
produced.
"""

from io import BytesIO

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.shared import Pt, RGBColor

from .categories import category_label
from .contract_types import role_label
from .models import ContractReport

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_SEVERITY_TR = {"low": "düşük", "medium": "orta", "high": "yüksek", "critical": "kritik"}
_MARK_COLOR = RGBColor(0xC0, 0x00, 0x00)


def _related_risk(report: ContractReport, finding_ids: list[str]) -> str:
    by_id = {finding.id: finding for finding in report.findings}
    parts = []
    for finding_id in finding_ids:
        finding = by_id.get(finding_id)
        if finding is None:
            continue
        source = " (kanuni sınır)" if finding.detected_by == "statutory_rule" else ""
        parts.append(f"{category_label(finding.category)} – {_SEVERITY_TR.get(finding.severity, finding.severity)}{source}")
    return "; ".join(parts) or "-"


def build_revised_contract_docx(report: ContractReport) -> bytes:
    document = Document()
    document.styles["Normal"].font.size = Pt(10.5)
    document.add_heading("Revize Edilmiş Sözleşme Taslağı", level=0)

    intro = document.add_paragraph()
    intro.add_run(
        "Bu taslak otomatik sözleşme analizinden üretilmiştir ve hukuki danışmanlık yerine geçmez. "
        "Değiştirilen maddeler sarı ile vurgulanmış ve [DEĞİŞTİRİLDİ] etiketiyle işaretlenmiştir; "
        "değişikliklerin gerekçeleri ekteki tabloda yer alır."
    ).italic = True
    user = role_label(report.contract_type, report.party)
    if user:
        document.add_paragraph(f"Öneriler {user} tarafının bakış açısıyla hazırlanmıştır.")

    rewrites = {rewrite.clause_id: rewrite for rewrite in report.rewrites}
    numbers = {rewrite.clause_id: index for index, rewrite in enumerate(report.rewrites, start=1)}
    for clause in report.clauses:
        document.add_heading(clause.title or clause.id, level=2)
        rewrite = rewrites.get(clause.id)
        if rewrite is None:
            document.add_paragraph(clause.text)
            continue
        paragraph = document.add_paragraph()
        marker = paragraph.add_run(f"[DEĞİŞTİRİLDİ – Değişiklik {numbers[clause.id]}] ")
        marker.bold = True
        marker.font.color.rgb = _MARK_COLOR
        suggestion = paragraph.add_run(rewrite.suggested_text)
        suggestion.font.highlight_color = WD_COLOR_INDEX.YELLOW

    document.add_page_break()
    document.add_heading("Ek: Değişiklik Tablosu", level=1)
    if not report.rewrites:
        document.add_paragraph("Değişiklik önerisi bulunmamaktadır.")
    else:
        table = document.add_table(rows=1, cols=5)
        table.style = "Table Grid"
        for cell, title in zip(table.rows[0].cells, ["No / Madde", "Orijinal metin", "Önerilen metin", "Gerekçe", "İlgili risk"]):
            cell.text = ""
            cell.paragraphs[0].add_run(title).bold = True
        titles = {clause.id: clause.title or clause.id for clause in report.clauses}
        for index, rewrite in enumerate(report.rewrites, start=1):
            row = table.add_row().cells
            row[0].text = f"{index} / {titles.get(rewrite.clause_id, rewrite.clause_id)}"
            row[1].text = rewrite.original_text
            row[2].text = rewrite.suggested_text
            row[3].text = rewrite.rationale
            row[4].text = _related_risk(report, rewrite.finding_ids)

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()

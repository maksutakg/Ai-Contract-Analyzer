from io import BytesIO

import pytest
from docx import Document
from docx.enum.text import WD_COLOR_INDEX

from law_rag.config import Settings
from law_rag.contract_types import normalize_contract_type, normalize_party
from law_rag.export_docx import build_revised_contract_docx
from law_rag.fake_analyzer import FakeContractAnalyzer
from law_rag.graph import analyze_contract
from law_rag.missing_clauses import build_missing_clauses, keyword_presence
from law_rag.models import (
    Clause,
    ClauseRewrite,
    ContractReport,
    LegalReference,
    RiskFinding,
    YargiDecision,
)
from law_rag.rewrites import clauses_to_rewrite
from law_rag.segmentation import PREAMBLE_ID, segment_clauses
from law_rag.yargi_client import FakeYargiClient


@pytest.mark.asyncio
async def test_fake_analyzer_does_not_attach_findings_to_preamble() -> None:
    analyzer = FakeContractAnalyzer()
    text = (
        "FESİH VE CEZAİ ŞART KONUT KİRA SÖZLEŞMESİ\n"
        "Taşınmaz İstanbul ilindedir.\n"
        "MADDE 1 - KONU\n"
        "Taraflar konut kirası konusunda anlaşmıştır.\n"
        "MADDE 2 - YETKİ\n"
        "Uyuşmazlıklarda Ankara mahkemeleri yetkilidir.\n"
    )
    clauses = segment_clauses(text)
    assert clauses[0].id == PREAMBLE_ID

    findings = await analyzer.classify_risks(clauses, contract_type="lease")

    assert all(finding.clause_id != PREAMBLE_ID for finding in findings)
    assert [finding.category for finding in findings] == ["jurisdiction"]


@pytest.mark.asyncio
async def test_fake_analyzer_detects_non_ankara_jurisdiction_courts() -> None:
    analyzer = FakeContractAnalyzer()
    clauses = segment_clauses(
        "KİRA SÖZLEŞMESİ\n"
        "MADDE 1 - YETKİ\n"
        "Uyuşmazlıklarda İzmir Mahkemeleri yetkilidir.\n"
    )
    findings = await analyzer.classify_risks(clauses, contract_type="lease")
    assert [f.category for f in findings] == ["jurisdiction"]
    assert "İzmir mahkemelerini" in findings[0].explanation

    lowercase_clauses = segment_clauses(
        "HİZMET SÖZLEŞMESİ\n"
        "MADDE 1 - YETKİ\n"
        "Uyuşmazlıklarda bursa mahkemeleri yetkilidir.\n"
    )
    lower_findings = await analyzer.classify_risks(lowercase_clauses, contract_type="service")
    assert [f.category for f in lower_findings] == ["jurisdiction"]
    assert "Ankara" not in lower_findings[0].explanation

    generic_clauses = segment_clauses(
        "KİRA SÖZLEŞMESİ\n"
        "MADDE 1 - YETKİ\n"
        "Uyuşmazlıklarda kanunen yetkili mahkemeleri ve icra daireleri görevlidir.\n"
    )
    assert await analyzer.classify_risks(generic_clauses, contract_type="lease") == []


def test_clauses_to_rewrite_skips_preamble() -> None:
    clauses = [
        Clause(id=PREAMBLE_ID, title="Başlangıç", text="Sözleşme başlığı ve taraflar."),
        Clause(id="clause-1", title="MADDE 1", text="Kiracı izinsiz girer."),
    ]
    findings = [
        RiskFinding(
            id="finding-1",
            category="termination",
            severity="medium",
            explanation="Başlıkta fesih geçiyor.",
            recommendation="Düzenleyin.",
            clause_id=PREAMBLE_ID,
            applies_to_user=True,
        ),
        RiskFinding(
            id="finding-2",
            category="unlawful_entry",
            severity="critical",
            explanation="İzinsiz giriş.",
            recommendation="Onay ekleyin.",
            clause_id="clause-1",
            applies_to_user=True,
        ),
    ]

    items = clauses_to_rewrite(clauses, findings)

    assert [clause.id for clause, _ in items] == ["clause-1"]


def test_normalize_contract_type_and_party_inference() -> None:
    assert normalize_contract_type("kira") == "lease"
    assert normalize_contract_type("hizmet") == "service"
    assert normalize_contract_type("iş") == "employment"
    assert normalize_contract_type("custom_type") == "custom_type"

    assert normalize_party(None, "kiracı") == ("lease", "tenant")
    assert normalize_party("lease", "ev sahibi") == ("lease", "landlord")
    assert normalize_party("lease", "işçi") == ("lease", None)
    assert normalize_party("employment", "işçi") == ("employment", "employee")


class DualPartyAnalyzer(FakeContractAnalyzer):
    async def classify_risks(self, clauses, contract_type=None, *, party=None):
        return [
            RiskFinding(
                id="finding-tenant",
                category="deposit_forfeiture",
                severity="low",
                explanation="Kiracı aleyhine hafif kayıt.",
                recommendation="Kiracı güvencesini netleştirin.",
                clause_id="clause-1",
                disadvantaged_party="tenant",
            ),
            RiskFinding(
                id="finding-landlord",
                category="termination",
                severity="critical",
                explanation="Kiraya veren aleyhine kritik kayıt.",
                recommendation="Fesih bildirimini düzeltin.",
                clause_id="clause-2",
                disadvantaged_party="landlord",
            ),
        ]

    async def build_legal_queries(self, findings, contract_type=None):
        return {finding.id: f"{finding.category} yargıtay" for finding in findings}


class StubYargiClient(FakeYargiClient):
    async def search(self, query: str, category: str | None = None, limit: int = 3):
        return [
            YargiDecision(
                source="Bedesten",
                title=f"Emsal {category}",
                relevance="İlgili karar",
                excerpt="Depozito ve fesih koşulları emsal kararı.",
            )
        ]


@pytest.mark.asyncio
async def test_party_perspective_filters_score_actions_and_rewrites() -> None:
    text = (
        "KONUT KİRA SÖZLEŞMESİ\n"
        "MADDE 1 - GÜVENCE\nTaraflar kapora konusunda anlaşmıştır.\n"
        "MADDE 2 - FESİH\nTaraflar sözleşmeyi bildirimsiz sonlandırabilir.\n"
    )
    settings = Settings(crag_use_llm_grader=False)

    tenant_report = await analyze_contract(
        file_name="kira.docx",
        file_type="docx",
        raw_text=text,
        contract_type="lease",
        party="kiracı",
        analyzer=DualPartyAnalyzer(),
        yargi_client=StubYargiClient(),
        app_settings=settings,
    )
    assert tenant_report.party == "tenant"
    by_clause = {f.clause_id: f for f in tenant_report.findings}
    assert by_clause["clause-1"].applies_to_user is True
    assert by_clause["clause-2"].applies_to_user is False
    assert tenant_report.risk_score == 10
    assert tenant_report.risk_level == "low"
    assert tenant_report.recommended_actions == ["Kiracı güvencesini netleştirin."]
    assert [r.clause_id for r in tenant_report.rewrites] == ["clause-1"]

    landlord_report = await analyze_contract(
        file_name="kira.docx",
        file_type="docx",
        raw_text=text,
        contract_type="lease",
        party="ev sahibi",
        analyzer=DualPartyAnalyzer(),
        yargi_client=StubYargiClient(),
        app_settings=settings,
    )
    assert landlord_report.party == "landlord"
    assert landlord_report.risk_score == 70
    assert landlord_report.risk_level == "high"
    assert landlord_report.recommended_actions == ["Fesih bildirimini düzeltin."]
    assert [r.clause_id for r in landlord_report.rewrites] == ["clause-2"]


def test_missing_clauses_checklists_and_party_importance_shift() -> None:
    minimal_clauses = [Clause(id="clause-1", title="MADDE 1", text="Taraflar anlaşmıştır.")]

    lease_presence = keyword_presence(minimal_clauses, "lease")
    tenant_missing = {m.topic: m for m in build_missing_clauses(lease_presence, "lease", "tenant")}
    landlord_missing = {m.topic: m for m in build_missing_clauses(lease_presence, "lease", "landlord")}

    assert tenant_missing["deposit"].importance == "medium"
    assert tenant_missing["deposit"].explanation.startswith("Kiracı olarak sizin açınızdan önemlidir:")
    assert landlord_missing["deposit"].importance == "low"
    assert landlord_missing["deposit"].explanation.startswith("Bu eksiklik daha çok karşı tarafı etkiler.")
    assert landlord_missing["rent_increase"].importance == "medium"
    assert tenant_missing["rent_increase"].importance == "low"

    service_topics = {m.topic for m in build_missing_clauses(keyword_presence(minimal_clauses, "service"), "service", "client")}
    assert {"scope", "fee_payment", "ip_ownership", "personal_data"}.issubset(service_topics)

    employment_topics = {m.topic for m in build_missing_clauses(keyword_presence(minimal_clauses, "employment"), "employment", "employee")}
    assert {"wage", "working_hours", "annual_leave"}.issubset(employment_topics)


def test_export_docx_preserves_order_highlights_rewrites_and_builds_appendix_table() -> None:
    report = ContractReport(
        contract_summary="Özet",
        risk_score=45,
        risk_level="medium",
        contract_type="lease",
        party="tenant",
        clauses=[
            Clause(id="clause-1", title="MADDE 1 - KONU", text="Konut kirasıdır."),
            Clause(id="clause-2", title="MADDE 2 - DEPOZİTO", text="Kiracı 5 kira depozito öder."),
        ],
        findings=[
            RiskFinding(
                id="finding-stat",
                category="deposit_forfeiture",
                severity="high",
                explanation="Üst sınır aşıldı.",
                recommendation="Üç aya indirin.",
                clause_id="clause-2",
                detected_by="statutory_rule",
                legal_references=[
                    LegalReference(
                        law_name="TBK",
                        law_number="6098",
                        article="m.342",
                        summary="Üç ay",
                        url="https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6098",
                    )
                ],
            )
        ],
        rewrites=[
            ClauseRewrite(
                clause_id="clause-2",
                finding_ids=["finding-stat"],
                original_text="Kiracı 5 kira depozito öder.",
                suggested_text="Kiracı en fazla 3 aylık kira bedeli depozito öder.",
                rationale="TBK m.342 sınırı",
                generated_by="rule_based",
            )
        ],
    )

    data = build_revised_contract_docx(report)
    doc = Document(BytesIO(data))
    texts = [p.text for p in doc.paragraphs]

    idx_c1 = next(i for i, t in enumerate(texts) if "MADDE 1 - KONU" in t)
    idx_c2 = next(i for i, t in enumerate(texts) if "MADDE 2 - DEPOZİTO" in t)
    assert idx_c1 < idx_c2
    assert "Öneriler kiracı tarafının bakış açısıyla hazırlanmıştır." in texts
    assert "Konut kirasıdır." in texts

    rewritten_para = doc.paragraphs[idx_c2 + 1]
    assert rewritten_para.runs[0].text.startswith("[DEĞİŞTİRİLDİ – Değişiklik 1] ")
    assert rewritten_para.runs[0].bold is True
    assert rewritten_para.runs[1].text == "Kiracı en fazla 3 aylık kira bedeli depozito öder."
    assert rewritten_para.runs[1].font.highlight_color == WD_COLOR_INDEX.YELLOW

    assert len(doc.tables) == 1
    table = doc.tables[0]
    assert [c.text for c in table.rows[0].cells] == [
        "No / Madde",
        "Orijinal metin",
        "Önerilen metin",
        "Gerekçe",
        "İlgili risk",
    ]
    assert len(table.rows) == 2
    row = table.rows[1].cells
    assert row[0].text == "1 / MADDE 2 - DEPOZİTO"
    assert row[1].text == "Kiracı 5 kira depozito öder."
    assert row[2].text == "Kiracı en fazla 3 aylık kira bedeli depozito öder."
    assert row[3].text == "TBK m.342 sınırı"
    assert "(kanuni sınır)" in row[4].text

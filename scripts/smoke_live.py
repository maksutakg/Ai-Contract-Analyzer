import argparse
import asyncio
import json
import subprocess
import sys
import time
from io import BytesIO

import httpx
from google import genai
from google.genai import types
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from law_rag.call_gate import CallGate
from law_rag.chat_answer import GeminiChatAnswerer
from law_rag.chat_index import build_index, retrieve
from law_rag.config import Settings
from law_rag.embeddings import GeminiEmbedder
from law_rag.graph import analyze_contract
from law_rag.llm import GeminiContractAnalyzer
from law_rag.models import Clause, ContractReport, RiskFinding, YargiDecision
from law_rag.ocr import GeminiOcrEngine, PageImage, clean_transcription, render_pdf_pages
from law_rag.yargi_client import RemoteYargiMcpClient


def _sample_pdf_bytes() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    content = DecodedStreamObject()
    content.set_data(
        b"BT\n/F1 18 Tf\n50 720 Td\n(KONUT KIRA SOZLESMESI) Tj\n"
        b"0 -36 Td\n(MADDE 1 - DEPOZITO) Tj\n"
        b"0 -28 Td\n(Kiraci 100.000 TL depozito oder.) Tj\nET\n"
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


async def run_yargi_smoke(port: int) -> bool:
    cmd = [
        "uvx",
        "--with",
        "mcp<1.26",
        "--with",
        "fastmcp<2.15",
        "--with",
        "uvicorn[standard]",
        "--from",
        "yargi-mcp",
        "uvicorn",
        "asgi_app:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client: RemoteYargiMcpClient | None = None
    ok = True
    try:
        ready = False
        for _ in range(50):
            if proc.poll() is not None:
                break
            try:
                res = httpx.get(f"http://127.0.0.1:{port}/health", trust_env=False, timeout=2.0)
                if res.status_code == 200:
                    print("YARGI_HEALTH:", json.dumps(res.json(), ensure_ascii=False), flush=True)
                    ready = True
                    break
            except Exception:
                await asyncio.sleep(0.3)
        if not ready:
            print(f"YARGI_START_FAILED: returncode={proc.poll()}", flush=True)
            return False

        app_settings = Settings(
            _env_file=None,
            yargi_mcp_url=f"http://127.0.0.1:{port}/mcp/",
            use_remote_yargi=True,
            yargi_request_timeout_seconds=30.0,
            yargi_max_results_per_finding=3,
        )
        client = RemoteYargiMcpClient(app_settings)

        t0 = time.monotonic()
        bedesten_decisions = await client.search(
            '"kira sözleşmesi" depozito "iade edilmez"', category="deposit_forfeiture"
        )
        print(
            f"BEDESTEN_SEARCH ({time.monotonic() - t0:.2f}s): count={len(bedesten_decisions)}",
            flush=True,
        )
        for item in bedesten_decisions:
            print(
                "  BEDESTEN_ITEM:",
                json.dumps(
                    {
                        "source": item.source,
                        "title": item.title,
                        "number": item.decision_number,
                        "date": item.decision_date,
                        "url": item.url,
                        "excerpt_len": len(item.excerpt or ""),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        if bedesten_decisions:
            t1 = time.monotonic()
            full_text = await client.fetch_decision_text(bedesten_decisions[0])
            print(
                f"BEDESTEN_FETCH ({time.monotonic() - t1:.2f}s): len={len(full_text) if full_text else None}",
                flush=True,
            )
            if full_text:
                print("  BEDESTEN_HEAD:", repr(full_text[:200]), flush=True)
            else:
                ok = False
        else:
            ok = False

        t2 = time.monotonic()
        kvkk_decisions = await client.search("kişisel veri", category="data_protection")
        print(
            f"KVKK_SEARCH ({time.monotonic() - t2:.2f}s): count={len(kvkk_decisions)}",
            flush=True,
        )
        for item in kvkk_decisions:
            print(
                "  KVKK_ITEM:",
                json.dumps(
                    {
                        "source": item.source,
                        "title": item.title,
                        "url": item.url,
                        "excerpt_len": len(item.excerpt or ""),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        if kvkk_decisions:
            kvkk_text = await client.fetch_decision_text(kvkk_decisions[0])
            print("KVKK_FETCH_LEN:", len(kvkk_text) if kvkk_text else None, flush=True)

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as raw_http:
            emsal_raw = await client._call_tool(
                raw_http, "search_emsal_detailed_decisions", {"keyword": "depozito", "page_number": 1}
            )
            emsal_decisions = await client._decisions_from_emsal_result(raw_http, "depozito", emsal_raw)
            print(f"EMSAL_SEARCH: count={len(emsal_decisions)}", flush=True)
            if emsal_decisions:
                print(
                    "  EMSAL_ITEM:",
                    json.dumps(
                        {
                            "source": emsal_decisions[0].source,
                            "title": emsal_decisions[0].title,
                            "url": emsal_decisions[0].url,
                            "excerpt_len": len(emsal_decisions[0].excerpt or ""),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    finally:
        if client is not None:
            await client.aclose()
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return ok


async def _timed(name: str, coro):
    t0 = time.monotonic()
    print(f"STEP {name}...", flush=True)
    try:
        res = await coro
        print(f"  OK ({time.monotonic() - t0:.2f}s)", flush=True)
        return res, None
    except Exception as exc:
        print(f"  ERR ({time.monotonic() - t0:.2f}s): {type(exc).__name__}: {str(exc)[:180]}", flush=True)
        return None, exc


async def run_gemini_smoke() -> bool:
    base = Settings()
    if not base.gemini_api_key:
        print("GEMINI_KEY_MISSING", flush=True)
        return False

    paced = base.model_copy(
        update={"llm_min_interval_seconds": max(base.llm_min_interval_seconds, 3.0)}
    )
    gate = CallGate.from_settings(paced)
    http_opts = types.HttpOptions(
        timeout=45000,
        retry_options=types.HttpRetryOptions(attempts=1),
    )
    client = genai.Client(api_key=paced.gemini_api_key, http_options=http_opts)
    print(
        f"GEMINI_CONFIG: model={paced.gemini_model} ocr_model={paced.ocr_model or paced.gemini_model} "
        f"embedding_model={paced.embedding_model} interval={paced.llm_min_interval_seconds}s",
        flush=True,
    )

    sample_text = (
        "KONUT KİRA SÖZLEŞMESİ\n"
        "Taşınmaz: Kadıköy/İstanbul.\n"
        "MADDE 1 - DEPOZİTO\n"
        "Kiracı 5 aylık kira bedeli olan 100.000 TL depozito öder; depozito hiçbir şartta iade edilmez.\n"
        "MADDE 2 - KONUTA GİRİŞ\n"
        "Kiraya veren dilediği zaman kiracının izni olmaksızın konuta girebilir.\n"
    )
    clauses = [
        Clause(id="preamble", title="Başlangıç", text="KONUT KİRA SÖZLEŞMESİ\nTaşınmaz: Kadıköy/İstanbul."),
        Clause(
            id="clause-1",
            title="MADDE 1 - DEPOZİTO",
            text="Kiracı 5 aylık kira bedeli olan 100.000 TL depozito öder; depozito hiçbir şartta iade edilmez.",
        ),
        Clause(
            id="clause-2",
            title="MADDE 2 - KONUTA GİRİŞ",
            text="Kiraya veren dilediği zaman kiracının izni olmaksızın konuta girebilir.",
        ),
    ]

    analyzer = GeminiContractAnalyzer(paced, gate)
    analyzer._client = client

    summary, err1 = await _timed("1 summarize_contract", analyzer.summarize_contract(sample_text, contract_type="lease"))
    if summary:
        print("  LIVE_SUMMARY:", repr(summary[:160]), flush=True)

    findings, err2 = await _timed("2 classify_risks", analyzer.classify_risks(clauses, contract_type="lease", party="tenant"))
    if findings is not None:
        print("  LIVE_FINDINGS:", [(f.id, f.category, f.severity, f.clause_id, f.disadvantaged_party) for f in findings], flush=True)

    facts, err3 = await _timed("3 extract_contract_facts", analyzer.extract_contract_facts(clauses, contract_type="lease"))
    if facts is not None:
        print("  LIVE_FACTS:", [(f.name, f.clause_id, f.value, f.extracted_by) for f in facts], flush=True)

    presence, err4 = await _timed("4 detect_missing_clauses", analyzer.detect_missing_clauses(clauses, contract_type="lease"))
    if presence is not None:
        print("  LIVE_MISSING_PRESENCE:", {k: v.present for k, v in presence.items()}, flush=True)

    target_finding = (findings or [
        RiskFinding(
            id="finding-1",
            category="deposit_forfeiture",
            severity="high",
            explanation="Depozito sınırı aşılıyor ve iade edilmiyor.",
            recommendation="Yasal sınıra indirin.",
            clause_id="clause-1",
        )
    ])[0]

    rewrites, err5 = await _timed("5 suggest_rewrites", analyzer.suggest_rewrites([(clauses[1], [target_finding])], "lease", "tenant"))
    if rewrites is not None:
        print("  LIVE_REWRITES:", [(r.clause_id, r.generated_by, r.suggested_text[:100]) for r in rewrites], flush=True)

    queries, err6 = await _timed("6 build_legal_queries", analyzer.build_legal_queries([target_finding], contract_type="lease"))
    if queries is not None:
        print("  LIVE_QUERIES:", queries, flush=True)

    sample_decisions = [
        YargiDecision(
            source="Yargi MCP / Bedesten",
            title="Yargıtay 3. HD E. 2019/1234",
            relevance="Depozito iadesi",
            excerpt="6098 sayılı TBK m.342 uyarınca güvence bedeli üç aylık kirayı aşamaz.",
        )
    ]
    grades, err7 = await _timed("7 grade_decisions", analyzer.grade_decisions(target_finding, sample_decisions))
    if grades is not None:
        print("  LIVE_GRADES:", [(g.grade, g.reason) for g in grades], flush=True)

    rewritten_q, err8 = await _timed(
        "8 rewrite_query",
        analyzer.rewrite_query(
            target_finding,
            [(queries or {}).get(target_finding.id, "depozito")],
            "Adaylar konuyla ilgisiz çıktı.",
            contract_type="lease",
        ),
    )
    if rewritten_q is not None:
        print("  LIVE_REWRITE_QUERY:", repr(rewritten_q), flush=True)

    embedder = GeminiEmbedder(paced, gate)
    embedder._client = client
    report = ContractReport(
        contract_summary=summary or "Özet",
        risk_score=70,
        risk_level="high",
        contract_type="lease",
        party="tenant",
        clauses=clauses,
        findings=findings or [target_finding],
    )
    index, err9 = await _timed("9 build_index (embeddings)", build_index(report, embedder, max_chars=800))
    if index is not None:
        print(
            f"  LIVE_EMBEDDING: dense_available={index.dense_available} error={index.dense_error} "
            f"chunks={len(index.chunks)} dim={len(index.vectors[0]) if index.vectors else None}",
            flush=True,
        )

    ans = None
    if index is not None:
        retrieved, _ = await _timed(
            "10a chat retrieve (covered)",
            retrieve(index, "Depozitoyu geri alabilir miyim?", embedder, mode="hybrid"),
        )
        if retrieved is not None:
            print(
                "  LIVE_CHAT_RETRIEVE_COVERED:",
                retrieved.mode,
                [(r.chunk.id, r.dense_score, r.lexical_score) for r in retrieved.chunks[:3]],
                flush=True,
            )
            answerer = GeminiChatAnswerer(paced, gate)
            answerer._client = client
            ans, _ = await _timed(
                "10b chat answer",
                answerer.answer("Depozitoyu geri alabilir miyim?", [], [r.chunk for r in retrieved.chunks]),
            )
            if ans is not None:
                print("  LIVE_CHAT_ANSWER:", ans.answered_by, ans.cited_ids, ans.notes, repr(ans.text), flush=True)

        oob_ret, _ = await _timed(
            "10c chat retrieve (OOB)",
            retrieve(index, "Evcil hayvan beslemek serbest mi?", embedder, mode="hybrid"),
        )
        if oob_ret is not None:
            print(
                "  LIVE_CHAT_RETRIEVE_OOB:",
                oob_ret.mode,
                [(r.chunk.id, r.dense_score, r.lexical_score) for r in oob_ret.chunks],
                flush=True,
            )

    pages = render_pdf_pages(_sample_pdf_bytes(), dpi=150)
    ocr_engine = GeminiOcrEngine(paced, gate)
    ocr_engine._client = client
    ocr_raw, ocr_err = await _timed("11a GeminiOcrEngine (active model)", ocr_engine.transcribe_page(pages[0]))
    if ocr_raw is not None:
        print("  LIVE_OCR_TEXT:", repr(clean_transcription(ocr_raw)), flush=True)

    gemma_ocr_settings = paced.model_copy(update={"ocr_model": "gemma-4-26b-a4b-it"})
    gemma_ocr_engine = GeminiOcrEngine(gemma_ocr_settings, gate)
    gemma_ocr_engine._client = client
    gemma_ocr_raw, gemma_ocr_err = await _timed("11b GeminiOcrEngine (gemma-4-26b-a4b-it)", gemma_ocr_engine.transcribe_page(pages[0]))
    if gemma_ocr_raw is not None:
        print("  GEMMA4_OCR_TEXT:", repr(clean_transcription(gemma_ocr_raw)), flush=True)

    warnings = analyzer.drain_warnings()
    print("ANALYZER_WARNINGS:", warnings, flush=True)
    return bool(index and index.dense_available and ocr_raw and not warnings)


async def run_e2e_smoke(port: int) -> bool:
    base = Settings()
    if not base.gemini_api_key:
        print("GEMINI_KEY_MISSING", flush=True)
        return False

    cmd = [
        "uvx",
        "--with",
        "mcp<1.26",
        "--with",
        "fastmcp<2.15",
        "--with",
        "uvicorn[standard]",
        "--from",
        "yargi-mcp",
        "uvicorn",
        "asgi_app:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    yargi_client: RemoteYargiMcpClient | None = None
    try:
        ready = False
        for _ in range(50):
            if proc.poll() is not None:
                break
            try:
                res = httpx.get(f"http://127.0.0.1:{port}/health", trust_env=False, timeout=2.0)
                if res.status_code == 200:
                    ready = True
                    break
            except Exception:
                await asyncio.sleep(0.3)
        if not ready:
            print(f"E2E_YARGI_START_FAILED: returncode={proc.poll()}", flush=True)
            return False

        e2e_settings = base.model_copy(
            update={
                "yargi_mcp_url": f"http://127.0.0.1:{port}/mcp/",
                "use_remote_yargi": True,
                "yargi_request_timeout_seconds": 30.0,
                "yargi_max_results_per_finding": 3,
                "crag_use_llm_grader": True,
                "crag_max_rewrites": 1,
                "crag_max_fetches_per_round": 6,
                "tufe_12m_average_change_percent": 45.0,
                "llm_min_interval_seconds": max(base.llm_min_interval_seconds, 3.0),
            }
        )
        gate = CallGate.from_settings(e2e_settings)
        analyzer = GeminiContractAnalyzer(e2e_settings, gate)
        yargi_client = RemoteYargiMcpClient(e2e_settings)
        sample_contract = (
            "KONUT KİRA SÖZLEŞMESİ\n"
            "Taşınmaz: Kadıköy / İstanbul.\n"
            "MADDE 1 - GÜVENCE BEDELİ\n"
            "Kiracı 5 aylık kira bedeli olan 100.000 TL depozito öder; depozito hiçbir şartta iade edilmez.\n"
            "MADDE 2 - KONUTA GİRİŞ\n"
            "Kiraya veren dilediği zaman kiracının izni olmaksızın konuta girebilir.\n"
        )
        t0 = time.monotonic()
        report = await analyze_contract(
            file_name="live_e2e_lease.docx",
            file_type="docx",
            raw_text=sample_contract,
            contract_type="lease",
            party="tenant",
            analyzer=analyzer,
            yargi_client=yargi_client,
            app_settings=e2e_settings,
        )
        print(f"E2E_ANALYZE_DONE ({time.monotonic() - t0:.2f}s)", flush=True)
        print("E2E_SCORE:", report.risk_score, report.risk_level, flush=True)
        print(
            "E2E_FINDINGS:",
            [(f.id, f.category, f.severity, f.detected_by, len(f.legal_references)) for f in report.findings],
            flush=True,
        )
        print(
            "E2E_CHECKS:",
            [(c.rule_id, c.status, c.extracted_by) for c in report.statutory_checks],
            flush=True,
        )
        print("E2E_MISSING_COUNT:", len(report.missing_clauses), flush=True)
        print("E2E_REWRITES:", [(r.clause_id, r.generated_by) for r in report.rewrites], flush=True)
        print(
            "E2E_TRACE:",
            [
                {
                    "finding_id": tr.finding_id,
                    "status": tr.status,
                    "rewrites_used": tr.rewrites_used,
                    "attempts": [
                        (a.attempt, a.query, a.candidates, a.relevant, a.ambiguous, a.grader)
                        for a in tr.attempts
                    ],
                }
                for tr in report.retrieval_trace
            ],
            flush=True,
        )
        print(
            "E2E_DECISIONS:",
            [(d.source, d.title, d.grade, d.graded_by, len(d.excerpt or "")) for d in report.related_decisions],
            flush=True,
        )
        print("E2E_LIMITATIONS:", report.limitations, flush=True)

        embedder = GeminiEmbedder(e2e_settings, gate)
        index = await build_index(report, embedder, max_chars=800)
        ret = await retrieve(index, "Depozitoyu geri alabilir miyim?", embedder, mode="hybrid")
        answerer = GeminiChatAnswerer(e2e_settings, gate)
        ans = await answerer.answer(
            "Depozitoyu geri alabilir miyim?", [], [item.chunk for item in ret.chunks]
        )
        print(
            "E2E_CHAT:",
            {"dense": index.dense_available, "answered_by": ans.answered_by, "cited": ans.cited_ids, "text": ans.text},
            flush=True,
        )
        return bool(report.findings and report.related_decisions and index.dense_available and ans.answered_by == "llm")
    finally:
        if yargi_client is not None:
            await yargi_client.aclose()
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yargi", action="store_true")
    parser.add_argument("--gemini", action="store_true")
    parser.add_argument("--e2e", action="store_true")
    parser.add_argument("--port", type=int, default=8011)
    args = parser.parse_args()

    ok = True
    if args.yargi:
        ok = await run_yargi_smoke(args.port) and ok
    if args.gemini:
        ok = await run_gemini_smoke() and ok
    if args.e2e:
        ok = await run_e2e_smoke(args.port) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

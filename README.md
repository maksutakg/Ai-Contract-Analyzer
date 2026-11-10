# Law RAG - Contract Analysis & Legal Precedent Retrieval System

This project is an AI-powered smart contract analysis system that detects risks in Turkish contracts using Large Language Models (LLMs) and dynamically retrieves corresponding precedent decisions from the Court of Cassation, Council of State, and KVKK via live Yargı MCP integration.

## Features

*   **Contract Summary:** High-level summary of key contract terms (parties, purpose, duration, price, payment, IP, and termination) in Turkish using LLMs. Long contracts are summarised in parts and the part summaries are combined, so nothing is truncated.
*   **Segmentation:** Rule-based clause segmentation. Recognises `MADDE 1 - ...`, `Madde 1:`, `MADDE 1.`, `Madde 1 Başlık`, `ARTICLE 1`, numbered headings (`1.`, `1)`) and sub-numbered headings (`1.1`, used as clauses only when the document has no higher-level headings). Dates, amounts, cross references (`Madde 5 uyarınca`) and numbered lists inside a clause are not treated as headings. Falls back to paragraphs when no headings are found. Text before the first heading (title, contract number, parties block) is kept as a clause with id `preamble` (title `Başlangıç`), so nothing in the document is discarded; signals such as "KONUT KİRA SÖZLEŞMESİ" often appear only there.
*   **Document loading and OCR:** PDF (text layer), DOCX (paragraphs **and table cells**, in document order; each table row becomes one line with cells separated by ` | `) and images (`.jpg`, `.jpeg`, `.png`). OCR is used for images and for PDFs whose text layer is missing or too thin to be a contract: the average number of non-whitespace characters per page is below `OCR_MIN_TEXT_CHARS_PER_PAGE` (default 200; a typed contract page has well over a thousand, a scanned page none or only a stamp or page number). PDF pages are rendered with `pypdfium2` (no system install) and each page image is transcribed, one page at a time through the same call gate as the analysis, by the Gemini-API model in `OCR_MODEL` (default: `GEMINI_MODEL`) with a prompt asking for the text exactly as written, keeping clause numbering and line breaks, without commentary. At most `OCR_MAX_PAGES` pages (default 10). The report's `ocr` field records the reason, the page count, failed pages and the model, and `limitations` warn that the transcription may contain errors and that page images were sent to the model provider. If OCR is needed but cannot run, the analyze endpoint returns a specific error instead of a 500: `ocr_disabled` (422, `OCR_ENABLED=false`), `ocr_unavailable` (503, no `GEMINI_API_KEY`), `ocr_page_limit_exceeded` (413), `ocr_failed` (502, every page failed). A page that fails is replaced by `[Sayfa N okunamadı]` and listed in `ocr.failed_pages`.
*   **Risk Analysis:** Detects legal risks in Turkish with recommendations. Clauses are classified in batches under a character budget (`LLM_CLAUSE_BATCH_CHARS`), with at most `LLM_MAX_FINDINGS_PER_BATCH` findings per batch; results are merged, de-duplicated per (category, clause) and renumbered.
*   **Categories:** One registry (`src/law_rag/categories.py`) owns the canonical categories, aliases, Turkish labels, keyword relevance terms and fallback search queries: `cash_payment`, `deposit_forfeiture`, `termination`, `penalty_clause`, `unlawful_entry`, `eviction_undertaking`, `rent_increase`, `jurisdiction`, `data_protection`, `intellectual_property`, `force_majeure`, `payment_interest`, `liability`, `dispute_resolution`, `probation_period`, `non_compete`, `general_risk`.
*   **Rule-based analyzer:** A finding is attributed to the clause whose own text matches the rule; neighbouring clauses are only supporting context. It reports at most one finding per category, and when it is used as a per-batch fallback, its findings are de-duplicated per category across batches.
*   **Dynamic Querying:** One Turkish search query per finding is generated once and stored in the graph state, keyed by finding id.
*   **Corrective RAG retrieval:** Retrieval is a LangGraph loop: `retrieve -> grade -> (rewrite query -> retrieve again) | select -> compose`. Candidates without text are hydrated via `fetch_decision_text` (bounded by `CRAG_MAX_FETCHES_PER_ROUND`). A keyword check is a cheap pre-filter; the LLM then labels each remaining candidate `relevant` / `ambiguous` / `irrelevant` with a one-sentence Turkish reason. A finding with no relevant decision gets its query rewritten (at most `CRAG_MAX_REWRITES` times) and only that finding is searched again. Set `CRAG_USE_LLM_GRADER=false` to grade with keywords only.
*   **No silent fallback:** If a Gemini call fails and the rule-based analyzer or keyword grader is used instead, the report's `limitations` say so.
*   **Party perspective:** `contract_type` is one of `lease`, `service`, `employment`, `other` (Turkish aliases such as `kira`, `hizmet`, `iş sözleşmesi` are accepted; an unrecognised value is passed through and analysed neutrally). The optional `party` is the user's side: `tenant` / `landlord` (lease), `client` / `provider` (service), `employee` / `employer` (employment); aliases such as `kiracı`, `kiraya veren`, `işçi`, `işveren` work, and a party alone implies its type when no type is given. Every finding records `disadvantaged_party` (a role id or `both`). With a party, the classifier is told whose interests to protect and writes recommendations for that side; findings that disadvantage only the other side stay in the report with `applies_to_user=false` and are excluded from the risk score, the recommended actions and the rewrites. Without a party the analysis is neutral, as before. The rule-based analyzer uses a static category-to-side mapping (`src/law_rag/contract_types.py`).
*   **Statutory limit checks (code, not LLM):** The LLM (offline: regex) only extracts facts such as deposit months, a fixed rent increase, a probation period or a non-compete duration (`src/law_rag/facts.py`); deterministic rules in `src/law_rag/statutory_rules.py` compare them with the limits. Each result has a `status` (`violation`, `ok`, `needs_review`, `not_applicable`), the extracted value, the limit, the clause id, a Turkish explanation and its legal basis. A violation becomes a finding with `confidence=1.0` and `detected_by="statutory_rule"`; an analyzer finding on the same clause and category is merged into it. Rules (verified against the consolidated texts on mevzuat.gov.tr):
    *   lease: deposit at most three months' rent (TBK 6098 m.342); renewal-period increase capped by the 12-month average CPI change (m.344); no late-payment penalty or acceleration clause (m.346); eviction undertaking must postdate handover (m.352/1). Lease rules give `needs_review` when the text does not show a residential or roofed-workplace lease.
    *   employment: probation at most two months, four with a collective agreement (İş Kanunu 4857 m.15); notice periods at least 2/4/6/8 weeks by seniority (m.17); non-compete at most two years (TBK m.445).
    *   The CPI rate changes monthly, so it comes from `TUFE_12M_AVERAGE_CHANGE_PERCENT`; when unset, a fixed-percentage increase is reported as `needs_review` rather than compared with a guessed value.
    *   When no contract type is given, the checks and the checklist below use a keyword guess of the type, and `limitations` say so.
*   **Statute grounding:** Each finding gets `legal_references` (law name and number, article, short Turkish paraphrase, official URL) from a curated mapping in `src/law_rag/statutes.py`, keyed by category and contract type. The LLM is never the source of a law or article number; LLM rewrites that cite one are rejected and replaced by the template.
*   **Missing clauses:** A curated checklist per contract type (`src/law_rag/missing_clauses.py`). Presence is decided by the LLM in one call over clause titles and text, with keyword matching as fallback and offline. Each missing topic has an `importance`, a Turkish explanation from the user's side and a short suggested clause. **Missing clauses do not change the risk score.**
*   **Clause rewrites and DOCX export:** For every clause with at least one finding that applies to the user, one Turkish replacement text and a one- or two-sentence rationale, covering all of the clause's findings (LLM in batches of `LLM_CLAUSE_BATCH_CHARS`; deterministic templates per category offline and as fallback). `POST /api/v1/contracts/export-docx` takes a report JSON and returns a `.docx` of the revised contract: all clauses in order, rewritten ones replaced by the suggestion, highlighted and labelled `[DEĞİŞTİRİLDİ]`, followed by an appendix table (original, suggestion, reason, related risk). The service stores nothing. Word tracked changes are not produced.

*   **Chat with the analysed contract (retrieval-augmented generation):** After an analysis, a chat session is created from the report and the user asks questions such as "Depozitomu geri alabilir miyim?". Details below.

### Contract chat

**Knowledge base.** One per session, built from the report: `clause` chunks (long clauses split on sentence boundaries at `CHAT_CHUNK_MAX_CHARS`), `finding` (explanation, recommendation and the curated statute references), `statutory_check`, `missing_clause` (with the suggested clause), `rewrite` and `decision` (related court decisions). Chunk ids are stable and derived from the report: `clause-3`, `clause-3-part2`, `finding-1`, `check-lease_deposit_cap`, `missing-deposit`, `rewrite-clause-3`, `decision-1`; chunks also carry the `clause_id` they belong to.

**Retrieval** (`law_rag.chat_index.retrieve`, usable without answer generation; mode `hybrid`, `dense` or `lexical`):
*   Lexical: BM25 (k1=1.2, b=0.75) over diacritic-free tokens (`text_utils.searchable`), stopwords removed, each token truncated to its first 5 characters as a simple stemmer for Turkish. A chunk counts as a lexical match when its score is at least 0.5 and the question terms it contains carry at least 35% of the question's IDF mass.
*   Dense: cosine similarity of embeddings from the Gemini embeddings endpoint via google-genai (`EMBEDDING_MODEL`, default `gemini-embedding-001`, task types `RETRIEVAL_DOCUMENT` / `RETRIEVAL_QUERY`, `EMBEDDING_DIMENSIONS` default 768, vectors normalised). A dense match needs a similarity of at least `CHAT_MIN_DENSE_SIMILARITY` (default 0.65 for Gemini, calibrated on the evaluation set; 0.3 for the offline embedder).
*   Hybrid: reciprocal rank fusion of the two match lists, `score = Σ 1 / (60 + rank)`; the top `CHAT_TOP_K` chunks are used.
*   If the embedding call fails (at session creation or for a question), retrieval falls back to lexical-only and the response says so in `notes`.
*   Offline, a deterministic embedder (hashed character 3/4-grams of each word's first 7 characters) stands in, so "depozitomu" finds the deposit clause without a key.
*   The thresholds are heuristics; `retrieve(..., apply_threshold=False)` returns raw ranked scores for evaluation.

**Answering.** If no chunk passes the thresholds, the reply is a fixed Turkish "not covered by this contract" message and no LLM call is made. Otherwise one call (`GEMINI_MODEL`) receives the question, the last `CHAT_HISTORY_TURNS` exchanges and the retrieved chunks, and must answer in Turkish from those chunks only, citing chunk ids in square brackets, or say the contract does not cover the question. The output is validated: citations of chunks that were not supplied are removed; statute or article numbers that do not appear in the supplied chunks trigger one regeneration and are then replaced by "ilgili kanun hükmü"; an answer without a valid citation after the regeneration, or a failed call, is replaced by an extractive answer quoting the top chunks, with a note. Every response includes the answer, the cited chunks (`id`, `type`, `clause_id`, `title`, `snippet`), `covered`, `answered_by` (`llm`, `extractive`, `not_covered`), `retrieval_mode`, `notes` and a standing disclaimer that this is not legal advice. Offline the answer is extractive.

**Storage.** Nothing is written to disk. A session (the chunked report, its embeddings and the recent questions and answers) lives only in the server process's memory. It expires `CHAT_SESSION_TTL_SECONDS` (default 1800) after its last use — each question extends it — can be deleted explicitly, and is lost when the process restarts. At most `CHAT_MAX_SESSIONS` (default 50) sessions exist at once; expired sessions are purged first. Note what does leave the process: with a `GEMINI_API_KEY`, chunk texts and questions are sent to the Gemini API for embeddings and answers (and page images for OCR, see above), under the provider's terms.

### LLM pacing

LLM calls are sequential by default (`LLM_MAX_CONCURRENCY=1`). On a free-tier key, also set `LLM_MIN_INTERVAL_SECONDS` (for example `2`) to space calls out. A full analysis makes roughly: summary parts + 1, one call per clause batch for classification, one per clause batch for statutory fact extraction (lease and employment only), one for missing clauses, one per batch of rewritten clauses, and per finding one query call plus one grading call and at most one rewrite call per CRAG round. `STATUTORY_CHECKS_ENABLED`, `MISSING_CLAUSES_ENABLED` and `CLAUSE_REWRITES_ENABLED` (all default `true`) turn the new steps off. OCR adds one call per page. A chat session costs one embedding call per `EMBEDDING_BATCH_SIZE` chunks at creation, then per question one embedding call and one answer call (at most two). Chat sessions share one process-wide gate.

### Risk score

Each finding contributes a probability `p = w(severity) * confidence` with `w(low)=0.10`, `w(medium)=0.25`, `w(high)=0.45`, `w(critical)=0.70`. The score is a noisy-OR:

```
risk_score = round(100 * (1 - Π (1 - p_i)))
```

Only findings with `applies_to_user=true` count (all findings when no party is given); missing clauses never count.

Levels: `< 25` low, `25-49` medium, `50-74` high, `>= 75` critical. More findings always raise the score, but it approaches 100 gradually instead of saturating. The previous formula (`max(average, highest) + min(20, 4*(n-1))`, thresholds 25/50/90) is kept as `calculate_risk_score_legacy` / `risk_level_for_score_legacy` in `src/law_rag/risk.py` for comparison.

## Setup & Running

This project uses `uv` for dependency management and execution.

### 1. Environment Setup

Copy `.env.example` to `.env` and fill in your API credentials:

```bash
cp .env.example .env
```

Your `.env` file should be configured as follows:

```ini
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.5-flash-lite
YARGI_MCP_URL=http://127.0.0.1:8001/mcp/
USE_REMOTE_YARGI=true
YARGI_MAX_RESULTS_PER_FINDING=3
YARGI_MAX_TOTAL_DECISIONS=10
YARGI_REQUEST_TIMEOUT_SECONDS=30
MAX_UPLOAD_BYTES=10485760

# LLM pacing and long-contract handling
LLM_MAX_CONCURRENCY=1
LLM_MIN_INTERVAL_SECONDS=0
LLM_CLAUSE_BATCH_CHARS=6000
LLM_MAX_FINDINGS_PER_BATCH=6
LLM_SUMMARY_CHUNK_CHARS=6000

# Corrective RAG loop
CRAG_USE_LLM_GRADER=true
CRAG_MAX_REWRITES=2
CRAG_MAX_FETCHES_PER_ROUND=6

# Statutory checks, missing clauses, rewrites
STATUTORY_CHECKS_ENABLED=true
MISSING_CLAUSES_ENABLED=true
CLAUSE_REWRITES_ENABLED=true
# 12-month average CPI change in percent (TÜİK); leave unset to get needs_review
TUFE_12M_AVERAGE_CHANGE_PERCENT=

# OCR (images, scanned PDFs)
OCR_ENABLED=true
# empty: GEMINI_MODEL
OCR_MODEL=
OCR_MAX_PAGES=10
OCR_MIN_TEXT_CHARS_PER_PAGE=200
OCR_RENDER_DPI=150

# Contract chat
EMBEDDING_MODEL=gemini-embedding-001
EMBEDDING_DIMENSIONS=768
EMBEDDING_BATCH_SIZE=100
CHAT_SESSION_TTL_SECONDS=1800
CHAT_MAX_SESSIONS=50
CHAT_TOP_K=6
CHAT_HISTORY_TURNS=3
CHAT_CHUNK_MAX_CHARS=800
# empty: embedder default (0.65 Gemini, 0.3 offline)
CHAT_MIN_DENSE_SIMILARITY=
```

### 2. Start Local Yargı MCP Server (for Live Case-Law Retrieval)

When `USE_REMOTE_YARGI=true` with the local default `YARGI_MCP_URL=http://127.0.0.1:8001/mcp/`, start the local `yargi-mcp` HTTP server in a separate terminal:

```bash
uv run python scripts/run_yargi_mcp.py
```

### 3. Start the Server

To launch the FastAPI server, run:

```bash
uv run python main.py
```

Once the server has started, the interactive API documentation (Swagger UI) will be available at:
`http://localhost:8000/docs`

---

## API Usage

### Health Check

```bash
curl "http://localhost:8000/health"
```

### Contract Analysis

Analyze a contract (PDF, DOCX, or a JPG/PNG photo or scan) by sending a multipart/form-data request to the `POST /api/v1/contracts/analyze` endpoint:

```bash
curl -X POST "http://localhost:8000/api/v1/contracts/analyze" \
  -F "contract_type=lease" \
  -F "party=tenant" \
  -F "file=@contract.pdf"
```

`contract_type` and `party` are optional (see *Party perspective* above).

### Revised contract export

Send a report returned by the analyze endpoint back to get the revised contract as Word:

```bash
curl -X POST "http://localhost:8000/api/v1/contracts/export-docx" \
  -H "Content-Type: application/json" \
  --data @report.json -o revize-sozlesme.docx
```

Invalid report JSON gives `422` (`invalid_report`), a report without clauses `400` (`no_clauses`), a body above `MAX_UPLOAD_BYTES` `413`.

### Contract chat

```bash
# 1. create a session from a report returned by the analyze endpoint (201)
curl -X POST "http://localhost:8000/api/v1/chat/sessions" \
  -H "Content-Type: application/json" --data @report.json
# -> {"session_id": "...", "expires_at": "...", "chunk_count": 27, "retrieval_mode": "hybrid", ...}

# 2. ask questions
curl -X POST "http://localhost:8000/api/v1/chat/sessions/<session_id>/messages" \
  -H "Content-Type: application/json" -d '{"question": "Depozitomu geri alabilir miyim?"}'

# 3. delete the session (204)
curl -X DELETE "http://localhost:8000/api/v1/chat/sessions/<session_id>"
```

An unknown, expired or deleted session gives `404` (`chat_session_not_found`); too many live sessions `429` (`chat_session_limit`); report errors are as for the export endpoint.

---

## Output JSON Schema

The analysis report returns a JSON payload with the following fields:

*   **`contract_summary`** (string): High-level Turkish legal summary of the contract.
*   **`risk_score`** (integer): Calculated overall risk score of the contract (0-100).
*   **`risk_level`** (string): Overall risk classification (`low`, `medium`, `high`, `critical`).
*   **`clauses`** (array): Extracted list of clauses containing `id`, `title`, and `text`.
*   **`contract_type`** / **`party`**: The normalised contract type and the user's role id (`null` for a neutral analysis).
*   **`findings`** (array): Identified risk findings:
    *   `id`: Finding identifier.
    *   `category`: Risk category (e.g., `data_protection`, `intellectual_property`, `termination`, `penalty_clause`, `probation_period`, `non_compete`).
    *   `severity`: Risk severity level.
    *   `explanation`: Explanation of the risk in Turkish.
    *   `recommendation`: Actionable advice in Turkish.
    *   `clause_id`: Referenced clause ID.
    *   `disadvantaged_party`: Role id the clause works against, `both`, or `null` if unknown.
    *   `applies_to_user`: `false` when a party was given and the finding only disadvantages the other side.
    *   `detected_by`: `llm`, `rule_based` or `statutory_rule`; `statutory_check_id` names the rule for the latter.
    *   `legal_references`: Curated statute provisions (`law_name`, `law_number`, `article`, `summary`, `url`).
*   **`recommended_actions`** (array of strings): Quick action list for contract redlines (findings that apply to the user only).
*   **`statutory_checks`** (array): `rule_id`, `title`, `status`, `clause_id`, `extracted_value`, `limit`, `explanation` (Turkish), `legal_basis`, `finding_id` (for violations), `extracted_by` (`llm` / `rule_based`).
*   **`missing_clauses`** (array): `topic`, `title`, `importance` (`low` / `medium` / `high`), `explanation`, `suggested_clause`, `detected_by`.
*   **`rewrites`** (array): `clause_id`, `finding_ids`, `original_text`, `suggested_text`, `rationale`, `generated_by` (`llm` / `rule_based`).
*   **`related_decisions`** (array): Precedent legal decisions matched on Yargı MCP (source, title, excerpt, URL), plus `finding_id`, the `query` and `attempt` that found it, its `grade` (`relevant` / `ambiguous`), `grade_reason` (Turkish) and `graded_by` (`llm` / `keyword`). Ambiguous decisions appear only for findings with no relevant decision.
*   **`retrieval_trace`** (array): Per finding: `finding_id`, `category`, `queries` (in the order tried), `attempts` (per attempt: `query`, `candidates`, `relevant`, `ambiguous`, `irrelevant`, `grader`, `error`) and the final `status` (`relevant`, `exhausted` or `failed`).
*   **`ocr`** (object or `null`): Set when the text was transcribed: `reason` (`image_upload` / `thin_text_layer`), `pages`, `failed_pages`, `engine` (`gemini` / `fake`), `model`.
*   **`limitations`** (array): Encountered technical limits or retrieval constraints.

---

## Running Tests & Evaluation

To run the unit test suite:

```bash
uv run pytest
```

To run the offline evaluation harness (`scripts/evaluate.py`, see `scripts/eval_data/ANNOTATION_GUIDE.md` for labeling additional contracts) or include live Gemini API checks (`--live`):

```bash
uv run python scripts/evaluate.py
uv run python scripts/evaluate.py --live
```
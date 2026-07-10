# Contract CRAG MVP Design

Date: 2026-05-19

## Purpose

Build an MVP backend for company legal and procurement teams that analyzes a single PDF or DOCX contract, assigns a risk score, retrieves relevant Turkish judicial decisions through Yargi MCP, and returns a structured JSON report through a REST API.

This MVP does not persist contracts, build a long-term vector index, or provide a dashboard. Those belong to later phases.

## Users

Primary users are non-technical legal department and procurement staff consuming the backend through an enterprise dashboard or another internal client. The API response must be deterministic enough for dashboard integration and readable enough for legal review.

## Scope

The MVP accepts one contract file per request. It extracts text, segments contract clauses, analyzes legal and commercial risks, creates Turkish legal search queries, retrieves relevant decisions from Yargi MCP, and returns a JSON report.

Supported input formats:

- PDF
- DOCX

Initial API:

- `POST /api/v1/contracts/analyze`

Input:

- `multipart/form-data`
- `file`: required PDF or DOCX file
- `contract_type`: optional string such as `procurement`, `service`, `license`, `nda`, or `other`

Output:

- `contract_summary`
- `risk_score`
- `risk_level`
- `clauses`
- `findings`
- `recommended_actions`
- `related_decisions`
- `limitations`

## Non-Goals

- Persistent vector database for uploaded contracts
- User accounts, roles, or tenant management
- Dashboard UI
- Contract redlining or DOCX editing
- Legal advice automation without human review
- Fine-tuning or local model hosting

## Technology Choices

- API framework: FastAPI
- Agent workflow: LangGraph
- LLM orchestration: LangChain-compatible adapters where useful
- LLM provider: Gemini API with configurable model name
- Default model setting: `GEMINI_MODEL=gemma-3-27b-it`
- Legal retrieval: remote Yargi MCP server at `https://yargimcp.surucu.dev/mcp`
- Project tooling: uv with the existing virtual environment

The model name remains configuration-driven because the requested "Gemma 4 31B" model identifier was not verified in the official Gemini API documentation. The implementation will avoid hard-coding model names outside configuration.

## Architecture

The backend has four main layers.

API layer:

- Validates uploads.
- Enforces file size and extension limits.
- Calls the LangGraph contract analysis graph.
- Returns JSON errors with stable codes.

Document ingestion layer:

- Extracts text from PDF and DOCX files.
- Normalizes whitespace and page artifacts.
- Preserves enough structural hints for clause segmentation.

Agent graph layer:

- Runs the contract analysis workflow as explicit LangGraph nodes.
- Stores intermediate state in a typed state object.
- Keeps each node independently testable.

Integration layer:

- Calls Gemini API for structured extraction and analysis.
- Calls Yargi MCP for Turkish legal decision search and retrieval.
- Converts external tool failures into partial report warnings instead of crashing the entire analysis when possible.

## LangGraph Workflow

The MVP graph contains these nodes:

1. `parse_document`
   Extracts text and basic metadata from the uploaded PDF or DOCX.

2. `segment_clauses`
   Splits text into clauses using headings, numbering, and model-assisted fallback when needed.

3. `classify_risks`
   Identifies risk categories such as payment, termination, penalty clauses, limitation of liability, confidentiality, data protection, dispute resolution, governing law, delivery, acceptance, warranty, indemnity, and unilateral change rights.

4. `score_contract`
   Produces a 0-100 risk score and one of `low`, `medium`, `high`, or `critical`.

5. `build_legal_queries`
   Builds concise Turkish search queries from the most important findings.

6. `retrieve_yargi_decisions`
   Uses Yargi MCP to search for relevant decisions, with an initial focus on Yargitay, Danistay, Emsal, KVKK, KIK, and Rekabet sources depending on the finding category.

7. `compose_report`
   Produces the final API response with citations, risk rationale, recommended actions, and limitations.

## Risk Scoring

The score is a legal review prioritization signal, not a final legal opinion.

Initial levels:

- `low`: 0-24
- `medium`: 25-49
- `high`: 50-74
- `critical`: 75-100

Each finding contributes severity, confidence, and business impact. The score should be explainable through the returned findings rather than appearing as an opaque number.

## Yargi MCP Retrieval

The graph will generate targeted Turkish queries instead of sending the whole contract to Yargi MCP. Example query themes:

- "cezai sart fahislik tacir sozlesme Yargitay"
- "sorumlulugun sinirlandirilmasi agir kusur Yargitay"
- "hizmet sozlesmesi tek tarafli fesih cezai sart"
- "kisisel verilerin islenmesi veri sorumlusu sozlesme KVKK"

Each related decision should include:

- source
- title or court/chamber metadata when available
- decision date and number when available
- short relevance explanation
- text excerpt or summary when available
- retrieval confidence

## Error Handling

The API returns stable JSON errors for:

- unsupported file type
- unreadable or encrypted file
- empty extracted text
- file size limit exceeded
- LLM provider failure
- Yargi MCP failure

If Yargi MCP fails after contract analysis succeeds, the response may still return findings with `related_decisions` empty and a limitation explaining the retrieval failure.

## Security and Privacy

The MVP should avoid logging full contract text. Logs may include request IDs, file type, byte size, node durations, and error codes.

Secrets are read from environment variables:

- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `YARGI_MCP_URL`

The API should reject suspicious filenames and should not persist uploaded files after analysis unless a later phase explicitly adds storage.

## Testing Strategy

Tests should cover:

- PDF and DOCX extraction paths with small fixtures
- unsupported file validation
- empty text handling
- LangGraph state transitions
- risk scoring boundaries
- structured report schema
- Yargi MCP integration through a mocked client
- provider failure behavior

The MVP can use mocked LLM and MCP clients for deterministic unit tests, with optional integration tests gated behind environment variables.

## Open Decisions

The implementation can choose the exact Python packages for PDF and DOCX parsing based on compatibility with the current Python version and uv environment. The API contract and graph boundaries above should remain stable.

## Acceptance Criteria

- A caller can upload a PDF or DOCX contract to `POST /api/v1/contracts/analyze`.
- The backend returns valid JSON with summary, risk score, findings, recommendations, and related decisions.
- The LangGraph workflow is visible in code as separate named nodes.
- Gemini model configuration is environment-driven.
- Yargi MCP URL is environment-driven and defaults to `https://yargimcp.surucu.dev/mcp`.
- Tests pass for parser validation, graph flow, scoring, and mocked retrieval.

# Law RAG - Contract Analysis & Legal Precedent Retrieval System

This project is an AI-powered smart contract analysis system that detects risks in Turkish contracts using Large Language Models (LLMs) and dynamically retrieves corresponding precedent decisions from the Court of Cassation, Council of State, and KVKK via live Yargı MCP integration.

## Features

*   **Contract Summary:** High-level summary of key contract terms (parties, purpose, duration, price, payment, IP, and termination) in Turkish using LLMs.
*   **Segmentation:** Automatic clause-by-clause segmentation of the contract text.
*   **Risk Analysis:** Detects legal risks and compliance issues (e.g. data protection, termination, intellectual property, penalty clauses) in Turkish with resolution recommendations.
*   **Dynamic Querying:** Dynamically generates optimized Turkish search queries based on identified risks using the LLM.
*   **Legal Precedent Retrieval (CRAG):** Integrates with a live Yargı MCP server to search and fetch relevant legal precedents (Court of Cassation, Council of State, KVKK) based on dynamic queries.
*   **Advanced Filtering:** Filters out irrelevant or empty search results using diacritics-insensitive (Turkish character normalized) checks.

## Setup & Running

### Quick start (Windows)

After creating `.env` (step 1 below), double-click `start.cmd` or run `.\start.ps1`. It builds the web interface if needed, starts the Yargı MCP server in the background (skipped if one already listens on its port), starts the API on `APP_PORT`, and opens the browser. Close the window or press Ctrl+C to stop; the MCP server it started stops too. MCP logs go to `logs/`. Requires `uv` (or `python -m uv`) and Node.js.

The steps below do the same by hand.

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
GEMINI_FALLBACK_MODEL=gemini-3.1-flash-lite
GEMINI_TIMEOUT_SECONDS=60
YARGI_MCP_URL=http://127.0.0.1:8001/mcp/
USE_REMOTE_YARGI=true
YARGI_MAX_RESULTS_PER_FINDING=3
YARGI_MAX_TOTAL_DECISIONS=10
YARGI_FETCH_DOCUMENTS=true
YARGI_REQUEST_TIMEOUT_SECONDS=30
YARGI_TOTAL_TIMEOUT_SECONDS=120
YARGI_MAX_FINDINGS=4
YARGI_MAX_CONCURRENCY=1
MAX_UPLOAD_BYTES=10485760
APP_PORT=8000
```

### 2. Start the Yargı MCP Server

The public hosted endpoint is not reliable, so run [yargi-mcp](https://pypi.org/project/yargi-mcp/) locally in its own isolated environment. Dependencies are pinned to the package's release date because newer `mcp` releases break it:

```bash
uv tool run --python 3.11 --exclude-newer 2026-07-15 --from "yargi-mcp[asgi]==0.2.2" uvicorn asgi_app:app --host 127.0.0.1 --port 8001
```

`YARGI_MCP_URL` must point to `http://127.0.0.1:8001/mcp/`.

### 3. Start the Server

In a second terminal (keep the Yargı MCP server running), launch the FastAPI server:

```bash
uv run python main.py
```

It listens on `127.0.0.1` and the port set by `APP_PORT` (default `8000`; change it if that port is taken). The interactive API documentation (Swagger UI) is then at `http://localhost:<APP_PORT>/docs`.

`.env` is read only at startup, so restart the server after editing it.

### 4. Web Interface

Build the React interface once (requires Node.js); the FastAPI server then serves it at `http://localhost:<APP_PORT>/`:

```bash
cd frontend
npm install
npm run build
```

Restart the FastAPI server after the first build so it picks up `frontend/dist`. Rebuild after changing the frontend. For frontend development with hot reload, run `npm run dev` and set `API_TARGET=http://127.0.0.1:<APP_PORT>`; frontend tests run with `npm test`. Design notes are in `docs/ARCHITECTURE.md` and `docs/DECISIONS.md`.

---

## API Usage

### Health Check

```bash
curl "http://localhost:8000/health"
```

### Contract Analysis

Analyze a contract (PDF or DOCX format) by sending a multipart/form-data request to the `POST /api/v1/contracts/analyze` endpoint:

```bash
curl -X POST "http://localhost:8000/api/v1/contracts/analyze" \
  -F "contract_type=service" \
  -F "file=@contract.pdf"
```

`contract_type` is optional; allowed values are `service` and `lease`.

---

## Output JSON Schema

The analysis report returns a JSON payload with the following fields:

*   **`contract_summary`** (string): High-level Turkish legal summary of the contract.
*   **`risk_score`** (integer): Calculated overall risk score of the contract (0-100).
*   **`risk_level`** (string): Overall risk classification (`low`, `medium`, `high`, `critical`).
*   **`clauses`** (array): Extracted list of clauses containing `id`, `title`, and `text`.
*   **`findings`** (array): Identified risk findings:
    *   `id`: Finding identifier.
    *   `category`: Risk category (e.g., `data_protection`, `intellectual_property`, `termination`, `penalty_clause`).
    *   `severity`: Risk severity level.
    *   `explanation`: Explanation of the risk in Turkish.
    *   `recommendation`: Actionable advice in Turkish.
    *   `clause_id`: Referenced clause ID.
*   **`recommended_actions`** (array of strings): Quick action list for contract redlines.
*   **`related_decisions`** (array): Precedent legal decisions matched on Yargı MCP (source, title, excerpt, and URL).
*   **`limitations`** (array): Encountered technical limits or retrieval constraints.
*   **`llm_engine`** (string): Gemini model that analyzed the contract, or `rules` with the reason when no API key is set.
*   **`yargi_source`** (string): Yargı MCP URL that was queried, or `fake` with the reason when remote search is disabled.

---

## Running Tests

To run the unit test suite:

```bash
uv run pytest
```
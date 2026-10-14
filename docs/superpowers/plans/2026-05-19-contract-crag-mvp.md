# Contract CRAG MVP Implementation Plan

> **Historical document.** This describes the original MVP plan and is no longer kept in sync with the code. See `README.md` for current setup and behavior.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI + LangGraph MVP that accepts one PDF/DOCX contract, analyzes clauses and risks, retrieves mocked or live Yargi MCP decisions, and returns a structured JSON report.

**Architecture:** Keep the backend modular: API routes call a LangGraph workflow, workflow nodes call document parsing, LLM, scoring, and legal retrieval services through typed interfaces. Tests use fake LLM and fake Yargi clients by default so the MVP remains deterministic without external credentials.

**Tech Stack:** Python, uv, FastAPI, Pydantic, LangGraph, Google Gemini API, PDF/DOCX parsing libraries, pytest, httpx.

---

## File Structure

- Create `src/law_rag/__init__.py`: package marker.
- Create `src/law_rag/config.py`: environment-driven settings.
- Create `src/law_rag/models.py`: Pydantic request/response and internal state models.
- Create `src/law_rag/document_loader.py`: PDF/DOCX extraction and validation.
- Create `src/law_rag/llm.py`: LLM protocol, Gemini implementation, deterministic fake implementation.
- Create `src/law_rag/risk.py`: risk level and scoring utilities.
- Create `src/law_rag/yargi_client.py`: Yargi MCP client protocol, HTTP implementation placeholder, fake implementation.
- Create `src/law_rag/graph.py`: LangGraph nodes and compiled graph builder.
- Create `src/law_rag/api.py`: FastAPI app and upload endpoint.
- Modify `main.py`: run the API with uvicorn.
- Modify `pyproject.toml`: package layout, dependencies, dev dependencies.
- Create `tests/`: unit and API tests.

No git or GitHub commands are part of this plan.

---

### Task 1: Project Dependencies And Package Layout

**Files:**
- Modify: `pyproject.toml`
- Create: `src/law_rag/__init__.py`
- Create: `tests/test_imports.py`

- [ ] **Step 1: Write the failing import test**

Create `tests/test_imports.py`:

```python
def test_package_imports() -> None:
    import law_rag

    assert law_rag.__name__ == "law_rag"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_imports.py -q`

Expected: FAIL because `pytest` or `law_rag` is not configured yet.

- [ ] **Step 3: Update project metadata and dependencies**

Set `pyproject.toml` to:

```toml
[project]
name = "law-rag"
version = "0.1.0"
description = "Contract CRAG backend for Turkish legal decision retrieval"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "google-genai>=1.0.0",
    "httpx>=0.27.0",
    "langchain-core>=0.3.0",
    "langgraph>=0.2.0",
    "pydantic>=2.8.0",
    "pydantic-settings>=2.4.0",
    "pypdf>=5.0.0",
    "python-docx>=1.1.2",
    "python-multipart>=0.0.9",
    "uvicorn[standard]>=0.30.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
]

[tool.uv]
package = true

[tool.setuptools.packages.find]
where = ["src"]
```

Create `src/law_rag/__init__.py`:

```python
"""Contract CRAG backend package."""
```

- [ ] **Step 4: Install dependencies and verify test passes**

Run: `uv sync --dev`

Expected: dependencies install successfully.

Run: `uv run pytest tests/test_imports.py -q`

Expected: PASS.

---

### Task 2: Configuration

**Files:**
- Create: `src/law_rag/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write configuration tests**

Create `tests/test_config.py`:

```python
from law_rag.config import Settings


def test_settings_defaults() -> None:
    settings = Settings()

    assert settings.gemini_model == "gemma-3-27b-it"
    assert str(settings.yargi_mcp_url) == "https://yargimcp.surucu.dev/mcp"
    assert settings.max_upload_bytes == 10 * 1024 * 1024


def test_settings_accepts_environment_names() -> None:
    settings = Settings(
        GEMINI_API_KEY="secret",
        GEMINI_MODEL="custom-model",
        YARGI_MCP_URL="https://example.test/mcp",
    )

    assert settings.gemini_api_key == "secret"
    assert settings.gemini_model == "custom-model"
    assert str(settings.yargi_mcp_url) == "https://example.test/mcp"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -q`

Expected: FAIL because `law_rag.config` does not exist.

- [ ] **Step 3: Implement settings**

Create `src/law_rag/config.py`:

```python
from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemma-3-27b-it", alias="GEMINI_MODEL")
    yargi_mcp_url: AnyHttpUrl = Field(
        default="https://yargimcp.surucu.dev/mcp",
        alias="YARGI_MCP_URL",
    )
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, alias="MAX_UPLOAD_BYTES")
```

- [ ] **Step 4: Verify configuration tests pass**

Run: `uv run pytest tests/test_config.py -q`

Expected: PASS.

---

### Task 3: Response And State Models

**Files:**
- Create: `src/law_rag/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write model tests**

Create `tests/test_models.py`:

```python
from law_rag.models import (
    Clause,
    ContractAnalysisState,
    ContractReport,
    RiskFinding,
    YargiDecision,
)


def test_contract_report_schema() -> None:
    report = ContractReport(
        contract_summary="Hizmet sozlesmesi",
        risk_score=72,
        risk_level="high",
        clauses=[Clause(id="c1", title="Fesih", text="Tek tarafli fesih")],
        findings=[
            RiskFinding(
                id="f1",
                clause_id="c1",
                category="termination",
                severity="high",
                confidence=0.8,
                explanation="Tek tarafli fesih riski var.",
                recommendation="Fesih kosullarini dengeleyin.",
            )
        ],
        recommended_actions=["Fesih maddesini revize edin."],
        related_decisions=[
            YargiDecision(
                source="Yargitay",
                title="Yargitay karari",
                relevance="Fesih ve cezai sart iliskili.",
                confidence=0.7,
            )
        ],
        limitations=[],
    )

    payload = report.model_dump()

    assert payload["risk_level"] == "high"
    assert payload["findings"][0]["category"] == "termination"


def test_contract_analysis_state_defaults() -> None:
    state = ContractAnalysisState(file_name="sample.docx", file_type="docx")

    assert state.raw_text == ""
    assert state.clauses == []
    assert state.limitations == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -q`

Expected: FAIL because `law_rag.models` does not exist.

- [ ] **Step 3: Implement models**

Create `src/law_rag/models.py`:

```python
from typing import Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["low", "medium", "high", "critical"]
Severity = Literal["low", "medium", "high", "critical"]


class Clause(BaseModel):
    id: str
    title: str | None = None
    text: str


class RiskFinding(BaseModel):
    id: str
    clause_id: str | None = None
    category: str
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    recommendation: str


class YargiDecision(BaseModel):
    source: str
    title: str
    decision_date: str | None = None
    decision_number: str | None = None
    relevance: str
    excerpt: str | None = None
    url: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class ContractReport(BaseModel):
    contract_summary: str
    risk_score: int = Field(ge=0, le=100)
    risk_level: RiskLevel
    clauses: list[Clause]
    findings: list[RiskFinding]
    recommended_actions: list[str]
    related_decisions: list[YargiDecision]
    limitations: list[str]


class ContractAnalysisState(BaseModel):
    file_name: str
    file_type: Literal["pdf", "docx"]
    contract_type: str | None = None
    raw_text: str = ""
    clauses: list[Clause] = Field(default_factory=list)
    findings: list[RiskFinding] = Field(default_factory=list)
    legal_queries: list[str] = Field(default_factory=list)
    related_decisions: list[YargiDecision] = Field(default_factory=list)
    contract_summary: str = ""
    risk_score: int = 0
    risk_level: RiskLevel = "low"
    recommended_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Verify model tests pass**

Run: `uv run pytest tests/test_models.py -q`

Expected: PASS.

---

### Task 4: Document Loader

**Files:**
- Create: `src/law_rag/document_loader.py`
- Create: `tests/test_document_loader.py`

- [ ] **Step 1: Write loader tests**

Create `tests/test_document_loader.py`:

```python
from io import BytesIO

import pytest
from docx import Document

from law_rag.document_loader import (
    DocumentLoadError,
    detect_file_type,
    extract_docx_text,
    load_contract_text,
)


def make_docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_detect_file_type_accepts_pdf_and_docx() -> None:
    assert detect_file_type("contract.pdf") == "pdf"
    assert detect_file_type("contract.docx") == "docx"


def test_detect_file_type_rejects_unknown_extension() -> None:
    with pytest.raises(DocumentLoadError, match="unsupported_file_type"):
        detect_file_type("contract.txt")


def test_extract_docx_text() -> None:
    data = make_docx_bytes("Madde 1 - Fesih kosullari")

    assert extract_docx_text(data) == "Madde 1 - Fesih kosullari"


def test_load_contract_text_rejects_empty_docx() -> None:
    data = make_docx_bytes("")

    with pytest.raises(DocumentLoadError, match="empty_text"):
        load_contract_text("empty.docx", data)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_document_loader.py -q`

Expected: FAIL because `law_rag.document_loader` does not exist.

- [ ] **Step 3: Implement loader**

Create `src/law_rag/document_loader.py`:

```python
from io import BytesIO
from pathlib import Path
from typing import Literal

from docx import Document
from pypdf import PdfReader


class DocumentLoadError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def detect_file_type(file_name: str) -> Literal["pdf", "docx"]:
    suffix = Path(file_name).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".docx":
        return "docx"
    raise DocumentLoadError("unsupported_file_type", "Only PDF and DOCX files are supported.")


def normalize_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def extract_docx_text(data: bytes) -> str:
    try:
        document = Document(BytesIO(data))
    except Exception as exc:
        raise DocumentLoadError("unreadable_file", "DOCX file could not be read.") from exc

    return normalize_text("\n".join(paragraph.text for paragraph in document.paragraphs))


def extract_pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(data))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise DocumentLoadError("unreadable_file", "PDF file could not be read.") from exc

    return normalize_text(text)


def load_contract_text(file_name: str, data: bytes) -> tuple[Literal["pdf", "docx"], str]:
    file_type = detect_file_type(file_name)
    text = extract_pdf_text(data) if file_type == "pdf" else extract_docx_text(data)

    if not text:
        raise DocumentLoadError("empty_text", "No readable text was extracted from the file.")

    return file_type, text
```

- [ ] **Step 4: Verify loader tests pass**

Run: `uv run pytest tests/test_document_loader.py -q`

Expected: PASS.

---

### Task 5: Risk Scoring

**Files:**
- Create: `src/law_rag/risk.py`
- Create: `tests/test_risk.py`

- [ ] **Step 1: Write risk tests**

Create `tests/test_risk.py`:

```python
from law_rag.models import RiskFinding
from law_rag.risk import calculate_risk_score, risk_level_for_score


def finding(severity: str, confidence: float) -> RiskFinding:
    return RiskFinding(
        id=f"{severity}-{confidence}",
        category="termination",
        severity=severity,
        confidence=confidence,
        explanation="Risk",
        recommendation="Fix",
    )


def test_risk_level_boundaries() -> None:
    assert risk_level_for_score(0) == "low"
    assert risk_level_for_score(24) == "low"
    assert risk_level_for_score(25) == "medium"
    assert risk_level_for_score(50) == "high"
    assert risk_level_for_score(75) == "critical"
    assert risk_level_for_score(100) == "critical"


def test_calculate_risk_score_uses_severity_and_confidence() -> None:
    score = calculate_risk_score(
        [
            finding("critical", 1.0),
            finding("high", 0.5),
            finding("low", 0.2),
        ]
    )

    assert score == 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_risk.py -q`

Expected: FAIL because `law_rag.risk` does not exist.

- [ ] **Step 3: Implement scoring**

Create `src/law_rag/risk.py`:

```python
from law_rag.models import RiskFinding, RiskLevel


SEVERITY_WEIGHTS = {
    "low": 15,
    "medium": 35,
    "high": 65,
    "critical": 100,
}


def risk_level_for_score(score: int) -> RiskLevel:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def calculate_risk_score(findings: list[RiskFinding]) -> int:
    if not findings:
        return 0

    weighted = [
        SEVERITY_WEIGHTS[finding.severity] * finding.confidence
        for finding in findings
    ]
    return min(100, round(sum(weighted) / len(weighted)))
```

- [ ] **Step 4: Verify risk tests pass**

Run: `uv run pytest tests/test_risk.py -q`

Expected: PASS.

---

### Task 6: LLM Service Interface And Fake Analyzer

**Files:**
- Create: `src/law_rag/llm.py`
- Create: `tests/test_llm.py`

- [ ] **Step 1: Write fake LLM tests**

Create `tests/test_llm.py`:

```python
import pytest

from law_rag.llm import FakeContractAnalyzer


@pytest.mark.asyncio
async def test_fake_analyzer_segments_and_finds_risks() -> None:
    analyzer = FakeContractAnalyzer()

    clauses = await analyzer.segment_clauses("Madde 1 - Fesih\nTaraf tek tarafli feshedebilir.")
    findings = await analyzer.classify_risks(clauses)
    summary = await analyzer.summarize_contract("Hizmet sozlesmesi metni")

    assert clauses[0].id == "c1"
    assert findings[0].category == "termination"
    assert summary == "Uploaded contract requires legal review before signature."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm.py -q`

Expected: FAIL because `law_rag.llm` does not exist.

- [ ] **Step 3: Implement analyzer protocol and fake implementation**

Create `src/law_rag/llm.py`:

```python
from typing import Protocol

from google import genai

from law_rag.config import Settings
from law_rag.models import Clause, RiskFinding


class ContractAnalyzer(Protocol):
    async def summarize_contract(self, text: str) -> str: ...

    async def segment_clauses(self, text: str) -> list[Clause]: ...

    async def classify_risks(self, clauses: list[Clause]) -> list[RiskFinding]: ...

    async def build_legal_queries(self, findings: list[RiskFinding]) -> list[str]: ...


class FakeContractAnalyzer:
    async def summarize_contract(self, text: str) -> str:
        return "Uploaded contract requires legal review before signature."

    async def segment_clauses(self, text: str) -> list[Clause]:
        chunks = [chunk.strip() for chunk in text.split("\n") if chunk.strip()]
        if not chunks:
            chunks = [text.strip()]
        return [
            Clause(id=f"c{index}", title=None, text=chunk)
            for index, chunk in enumerate(chunks, start=1)
        ]

    async def classify_risks(self, clauses: list[Clause]) -> list[RiskFinding]:
        findings: list[RiskFinding] = []
        for clause in clauses:
            lowered = clause.text.lower()
            if "fesih" in lowered or "terminate" in lowered:
                findings.append(
                    RiskFinding(
                        id=f"f{len(findings) + 1}",
                        clause_id=clause.id,
                        category="termination",
                        severity="high",
                        confidence=0.85,
                        explanation="Clause may allow broad or unilateral termination.",
                        recommendation="Clarify termination triggers, notice periods, and cure rights.",
                    )
                )
            if "cezai sart" in lowered or "penalty" in lowered:
                findings.append(
                    RiskFinding(
                        id=f"f{len(findings) + 1}",
                        clause_id=clause.id,
                        category="penalty_clause",
                        severity="medium",
                        confidence=0.75,
                        explanation="Penalty clause may require proportionality review.",
                        recommendation="Check amount, cap, and enforceability under Turkish law.",
                    )
                )
        return findings

    async def build_legal_queries(self, findings: list[RiskFinding]) -> list[str]:
        queries = []
        for finding in findings[:5]:
            if finding.category == "termination":
                queries.append("hizmet sozlesmesi tek tarafli fesih cezai sart Yargitay")
            elif finding.category == "penalty_clause":
                queries.append("cezai sart fahislik tacir sozlesme Yargitay")
        return queries


class GeminiContractAnalyzer:
    def __init__(self, settings: Settings) -> None:
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required for GeminiContractAnalyzer.")
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model

    async def summarize_contract(self, text: str) -> str:
        response = self._client.models.generate_content(
            model=self._model,
            contents=f"Summarize this Turkish contract for legal review in English:\n\n{text[:12000]}",
        )
        return response.text or "Contract summary unavailable."

    async def segment_clauses(self, text: str) -> list[Clause]:
        return await FakeContractAnalyzer().segment_clauses(text)

    async def classify_risks(self, clauses: list[Clause]) -> list[RiskFinding]:
        return await FakeContractAnalyzer().classify_risks(clauses)

    async def build_legal_queries(self, findings: list[RiskFinding]) -> list[str]:
        return await FakeContractAnalyzer().build_legal_queries(findings)
```

- [ ] **Step 4: Verify fake LLM tests pass**

Run: `uv run pytest tests/test_llm.py -q`

Expected: PASS.

---

### Task 7: Yargi Client Interface

**Files:**
- Create: `src/law_rag/yargi_client.py`
- Create: `tests/test_yargi_client.py`

- [ ] **Step 1: Write Yargi fake client tests**

Create `tests/test_yargi_client.py`:

```python
import pytest

from law_rag.yargi_client import FakeYargiClient


@pytest.mark.asyncio
async def test_fake_yargi_client_returns_decisions() -> None:
    client = FakeYargiClient()

    decisions = await client.search(["hizmet sozlesmesi tek tarafli fesih"])

    assert decisions[0].source == "Yargi MCP"
    assert "hizmet sozlesmesi" in decisions[0].relevance
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yargi_client.py -q`

Expected: FAIL because `law_rag.yargi_client` does not exist.

- [ ] **Step 3: Implement Yargi clients**

Create `src/law_rag/yargi_client.py`:

```python
from typing import Protocol

import httpx

from law_rag.config import Settings
from law_rag.models import YargiDecision


class YargiClient(Protocol):
    async def search(self, queries: list[str]) -> list[YargiDecision]: ...


class FakeYargiClient:
    async def search(self, queries: list[str]) -> list[YargiDecision]:
        return [
            YargiDecision(
                source="Yargi MCP",
                title="Mock Turkish legal decision",
                relevance=f"Mock decision related to query: {query}",
                excerpt="Mock excerpt for development and tests.",
                confidence=0.6,
            )
            for query in queries
        ]


class RemoteYargiMcpClient:
    def __init__(self, settings: Settings) -> None:
        self._url = str(settings.yargi_mcp_url)

    async def search(self, queries: list[str]) -> list[YargiDecision]:
        decisions: list[YargiDecision] = []
        async with httpx.AsyncClient(timeout=30) as client:
            for query in queries:
                response = await client.post(
                    self._url,
                    json={
                        "jsonrpc": "2.0",
                        "id": query,
                        "method": "tools/call",
                        "params": {
                            "name": "search",
                            "arguments": {"query": query},
                        },
                    },
                )
                response.raise_for_status()
                decisions.append(
                    YargiDecision(
                        source="Yargi MCP",
                        title="Yargi MCP search result",
                        relevance=f"Retrieved through remote MCP for query: {query}",
                        excerpt=response.text[:1000],
                        confidence=0.5,
                    )
                )
        return decisions
```

- [ ] **Step 4: Verify Yargi tests pass**

Run: `uv run pytest tests/test_yargi_client.py -q`

Expected: PASS.

---

### Task 8: LangGraph Workflow

**Files:**
- Create: `src/law_rag/graph.py`
- Create: `tests/test_graph.py`

- [ ] **Step 1: Write graph tests**

Create `tests/test_graph.py`:

```python
import pytest

from law_rag.graph import analyze_contract
from law_rag.llm import FakeContractAnalyzer
from law_rag.models import ContractAnalysisState
from law_rag.yargi_client import FakeYargiClient


@pytest.mark.asyncio
async def test_analyze_contract_graph_returns_report() -> None:
    state = ContractAnalysisState(
        file_name="contract.docx",
        file_type="docx",
        raw_text="Madde 1 - Fesih\nTaraf tek tarafli feshedebilir.",
    )

    report = await analyze_contract(
        state=state,
        analyzer=FakeContractAnalyzer(),
        yargi_client=FakeYargiClient(),
    )

    assert report.risk_score > 0
    assert report.risk_level in {"medium", "high", "critical"}
    assert report.findings[0].category == "termination"
    assert report.related_decisions
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_graph.py -q`

Expected: FAIL because `law_rag.graph` does not exist.

- [ ] **Step 3: Implement graph**

Create `src/law_rag/graph.py`:

```python
from langgraph.graph import END, StateGraph

from law_rag.llm import ContractAnalyzer
from law_rag.models import ContractAnalysisState, ContractReport
from law_rag.risk import calculate_risk_score, risk_level_for_score
from law_rag.yargi_client import YargiClient


def build_contract_graph(analyzer: ContractAnalyzer, yargi_client: YargiClient):
    async def segment_clauses(state: ContractAnalysisState) -> ContractAnalysisState:
        state.clauses = await analyzer.segment_clauses(state.raw_text)
        return state

    async def classify_risks(state: ContractAnalysisState) -> ContractAnalysisState:
        state.findings = await analyzer.classify_risks(state.clauses)
        return state

    async def score_contract(state: ContractAnalysisState) -> ContractAnalysisState:
        state.risk_score = calculate_risk_score(state.findings)
        state.risk_level = risk_level_for_score(state.risk_score)
        return state

    async def build_legal_queries(state: ContractAnalysisState) -> ContractAnalysisState:
        state.legal_queries = await analyzer.build_legal_queries(state.findings)
        return state

    async def retrieve_yargi_decisions(state: ContractAnalysisState) -> ContractAnalysisState:
        try:
            state.related_decisions = await yargi_client.search(state.legal_queries)
        except Exception:
            state.related_decisions = []
            state.limitations.append("Yargi MCP retrieval failed.")
        return state

    async def compose_report(state: ContractAnalysisState) -> ContractAnalysisState:
        state.contract_summary = await analyzer.summarize_contract(state.raw_text)
        state.recommended_actions = [
            finding.recommendation for finding in state.findings
        ]
        if not state.findings:
            state.limitations.append("No major risk findings were detected by the MVP analyzer.")
        return state

    graph = StateGraph(ContractAnalysisState)
    graph.add_node("segment_clauses", segment_clauses)
    graph.add_node("classify_risks", classify_risks)
    graph.add_node("score_contract", score_contract)
    graph.add_node("build_legal_queries", build_legal_queries)
    graph.add_node("retrieve_yargi_decisions", retrieve_yargi_decisions)
    graph.add_node("compose_report", compose_report)

    graph.set_entry_point("segment_clauses")
    graph.add_edge("segment_clauses", "classify_risks")
    graph.add_edge("classify_risks", "score_contract")
    graph.add_edge("score_contract", "build_legal_queries")
    graph.add_edge("build_legal_queries", "retrieve_yargi_decisions")
    graph.add_edge("retrieve_yargi_decisions", "compose_report")
    graph.add_edge("compose_report", END)

    return graph.compile()


async def analyze_contract(
    state: ContractAnalysisState,
    analyzer: ContractAnalyzer,
    yargi_client: YargiClient,
) -> ContractReport:
    graph = build_contract_graph(analyzer, yargi_client)
    result = await graph.ainvoke(state)
    final_state = ContractAnalysisState.model_validate(result)

    return ContractReport(
        contract_summary=final_state.contract_summary,
        risk_score=final_state.risk_score,
        risk_level=final_state.risk_level,
        clauses=final_state.clauses,
        findings=final_state.findings,
        recommended_actions=final_state.recommended_actions,
        related_decisions=final_state.related_decisions,
        limitations=final_state.limitations,
    )
```

- [ ] **Step 4: Verify graph tests pass**

Run: `uv run pytest tests/test_graph.py -q`

Expected: PASS.

---

### Task 9: FastAPI Endpoint

**Files:**
- Create: `src/law_rag/api.py`
- Modify: `main.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Write API tests**

Create `tests/test_api.py`:

```python
from io import BytesIO

import pytest
from docx import Document
from httpx import ASGITransport, AsyncClient

from law_rag.api import create_app


def make_docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_analyze_contract_endpoint_accepts_docx() -> None:
    app = create_app(use_fake_clients=True)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/contracts/analyze",
            files={
                "file": (
                    "contract.docx",
                    make_docx_bytes("Madde 1 - Fesih\nTaraf tek tarafli feshedebilir."),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["risk_score"] > 0
    assert payload["related_decisions"]


@pytest.mark.asyncio
async def test_analyze_contract_endpoint_rejects_txt() -> None:
    app = create_app(use_fake_clients=True)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/contracts/analyze",
            files={"file": ("contract.txt", b"text", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "unsupported_file_type"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py -q`

Expected: FAIL because `law_rag.api` does not exist.

- [ ] **Step 3: Implement API**

Create `src/law_rag/api.py`:

```python
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from law_rag.config import Settings
from law_rag.document_loader import DocumentLoadError, load_contract_text
from law_rag.graph import analyze_contract
from law_rag.llm import FakeContractAnalyzer, GeminiContractAnalyzer
from law_rag.models import ContractAnalysisState, ContractReport
from law_rag.yargi_client import FakeYargiClient, RemoteYargiMcpClient


def create_app(use_fake_clients: bool = False) -> FastAPI:
    settings = Settings()
    app = FastAPI(title="Law RAG Contract CRAG API", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/contracts/analyze", response_model=ContractReport)
    async def analyze_contract_endpoint(
        file: UploadFile = File(...),
        contract_type: str | None = Form(default=None),
    ) -> ContractReport:
        data = await file.read()
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail={"code": "file_size_limit_exceeded", "message": "File is too large."},
            )

        try:
            file_type, text = load_contract_text(file.filename or "upload", data)
        except DocumentLoadError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

        analyzer = (
            FakeContractAnalyzer()
            if use_fake_clients or not settings.gemini_api_key
            else GeminiContractAnalyzer(settings)
        )
        yargi_client = FakeYargiClient() if use_fake_clients else RemoteYargiMcpClient(settings)

        state = ContractAnalysisState(
            file_name=file.filename or "upload",
            file_type=file_type,
            contract_type=contract_type,
            raw_text=text,
        )
        return await analyze_contract(state, analyzer, yargi_client)

    return app


app = create_app()
```

Replace `main.py`:

```python
import uvicorn


def main() -> None:
    uvicorn.run("law_rag.api:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Verify API tests pass**

Run: `uv run pytest tests/test_api.py -q`

Expected: PASS.

---

### Task 10: README And Full Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**

Set `README.md` to:

```markdown
# Law RAG

Contract CRAG backend for Turkish legal review workflows.

## MVP

The API accepts one PDF or DOCX contract, extracts text, runs a LangGraph analysis workflow, assigns a risk score, retrieves related Turkish legal decisions through Yargi MCP, and returns a JSON report.

## Run

```bash
uv sync --dev
uv run python main.py
```

## Environment

```bash
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=gemma-3-27b-it
YARGI_MCP_URL=https://yargimcp.surucu.dev/mcp
```

If `GEMINI_API_KEY` is absent, the app uses the deterministic MVP fake analyzer for local development.

## Analyze Contract

```bash
curl -X POST http://localhost:8000/api/v1/contracts/analyze \
  -F "file=@contract.docx" \
  -F "contract_type=service"
```

## Test

```bash
uv run pytest -q
```
```

- [ ] **Step 2: Run all tests**

Run: `uv run pytest -q`

Expected: all tests PASS.

- [ ] **Step 3: Run local API smoke test**

Run: `uv run python main.py`

Expected: server starts at `http://0.0.0.0:8000`.

In another terminal or API client, call `GET /health`.

Expected response:

```json
{"status":"ok"}
```

---

## Self-Review Notes

- Spec coverage: upload API, parser, LangGraph nodes, risk scoring, Yargi retrieval, config-driven Gemini model, and tests are each mapped to tasks.
- No persistent vector database is introduced.
- No GitHub or git operations are included.
- Live Yargi MCP tool names may need adjustment after integration testing against the remote MCP server; the MVP includes a fake client and a narrow HTTP placeholder so core behavior remains testable.

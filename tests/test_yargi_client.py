from typing import Any

import httpx
import pytest

from law_rag.yargi_client import RemoteYargiMcpClient


class RecordingYargiClient(RemoteYargiMcpClient):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def _ensure_initialized(self, client: httpx.AsyncClient) -> None:
        self._tools = {
            "search_bedesten_unified",
            "get_bedesten_document_markdown",
            "search_emsal_detailed_decisions",
            "get_emsal_document_markdown",
            "search_kvkk_decisions",
            "get_kvkk_document_markdown",
        }
        self._initialized = True

    async def _call_tool(
        self,
        client: httpx.AsyncClient,
        name: str,
        arguments: dict[str, Any],
    ) -> Any:
        self.calls.append((name, arguments))
        if name == "search_kvkk_decisions":
            return {
                "decisions": [
                    {
                        "title": "KVKK karari",
                        "description": "Kişisel veri ve veri işleyen sorumluluğu değerlendirilmiştir.",
                        "url": "https://www.kvkk.gov.tr/Icerik/1",
                    }
                ]
            }
        if name == "search_bedesten_unified":
            if arguments["court_types"] == ["YARGITAYKARARI", "DANISTAYKARAR"]:
                return {"decisions": []}
            return {
                "decisions": [
                    {
                        "documentId": "doc-1",
                        "title": "Istinaf karari",
                        "summary": "Fallback sonucu",
                    }
                ]
            }
        if name == "get_bedesten_document_markdown":
            return {"markdown_content": "Bedesten karar metni"}
        if name == "get_kvkk_document_markdown":
            return {"markdown_content": "KVKK karar metni"}
        return {"decisions": []}


@pytest.mark.asyncio
async def test_data_protection_search_uses_kvkk_before_bedesten() -> None:
    client = RecordingYargiClient()

    decisions = await client.search('"veri isleyen" KVKK', category="data_protection")

    assert decisions[0].source == "Yargi MCP / KVKK"
    assert decisions[0].excerpt == "Kişisel veri ve veri işleyen sorumluluğu değerlendirilmiştir."
    assert client.calls[0][0] == "search_kvkk_decisions"
    assert client.calls[0][1] == {"keywords": '"veri isleyen" KVKK', "page": 1}
    assert all(call[0] != "search_bedesten_unified" for call in client.calls)


@pytest.mark.asyncio
async def test_bedesten_search_tries_high_courts_before_broad_sources() -> None:
    client = RecordingYargiClient()

    decisions = await client.search('"derhal fesih" "hakli neden"', category="termination")

    bedesten_calls = [
        arguments
        for name, arguments in client.calls
        if name == "search_bedesten_unified"
    ]
    assert bedesten_calls[0]["court_types"] == ["YARGITAYKARARI", "DANISTAYKARAR"]
    assert bedesten_calls[1]["court_types"] == [
        "YARGITAYKARARI",
        "DANISTAYKARAR",
        "ISTINAFHUKUK",
        "YERELHUKUK",
    ]
    assert decisions[0].title == "Istinaf karari"


@pytest.mark.asyncio
async def test_fetch_decision_text_uses_decision_source() -> None:
    client = RecordingYargiClient()
    bedesten_decision = (
        await client.search('"derhal fesih" "hakli neden"', category="termination")
    )[0]
    kvkk_decision = (
        await client.search('"veri isleyen" KVKK', category="data_protection")
    )[0]

    assert await client.fetch_decision_text(bedesten_decision) == "Bedesten karar metni"
    assert await client.fetch_decision_text(kvkk_decision) == "KVKK karar metni"

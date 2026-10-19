import asyncio
from typing import Any

import httpx
import pytest

from law_rag.models import YargiDecision
from law_rag.yargi_client import RemoteYargiMcpClient, YargiRateLimitError, _bedesten_phrases


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


class HandshakeCountingClient(RemoteYargiMcpClient):
    def __init__(self) -> None:
        super().__init__()
        self.initialize_calls = 0

    async def _rpc(self, client: httpx.AsyncClient, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            self.initialize_calls += 1
        await asyncio.sleep(0.01)
        return {"tools": [{"name": "search_bedesten_unified"}]}

    async def _notify(self, client: httpx.AsyncClient, method: str, params: dict[str, Any]) -> None:
        return None

    async def _call_tool(self, client: httpx.AsyncClient, name: str, arguments: dict[str, Any]) -> Any:
        return {"decisions": []}


@pytest.mark.asyncio
async def test_parallel_searches_share_one_mcp_handshake() -> None:
    client = HandshakeCountingClient()

    await asyncio.gather(*(client.search(f"sorgu {index}") for index in range(3)))

    assert client.initialize_calls == 1


class RawPayloadClient(RemoteYargiMcpClient):
    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__()
        self.payload = payload
        self._tools = {"search_bedesten_unified", "get_kvkk_document_markdown"}
        self._initialized = True

    async def _rpc(self, client: httpx.AsyncClient, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"structuredContent": self.payload}


@pytest.mark.asyncio
async def test_rate_limit_payload_raises_instead_of_looking_empty() -> None:
    client = RawPayloadClient({"decisions": [], "error": "rate_limit_exceeded", "retry_after": "0"})

    with pytest.raises(YargiRateLimitError):
        await client.search('"cezai şart"', category="penalty_clause")


class RateLimitedOnceClient(RawPayloadClient):
    def __init__(self) -> None:
        super().__init__({})
        self.calls = 0

    async def _rpc(self, client: httpx.AsyncClient, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            text = "ERROR (rate_limit_exceeded, HTTP 429): bekleyin Retry-After: 0.01"
            return {"structuredContent": {"documentId": "1", "markdown_content": text}}
        return {"structuredContent": {"documentId": "1", "markdown_content": "Karar metni"}}


@pytest.mark.asyncio
async def test_rate_limited_document_is_retried_after_wait() -> None:
    client = RateLimitedOnceClient()
    decision = YargiDecision(source="Yargi MCP / Bedesten", title="karar", relevance="q", url="https://mevzuat.adalet.gov.tr/ictihat/1")

    assert await client.fetch_decision_text(decision) == "Karar metni"
    assert client.calls == 2


@pytest.mark.asyncio
async def test_kvkk_document_text_is_read_from_markdown_chunk() -> None:
    client = RawPayloadClient({"markdown_chunk": "KVKK karar metni", "current_page": 1})
    decision = YargiDecision(source="Yargi MCP / KVKK", title="KVKK", relevance="q", url="https://www.kvkk.gov.tr/Icerik/1")

    assert await client.fetch_decision_text(decision) == "KVKK karar metni"


def test_bedesten_phrases_make_terms_required_and_fall_back_to_first_phrase() -> None:
    assert _bedesten_phrases('"cezai şart" "Türk Borçlar Kanunu" indirim') == [
        '+"cezai şart" +"Türk Borçlar Kanunu" +indirim',
        '"cezai şart"',
    ]
    assert _bedesten_phrases('+kira -tahliye OR "kira artışı"') == ['+kira -tahliye OR +"kira artışı"', '"kira artışı"']
    assert _bedesten_phrases("tahliye") == ["+tahliye"]


def test_bedesten_phrases_drop_unbalanced_quotes() -> None:
    assert _bedesten_phrases('konut dokunulmazlığı" "özel hayat') == ["+konut +dokunulmazlığı +özel +hayat"]


@pytest.mark.asyncio
async def test_rate_limited_document_fetch_is_not_silently_empty() -> None:
    client = RawPayloadClient({"documentId": "1", "markdown_content": "ERROR (rate_limit_exceeded, HTTP 429): Retry-After: 0"})
    decision = YargiDecision(source="Yargi MCP / Bedesten", title="karar", relevance="q", url="https://mevzuat.adalet.gov.tr/ictihat/1")

    with pytest.raises(YargiRateLimitError):
        await client.fetch_decision_text(decision)


@pytest.mark.asyncio
async def test_decisions_name_the_issuing_court() -> None:
    client = RawPayloadClient(
        {"decisions": [{"documentId": "1", "itemType": {"name": "DANISTAYKARAR"}, "birimAdi": "8. Daire"}]}
    )

    decisions = await client.search('"imar"', category="termination")

    assert decisions[0].court == "Danıştay"

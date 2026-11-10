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


@pytest.mark.asyncio
async def test_remote_yargi_client_reuses_http_client_and_closes(monkeypatch) -> None:
    created: list[Any] = []

    class DummyResponse:
        def __init__(self, data: dict[str, Any], headers: dict[str, str] | None = None) -> None:
            self._data = data
            self.headers = headers or {"content-type": "application/json"}
            self.text = ""
            self.status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self._data

    class FakeAsyncHttp:
        def __init__(self, **kwargs) -> None:
            self.closed = False
            created.append(self)

        async def post(self, url: str, headers=None, json=None):
            method = json.get("method")
            if method == "initialize":
                return DummyResponse({"result": {}}, {"mcp-session-id": "s1", "content-type": "application/json"})
            if method == "notifications/initialized":
                return DummyResponse({})
            if method == "tools/list":
                return DummyResponse({"result": {"tools": [{"name": "search_bedesten_unified"}]}})
            tool_name = json.get("params", {}).get("name")
            if tool_name == "search_bedesten_unified":
                return DummyResponse(
                    {
                        "result": {
                            "structuredContent": {
                                "decisions": [{"documentId": "doc-1", "title": "Karar 1"}]
                            }
                        }
                    }
                )
            return DummyResponse({"result": {"structuredContent": {"markdown_content": "Metin"}}})

        async def aclose(self) -> None:
            self.closed = True

    monkeypatch.setattr("law_rag.yargi_client.httpx.AsyncClient", FakeAsyncHttp)
    client = RemoteYargiMcpClient()

    first = await client.search("depozito", category="deposit_forfeiture")
    await client.fetch_decision_text(first[0])
    await client.aclose()

    assert len(created) == 1
    assert created[0].closed is True


@pytest.mark.asyncio
async def test_bedesten_normalizes_and_syntax_and_halts_on_rate_limit(monkeypatch) -> None:
    from law_rag.yargi_client import YargiMcpError

    client = RecordingYargiClient()
    await client.search('"kira sözleşmesi" "güvence bedeli" iade', category="deposit_forfeiture")
    first_phrase = client.calls[0][1]["phrase"]
    assert first_phrase == '"kira sözleşmesi" AND "güvence bedeli" AND iade'

    client.calls.clear()
    await client.search('depozito OR teminat', category="deposit_forfeiture")
    assert client.calls[0][1]["phrase"] == 'depozito OR teminat'

    class RateLimitedClient(RecordingYargiClient):
        async def _call_tool(self, http_client, name, arguments):
            self.calls.append((name, arguments))
            return {
                "decisions": [],
                "error": "rate_limit_exceeded",
                "status_code": 429,
                "retry_after": "28.5",
            }

    limited = RateLimitedClient()
    with pytest.raises(YargiMcpError):
        await limited.search('"kira sözleşmesi" AND depozito', category="deposit_forfeiture")
    assert len(limited.calls) == 1

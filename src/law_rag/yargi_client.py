import asyncio
import json
import re
from typing import Any, Protocol

import httpx

from .config import Settings, settings
from .models import YargiDecision


RATE_LIMIT_MAX_WAIT_SECONDS = 20.0
_QUERY_TERM = re.compile(r'"[^"]+"|\S+')


def _bedesten_phrases(query: str) -> list[str]:
    # Bedesten ORs bare terms, so every term is made required; the first quoted phrase alone is the fallback.
    quoted = re.findall(r'"([^"]*)"', query)
    if query.count('"') % 2 or any(not text.strip() or text != text.strip() for text in quoted):
        query = query.replace('"', "")
    terms = _QUERY_TERM.findall(query)
    required = " ".join(
        term if term[0] in "+-" or term.upper() in {"AND", "OR", "NOT"} else f"+{term}"
        for term in terms
    )
    first_phrase = [term for term in terms if term.startswith('"')][:1]
    return list(dict.fromkeys([required, *first_phrase]))


class YargiClient(Protocol):
    async def search(self, query: str, category: str | None = None) -> list[YargiDecision]:
        ...

    async def fetch_decision_text(self, decision: YargiDecision) -> str | None:
        ...


class YargiMcpError(RuntimeError):
    pass


class YargiRateLimitError(YargiMcpError):
    pass


class FakeYargiClient:
    async def search(self, query: str, category: str | None = None) -> list[YargiDecision]:
        return [
            YargiDecision(
                source="Yargi MCP",
                title="MVP yargi karari",
                relevance=f"'{query}' sorgusu ile iliskili ornek karar ozeti.",
                excerpt="Mock excerpt for local MVP development.",
                confidence=0.6,
            )
        ]

    async def fetch_decision_text(self, decision: YargiDecision) -> str | None:
        return decision.excerpt


class RemoteYargiMcpClient:
    def __init__(self, app_settings: Settings = settings) -> None:
        self._settings = app_settings
        self._url = self._normalize_url(app_settings.yargi_mcp_url)
        self._session_id: str | None = None
        self._initialized = False
        self._request_id = 0
        self._tools: set[str] = set()
        self._init_lock = asyncio.Lock()
        self._call_semaphore = asyncio.Semaphore(app_settings.yargi_max_concurrency)

    async def search(self, query: str, category: str | None = None) -> list[YargiDecision]:
        async with httpx.AsyncClient(
            timeout=self._settings.yargi_request_timeout_seconds,
            follow_redirects=True,
        ) as client:
            await self._ensure_initialized(client)

            if category == "data_protection" and "search_kvkk_decisions" in self._tools:
                kvkk_result = await self._call_tool(
                    client,
                    "search_kvkk_decisions",
                    {"keywords": query, "page": 1},
                )
                decisions = await self._decisions_from_kvkk_result(query, kvkk_result)
                if decisions:
                    return decisions

            for phrase in _bedesten_phrases(query):
                for court_types in (
                    ["YARGITAYKARARI", "DANISTAYKARAR"],
                    ["YARGITAYKARARI", "DANISTAYKARAR", "ISTINAFHUKUK", "YERELHUKUK"],
                ):
                    decisions = await self._search_bedesten(client, phrase, court_types)
                    if decisions:
                        return decisions

            if "search_emsal_detailed_decisions" in self._tools:
                try:
                    emsal_result = await self._call_tool(
                        client,
                        "search_emsal_detailed_decisions",
                        {"keyword": query, "page_number": 1},
                    )
                    return await self._decisions_from_emsal_result(client, query, emsal_result)
                except Exception:
                    return []

            return []

    async def fetch_decision_text(self, decision: YargiDecision) -> str | None:
        async with httpx.AsyncClient(
            timeout=self._settings.yargi_request_timeout_seconds,
            follow_redirects=True,
        ) as client:
            await self._ensure_initialized(client)
            if "KVKK" in decision.source and decision.url:
                return await self._fetch_kvkk_document(client, decision.url)
            if "Bedesten" in decision.source:
                document_id = self._document_id_from_decision(decision)
                if document_id:
                    return await self._fetch_bedesten_document(client, document_id)
            if "Emsal" in decision.source:
                document_id = self._document_id_from_decision(decision)
                if document_id:
                    return await self._fetch_emsal_document(client, document_id)
        return None

    async def _search_bedesten(
        self,
        client: httpx.AsyncClient,
        query: str,
        court_types: list[str],
    ) -> list[YargiDecision]:
        result = await self._call_tool(
            client,
            "search_bedesten_unified",
            {
                "phrase": query,
                "court_types": court_types,
                "pageNumber": 1,
                "birimAdi": "ALL",
            },
        )
        return await self._decisions_from_bedesten_result(client, query, result)

    async def _ensure_initialized(self, client: httpx.AsyncClient) -> None:
        if self._initialized:
            return
        # Parallel searches share this client; only the first one may run the MCP handshake.
        async with self._init_lock:
            if self._initialized:
                return
            await self._rpc(
                client,
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "law-rag", "version": "0.1.0"},
                },
            )
            await self._notify(client, "notifications/initialized", {})
            tools_result = await self._rpc(client, "tools/list", {})
            self._tools = {
                str(tool.get("name"))
                for tool in tools_result.get("tools", [])
                if isinstance(tool, dict) and tool.get("name")
            }
            if "search_bedesten_unified" not in self._tools:
                raise YargiMcpError("Yargi MCP tool search_bedesten_unified is not available.")
            self._initialized = True

    async def _call_tool(
        self,
        client: httpx.AsyncClient,
        name: str,
        arguments: dict[str, Any],
    ) -> Any:
        payload = await self._call_tool_once(client, name, arguments)
        retry_after = self._rate_limit_retry_after(payload)
        if retry_after is not None and retry_after <= RATE_LIMIT_MAX_WAIT_SECONDS:
            await asyncio.sleep(retry_after)
            payload = await self._call_tool_once(client, name, arguments)
            retry_after = self._rate_limit_retry_after(payload)
        if retry_after is not None:
            raise YargiRateLimitError(f"Yargi MCP rate limit from {name}: retry_after={retry_after}")
        return payload

    async def _call_tool_once(
        self,
        client: httpx.AsyncClient,
        name: str,
        arguments: dict[str, Any],
    ) -> Any:
        async with self._call_semaphore:
            result = await self._rpc(
                client,
                "tools/call",
                {"name": name, "arguments": arguments},
            )
        if result.get("isError"):
            raise YargiMcpError(f"Yargi MCP tool error from {name}: {result}")
        return self._extract_tool_payload(result)

    def _rate_limit_retry_after(self, payload: Any) -> float | None:
        # The server reports throttling as a normal payload: an error field on searches, an ERROR text on documents.
        if not isinstance(payload, dict):
            return None
        if payload.get("error") == "rate_limit_exceeded":
            raw = str(payload.get("retry_after") or "")
        elif str(payload.get("markdown_content") or "").startswith("ERROR (rate_limit_exceeded"):
            match = re.search(r"Retry-After:\s*([\d.]+)", payload["markdown_content"])
            raw = match.group(1) if match else ""
        else:
            return None
        try:
            return float(raw)
        except ValueError:
            return 1.0

    async def _rpc(
        self,
        client: httpx.AsyncClient,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        self._request_id += 1
        response = await client.post(
            self._url,
            headers=self._headers(),
            json={
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params,
            },
        )
        self._capture_session(response)
        response.raise_for_status()
        payload = self._decode_response(response)
        if "error" in payload:
            raise YargiMcpError(f"Yargi MCP {method} failed: {payload['error']}")
        result = payload.get("result")
        if not isinstance(result, dict):
            return {}
        return result

    async def _notify(
        self,
        client: httpx.AsyncClient,
        method: str,
        params: dict[str, Any],
    ) -> None:
        response = await client.post(
            self._url,
            headers=self._headers(),
            json={"jsonrpc": "2.0", "method": method, "params": params},
        )
        self._capture_session(response)
        if response.status_code >= 400:
            response.raise_for_status()

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-06-18",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _capture_session(self, response: httpx.Response) -> None:
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id

    def _decode_response(self, response: httpx.Response) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "")
        text = response.text.strip()
        if "text/event-stream" in content_type or text.startswith("event:"):
            for block in text.split("\n\n"):
                data_lines = [
                    line.removeprefix("data:").strip()
                    for line in block.splitlines()
                    if line.startswith("data:")
                ]
                if data_lines:
                    return json.loads("\n".join(data_lines))
            raise YargiMcpError("Yargi MCP returned SSE without JSON data.")
        return response.json()

    def _extract_tool_payload(self, result: dict[str, Any]) -> Any:
        structured = result.get("structuredContent")
        if structured is not None:
            return structured

        content = result.get("content", [])
        if isinstance(content, list):
            texts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            joined = "\n".join(text for text in texts if text).strip()
            if not joined:
                return {}
            try:
                return json.loads(joined)
            except json.JSONDecodeError:
                return {"text": joined}
        return result

    async def _decisions_from_bedesten_result(
        self,
        client: httpx.AsyncClient,
        query: str,
        payload: Any,
    ) -> list[YargiDecision]:
        if not isinstance(payload, dict):
            return []

        raw_decisions = payload.get("decisions") or []
        decisions: list[YargiDecision] = []
        for item in raw_decisions[: self._settings.yargi_max_results_per_finding]:
            if not isinstance(item, dict):
                continue
            document_id = self._first_value(item, "documentId", "document_id", "id")
            title = self._decision_title(item, fallback="Bedesten karari")
            excerpt = self._first_value(item, "ozet", "summary", "preview", "text")
            url = self._first_value(item, "source_url", "document_url", "url")
            if not url and document_id:
                url = f"https://mevzuat.adalet.gov.tr/ictihat/{document_id}"

            decisions.append(
                YargiDecision(
                    source="Yargi MCP / Bedesten",
                    title=title,
                    decision_date=self._decision_date(item),
                    decision_number=self._decision_number(item),
                    relevance=f"'{query}' sorgusu icin Bedesten uzerinden bulunan karar.",
                    excerpt=excerpt,
                    url=url,
                    confidence=0.72,
                )
            )
        return decisions

    async def _decisions_from_kvkk_result(
        self,
        query: str,
        payload: Any,
    ) -> list[YargiDecision]:
        if isinstance(payload, dict):
            raw_decisions = payload.get("decisions") or payload.get("results") or []
        elif isinstance(payload, list):
            raw_decisions = payload
        else:
            raw_decisions = []

        decisions: list[YargiDecision] = []
        for item in raw_decisions[: self._settings.yargi_max_results_per_finding]:
            if not isinstance(item, dict):
                continue
            url = self._first_value(item, "decision_url", "url", "source_url")
            decisions.append(
                YargiDecision(
                    source="Yargi MCP / KVKK",
                    title=self._decision_title(item, fallback="KVKK karari"),
                    decision_date=self._decision_date(item),
                    decision_number=self._decision_number(item),
                    relevance=f"'{query}' sorgusu icin KVKK uzerinden bulunan karar.",
                    excerpt=self._first_value(item, "description", "summary", "excerpt", "text", "content"),
                    url=url,
                    confidence=0.78,
                )
            )
        return decisions

    async def _fetch_bedesten_document(
        self,
        client: httpx.AsyncClient,
        document_id: str,
    ) -> str | None:
        try:
            payload = await self._call_tool(
                client,
                "get_bedesten_document_markdown",
                {"documentId": document_id},
            )
        except YargiRateLimitError:
            raise
        except Exception:
            return None
        if isinstance(payload, dict):
            text = self._first_value(payload, "markdown_content", "content", "text")
            return self._clean_document_text(text)
        if isinstance(payload, str):
            return self._clean_document_text(payload)
        return None

    async def _decisions_from_emsal_result(
        self,
        client: httpx.AsyncClient,
        query: str,
        payload: Any,
    ) -> list[YargiDecision]:
        if isinstance(payload, dict):
            raw_decisions = payload.get("decisions") or payload.get("results") or []
        elif isinstance(payload, list):
            raw_decisions = payload
        else:
            raw_decisions = []

        decisions: list[YargiDecision] = []
        for item in raw_decisions[: self._settings.yargi_max_results_per_finding]:
            if not isinstance(item, dict):
                continue
            url = self._first_value(item, "url", "document_url", "source_url")
            document_id = self._first_value(item, "id", "document_id")
            if not document_id and url and "id=" in url:
                document_id = url.rsplit("id=", 1)[-1]
            excerpt = self._first_value(item, "excerpt", "summary", "text", "content")
            decisions.append(
                YargiDecision(
                    source="Yargi MCP / Emsal",
                    title=self._decision_title(item, fallback="Emsal karari"),
                    decision_date=self._decision_date(item),
                    decision_number=self._decision_number(item),
                    relevance=f"'{query}' sorgusu icin Emsal uzerinden bulunan karar.",
                    excerpt=excerpt,
                    url=url,
                    confidence=0.65,
                )
            )
        return decisions

    async def _fetch_kvkk_document(
        self,
        client: httpx.AsyncClient,
        decision_url: str,
    ) -> str | None:
        if "get_kvkk_document_markdown" not in self._tools:
            return None
        try:
            payload = await self._call_tool(
                client,
                "get_kvkk_document_markdown",
                {"decision_url": decision_url, "page_number": 1},
            )
        except YargiRateLimitError:
            raise
        except Exception:
            return None
        if isinstance(payload, dict):
            text = self._first_value(payload, "markdown_chunk", "markdown_content", "content", "text")
            return self._clean_document_text(text)
        if isinstance(payload, str):
            return self._clean_document_text(payload)
        return None

    async def _fetch_emsal_document(
        self,
        client: httpx.AsyncClient,
        document_id: str,
    ) -> str | None:
        if "get_emsal_document_markdown" not in self._tools:
            return None
        try:
            payload = await self._call_tool(
                client,
                "get_emsal_document_markdown",
                {"id": document_id},
            )
        except YargiRateLimitError:
            raise
        except Exception:
            return None
        if isinstance(payload, dict):
            text = self._first_value(payload, "markdown_content", "content", "text")
            return self._clean_document_text(text)
        if isinstance(payload, str):
            return self._clean_document_text(payload)
        return None

    def _decision_title(self, item: dict[str, Any], fallback: str) -> str:
        direct_title = self._first_value(item, "title", "baslik", "daire", "birimAdi")
        parts = [direct_title] if direct_title else []
        decision_number = self._decision_number(item)
        decision_date = self._decision_date(item)
        if decision_number:
            parts.append(decision_number)
        if decision_date:
            parts.append(str(decision_date))
        return " - ".join(str(part) for part in parts if part) or fallback

    def _decision_number(self, item: dict[str, Any]) -> str | None:
        esas = self._first_value(item, "esasNo", "esas_no")
        karar = self._first_value(item, "kararNo", "karar_no")
        if esas and karar:
            return f"E. {esas}, K. {karar}"
        return self._first_value(item, "decision_number", "kararNo", "karar_no")

    def _decision_date(self, item: dict[str, Any]) -> str | None:
        raw_date = self._first_value(item, "kararTarihiStr", "kararTarihi", "decision_date", "publication_date")
        if not raw_date:
            return None
        match = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", raw_date)
        if not match:
            return raw_date
        day, month, year = (int(part) for part in match.groups())
        if not (1 <= day <= 31 and 1 <= month <= 12 and 1900 <= year <= 2100):
            return None
        return f"{day:02d}.{month:02d}.{year:04d}"

    def _first_value(self, item: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = item.get(key)
            if value is not None and str(value).strip():
                return str(value)
        return None

    def _normalize_url(self, url: str) -> str:
        stripped = url.strip()
        return stripped if stripped.endswith("/") else f"{stripped}/"

    def _document_id_from_decision(self, decision: YargiDecision) -> str | None:
        if decision.url:
            if "id=" in decision.url:
                return decision.url.rsplit("id=", 1)[-1]
            return decision.url.rstrip("/").rsplit("/", 1)[-1]
        return None

    def _clean_document_text(self, text: str | None) -> str | None:
        if not text:
            return None
        stripped = text.strip()
        if stripped.startswith("ERROR (") or "rate_limit_exceeded" in stripped:
            return None
        return stripped

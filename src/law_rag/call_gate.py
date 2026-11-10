"""Pacing for Gemini API calls (free-tier friendly).

One gate bounds the calls in flight and spaces call starts by a minimum
interval. The analyze endpoint creates one gate per request and shares it
between the OCR engine and the analyzer, so a scanned contract's page
transcriptions and the analysis calls are paced together. Chat sessions share
one process-wide gate.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any


class CallGate:
    """Bounds concurrent LLM calls and spaces call starts by a minimum interval."""

    def __init__(self, max_concurrency: int, min_interval_seconds: float) -> None:
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self._lock = asyncio.Lock()
        self._min_interval = max(0.0, min_interval_seconds)
        self._last_start = 0.0

    @classmethod
    def from_settings(cls, app_settings: Any) -> "CallGate":
        return cls(
            getattr(app_settings, "llm_max_concurrency", 1),
            getattr(app_settings, "llm_min_interval_seconds", 0.0),
        )

    async def run(self, call: Callable[[], Awaitable[Any]]) -> Any:
        async with self._semaphore:
            if self._min_interval:
                async with self._lock:
                    wait = self._last_start + self._min_interval - time.monotonic()
                    if wait > 0:
                        await asyncio.sleep(wait)
                    self._last_start = time.monotonic()
            return await call()


def create_genai_client(client_factory: Any, api_key: str, timeout_seconds: float = 45.0) -> Any:
    from google.genai import types

    options = types.HttpOptions(
        timeout=int(timeout_seconds * 1000),
        retry_options=types.HttpRetryOptions(attempts=1),
    )
    try:
        return client_factory(api_key=api_key, http_options=options)
    except TypeError:
        return client_factory(api_key=api_key)

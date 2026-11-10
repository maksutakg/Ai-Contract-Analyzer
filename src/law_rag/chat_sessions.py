"""In-memory chat sessions: nothing is written to disk.

A session holds the chunked report, its embeddings and the recent question /
answer history in process memory only. It expires CHAT_SESSION_TTL_SECONDS
after its last use (sliding TTL; each question extends it), can be deleted
explicitly, and disappears when the process restarts. At most
CHAT_MAX_SESSIONS sessions exist at once; expired sessions are purged before
the cap is checked.
"""

import asyncio
import secrets
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .chat_answer import Turn
from .chat_index import ChatIndex


class SessionNotFound(KeyError):
    pass


class SessionLimitReached(RuntimeError):
    pass


@dataclass
class ChatSession:
    id: str
    index: ChatIndex
    expires_at: float  # wall clock (time.time) seconds
    history: deque = field(default_factory=deque)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def expires_at_iso(self) -> str:
        return datetime.fromtimestamp(self.expires_at, tz=timezone.utc).isoformat(timespec="seconds")

    def recent_history(self) -> list[Turn]:
        return list(self.history)


class ChatSessionStore:
    def __init__(
        self,
        ttl_seconds: int,
        max_sessions: int,
        history_turns: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self._history_turns = history_turns
        self._clock = clock
        self._sessions: dict[str, ChatSession] = {}

    def __len__(self) -> int:
        self.purge_expired()
        return len(self._sessions)

    def purge_expired(self) -> None:
        now = self._clock()
        for session_id in [key for key, session in self._sessions.items() if session.expires_at <= now]:
            del self._sessions[session_id]

    def ensure_capacity(self) -> None:
        self.purge_expired()
        if len(self._sessions) >= self.max_sessions:
            raise SessionLimitReached

    def create(self, index: ChatIndex) -> ChatSession:
        self.ensure_capacity()
        session = ChatSession(
            id=secrets.token_urlsafe(18),
            index=index,
            expires_at=self._clock() + self.ttl_seconds,
            history=deque(maxlen=max(1, self._history_turns)),
        )
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> ChatSession:
        session = self._sessions.get(session_id)
        if session is None or session.expires_at <= self._clock():
            self._sessions.pop(session_id, None)
            raise SessionNotFound(session_id)
        return session

    def touch(self, session: ChatSession) -> None:
        session.expires_at = self._clock() + self.ttl_seconds

    def record(self, session: ChatSession, turn: Turn) -> None:
        if self._history_turns > 0:
            session.history.append(turn)

    def delete(self, session_id: str) -> bool:
        self.purge_expired()
        return self._sessions.pop(session_id, None) is not None

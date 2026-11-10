"""Request and response models of the contract chat endpoints."""

from typing import Literal

from pydantic import BaseModel, Field

AnsweredBy = Literal["llm", "extractive", "not_covered"]


class ChatQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class ChatCitation(BaseModel):
    id: str
    type: str
    clause_id: str | None = None
    title: str | None = None
    snippet: str


class ChatSessionCreated(BaseModel):
    session_id: str
    expires_at: str  # ISO 8601, UTC; extended by each question (sliding TTL)
    ttl_seconds: int
    chunk_count: int
    chunk_types: dict[str, int]
    retrieval_mode: Literal["hybrid", "lexical"]
    embedding_model: str | None = None
    notes: list[str] = Field(default_factory=list)
    disclaimer: str


class ChatAnswer(BaseModel):
    session_id: str
    question: str
    answer: str
    covered: bool
    answered_by: AnsweredBy
    citations: list[ChatCitation] = Field(default_factory=list)
    retrieval_mode: Literal["hybrid", "dense", "lexical"]
    notes: list[str] = Field(default_factory=list)
    disclaimer: str
    expires_at: str

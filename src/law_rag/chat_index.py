"""Per-contract knowledge base and hybrid retrieval for the contract chat.

Knowledge base (built from one ContractReport, kept in memory only):
  clause           clause text (long clauses split on sentence boundaries)
  finding          risk finding, recommendation and curated statute references
  statutory_check  result of a statutory limit check and its legal basis
  missing_clause   a checklist topic the contract lacks, with the suggestion
  rewrite          a suggested replacement for a clause
  decision         a related court decision from the CRAG step

Every chunk has a stable id derived from the report ("clause-3",
"clause-3-part2", "finding-1", "check-lease_deposit_cap", "missing-deposit",
"rewrite-clause-3", "decision-1") and, where it has one, the clause id it
belongs to, so answers can cite it and a frontend can link to it.

Retrieval (`retrieve` / `rank_chunks`), mode "hybrid", "dense" or "lexical":
* lexical: BM25 (k1=1.2, b=0.75) over diacritic-free tokens (text_utils.searchable)
  truncated to their first 5 characters, a simple and well-studied stemmer
  for agglutinative Turkish ("depozitomu" and "depozitonun" both -> "depoz").
  A chunk is a lexical match when its BM25 score is at least LEXICAL_MIN_SCORE
  and the query terms it contains carry at least LEXICAL_MIN_COVERAGE of the
  question's IDF mass (see lexical_scores), so one incidental common word
  ("yeri", "zorunda") does not make an unrelated question look covered.
* dense: cosine similarity of embeddings; a chunk is a dense match when the
  similarity is at least the embedder's threshold (CHAT_MIN_DENSE_SIMILARITY).
* hybrid: reciprocal rank fusion of the two match lists,
  score(d) = sum over lists of 1 / (RRF_K + rank(d)), RRF_K = 60.
With `apply_threshold=False` every chunk with a positive score is ranked (for
evaluation). An empty result means the question is not covered.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from .categories import category_label
from .embeddings import Embedder, Vector, cosine
from .models import ContractReport, LegalReference
from .text_utils import word_tokens

ChunkType = Literal["clause", "finding", "statutory_check", "missing_clause", "rewrite", "decision"]
RetrievalMode = Literal["hybrid", "dense", "lexical"]

RRF_K = 60
LEXICAL_MIN_SCORE = 1.0
# Heuristic gates, set by probing a handful of questions offline; to be tuned
# with the evaluation harness (retrieve(..., apply_threshold=False) exposes the raw scores).
LEXICAL_MIN_COVERAGE = 0.35
STEM_CHARS = 5
BM25_K1 = 1.2
BM25_B = 0.75

_STATUS_TR = {
    "violation": "ihlal",
    "ok": "uygun",
    "needs_review": "manuel kontrol gerekli",
    "not_applicable": "tespit edilemedi",
}
_SEVERITY_TR = {"low": "düşük", "medium": "orta", "high": "yüksek", "critical": "kritik"}
_IMPORTANCE_TR = {"low": "düşük", "medium": "orta", "high": "yüksek"}


@dataclass
class Chunk:
    id: str
    type: ChunkType
    text: str
    clause_id: str | None = None
    title: str | None = None


@dataclass
class ChatIndex:
    chunks: list[Chunk]
    vectors: list[Vector] | None = None  # None: dense retrieval unavailable
    embedder_name: str | None = None
    dense_error: str | None = None
    _tokens: list[Counter] = field(default_factory=list)
    _df: Counter = field(default_factory=Counter)
    _avg_len: float = 0.0

    def __post_init__(self) -> None:
        self._tokens = [Counter(stems(f"{chunk.title or ''} {chunk.text}")) for chunk in self.chunks]
        for counts in self._tokens:
            self._df.update(counts.keys())
        lengths = [sum(counts.values()) for counts in self._tokens]
        self._avg_len = (sum(lengths) / len(lengths)) if lengths else 0.0

    @property
    def dense_available(self) -> bool:
        return self.vectors is not None

    def by_id(self) -> dict[str, Chunk]:
        return {chunk.id: chunk for chunk in self.chunks}


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float
    lexical_score: float = 0.0
    lexical_coverage: float = 0.0
    dense_score: float | None = None
    lexical_rank: int | None = None
    dense_rank: int | None = None


def stems(text: str) -> list[str]:
    return [token[:STEM_CHARS] for token in word_tokens(text)]


# ---------------------------------------------------------------- chunking
def split_text(text: str, max_chars: int) -> list[str]:
    """Split on sentence boundaries into parts of at most max_chars (hard split if needed)."""
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.;:!?])\s+", text):
        pieces = [sentence[i : i + max_chars] for i in range(0, len(sentence), max_chars)] or [""]
        for piece in pieces:
            if current and len(current) + 1 + len(piece) > max_chars:
                parts.append(current)
                current = piece
            else:
                current = f"{current} {piece}".strip()
    if current:
        parts.append(current)
    return parts


def _references(references: list[LegalReference]) -> str:
    return " ".join(
        f"Dayanak: {ref.law_name} ({ref.law_number} sayılı) {ref.article}: {ref.summary}" for ref in references
    )


def build_chunks(report: ContractReport, max_chars: int = 800) -> list[Chunk]:
    chunks: list[Chunk] = []
    titles = {clause.id: clause.title or clause.id for clause in report.clauses}
    for clause in report.clauses:
        parts = split_text(clause.text, max_chars)
        for number, part in enumerate(parts, start=1):
            chunk_id = clause.id if len(parts) == 1 else f"{clause.id}-part{number}"
            chunks.append(Chunk(chunk_id, "clause", part, clause.id, clause.title))
    clause_of_finding = {finding.id: finding.clause_id for finding in report.findings}
    for finding in report.findings:
        label = category_label(finding.category)
        where = f" ({titles.get(finding.clause_id or '', finding.clause_id)})" if finding.clause_id else ""
        text = (
            f"Risk bulgusu{where}: {label}, önem: {_SEVERITY_TR.get(finding.severity, finding.severity)}. "
            f"{finding.explanation} Öneri: {finding.recommendation} {_references(finding.legal_references)}"
        )
        chunks.append(Chunk(finding.id, "finding", text.strip(), finding.clause_id, f"Risk: {label}"))
    for check in report.statutory_checks:
        details = [f"Kanuni sınır kontrolü: {check.title}. Sonuç: {_STATUS_TR.get(check.status, check.status)}."]
        if check.extracted_value:
            details.append(f"Sözleşmedeki değer: {check.extracted_value}.")
        if check.limit:
            details.append(f"Sınır: {check.limit}.")
        details += [check.explanation, _references([check.legal_basis])]
        chunks.append(Chunk(f"check-{check.rule_id}", "statutory_check", " ".join(details), check.clause_id, check.title))
    for missing in report.missing_clauses:
        text = (
            f"Eksik madde: {missing.title} (önem: {_IMPORTANCE_TR.get(missing.importance, missing.importance)}). "
            f"{missing.explanation} Önerilen madde: {missing.suggested_clause}"
        )
        chunks.append(Chunk(f"missing-{missing.topic}", "missing_clause", text, None, f"Eksik: {missing.title}"))
    for rewrite in report.rewrites:
        text = f"Değişiklik önerisi: {rewrite.suggested_text} Gerekçe: {rewrite.rationale}"
        title = f"Öneri: {titles.get(rewrite.clause_id, rewrite.clause_id)}"
        chunks.append(Chunk(f"rewrite-{rewrite.clause_id}", "rewrite", text, rewrite.clause_id, title))
    for number, decision in enumerate(report.related_decisions, start=1):
        meta = ", ".join(part for part in [decision.source, decision.decision_number, decision.decision_date] if part)
        text = f"İlgili karar: {decision.title} ({meta}). {(decision.excerpt or decision.relevance or '')[:max_chars]}"
        clause_id = clause_of_finding.get(decision.finding_id or "")
        chunks.append(Chunk(f"decision-{number}", "decision", text.strip(), clause_id, decision.title))
    return chunks


async def build_index(report: ContractReport, embedder: Embedder | None, max_chars: int = 800) -> ChatIndex:
    """Chunk the report and embed the chunks; an embedding failure leaves the index lexical-only."""
    chunks = build_chunks(report, max_chars)
    if embedder is None:
        return ChatIndex(chunks, None, None, "no_embedder")
    try:
        vectors = await embedder.embed_documents([f"{chunk.title or ''}\n{chunk.text}" for chunk in chunks])
        if len(vectors) != len(chunks):
            raise ValueError("embedding count mismatch")
        return ChatIndex(chunks, vectors, embedder.name)
    except Exception as exc:
        return ChatIndex(chunks, None, embedder.name, exc.__class__.__name__)


# ---------------------------------------------------------------- scoring
def _idf(total: int, df: int) -> float:
    return math.log(1 + (total - df + 0.5) / (df + 0.5))


def lexical_scores(index: ChatIndex, question: str) -> tuple[list[float], list[float]]:
    """BM25 score per chunk and the share of the question's IDF mass the chunk matches.

    A query term that occurs in no chunk counts with the IDF of a term that
    occurs in one chunk, so a question about something the contract never
    mentions ("evcil hayvan") has low coverage even if one common word matches.
    """
    query = set(stems(question))
    total = len(index.chunks)
    idf = {term: _idf(total, index._df[term] or 1) for term in query}
    query_mass = sum(idf.values()) or 1.0
    scores: list[float] = []
    coverage: list[float] = []
    for counts in index._tokens:
        length = sum(counts.values())
        score = 0.0
        matched = 0.0
        for term in query:
            tf = counts.get(term, 0)
            if not tf:
                continue
            norm = BM25_K1 * (1 - BM25_B + BM25_B * length / (index._avg_len or 1))
            score += idf[term] * tf * (BM25_K1 + 1) / (tf + norm)
            matched += idf[term]
        scores.append(score)
        coverage.append(matched / query_mass)
    return scores, coverage


def rank_chunks(
    index: ChatIndex,
    question: str,
    query_vector: Vector | None,
    *,
    mode: RetrievalMode = "hybrid",
    top_k: int = 6,
    min_dense_similarity: float = 0.3,
    apply_threshold: bool = True,
) -> list[RetrievedChunk]:
    """Rank chunks for a question; `query_vector` is needed for dense and hybrid modes."""
    lexical, coverage = lexical_scores(index, question)
    dense: list[float] | None = None
    if query_vector is not None and index.vectors is not None:
        dense = [cosine(query_vector, vector) for vector in index.vectors]
    if mode in ("hybrid", "dense") and dense is None:
        mode = "lexical" if mode == "hybrid" else mode
        if mode == "dense":
            return []
    lex_floor = LEXICAL_MIN_SCORE if apply_threshold else 1e-9
    cov_floor = LEXICAL_MIN_COVERAGE if apply_threshold else 0.0
    lex_order = sorted(
        (i for i, s in enumerate(lexical) if s >= lex_floor and coverage[i] >= cov_floor),
        key=lambda i: -lexical[i],
    )
    dense_order: list[int] = []
    if dense is not None:
        floor = min_dense_similarity if apply_threshold else -1.0
        dense_order = sorted((i for i, s in enumerate(dense) if s >= floor), key=lambda i: -dense[i])
    lex_rank = {i: rank for rank, i in enumerate(lex_order, start=1)}
    dense_rank = {i: rank for rank, i in enumerate(dense_order, start=1)}

    if mode == "lexical":
        scored = [(i, lexical[i]) for i in lex_order]
    elif mode == "dense":
        scored = [(i, dense[i]) for i in dense_order]  # type: ignore[index]
    else:
        fused: dict[int, float] = {}
        for ranks in (lex_rank, dense_rank):
            for i, rank in ranks.items():
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + rank)
        scored = sorted(fused.items(), key=lambda item: (-item[1], item[0]))
    return [
        RetrievedChunk(
            chunk=index.chunks[i],
            score=round(score, 6),
            lexical_score=round(lexical[i], 4),
            lexical_coverage=round(coverage[i], 4),
            dense_score=round(dense[i], 4) if dense is not None else None,
            lexical_rank=lex_rank.get(i),
            dense_rank=dense_rank.get(i),
        )
        for i, score in scored[:top_k]
    ]


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    mode: RetrievalMode  # the mode actually used
    dense_failed: bool = False


async def retrieve(
    index: ChatIndex,
    question: str,
    embedder: Embedder | None,
    *,
    mode: RetrievalMode = "hybrid",
    top_k: int = 6,
    min_dense_similarity: float | None = None,
    apply_threshold: bool = True,
) -> RetrievalResult:
    """Ranked chunks with scores for a question (no answer generation).

    Falls back to lexical-only when the index has no vectors or the question
    cannot be embedded; `dense_failed` and `mode` report that.
    """
    query_vector: Vector | None = None
    dense_failed = False
    if mode != "lexical":
        if embedder is None or not index.dense_available:
            dense_failed = True
        else:
            try:
                query_vector = await embedder.embed_query(question)
            except Exception:
                dense_failed = True
    if dense_failed and mode == "dense":
        return RetrievalResult([], "dense", True)
    used: RetrievalMode = "lexical" if dense_failed else mode
    threshold = min_dense_similarity
    if threshold is None:
        threshold = getattr(embedder, "default_min_similarity", 0.3)
    ranked = rank_chunks(
        index,
        question,
        query_vector,
        mode=used,
        top_k=top_k,
        min_dense_similarity=threshold,
        apply_threshold=apply_threshold,
    )
    return RetrievalResult(ranked, used, dense_failed)

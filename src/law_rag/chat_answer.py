"""Answer generation for the contract chat, with output validation.

GeminiChatAnswerer: one call per question (at most one regeneration). The
prompt gives the question, a short recent history and the retrieved chunks,
and asks for a Turkish answer from those chunks only, citing chunk ids in
square brackets, or the marker KAPSAM_DIŞI when the chunks do not answer it.
Validation:
* citations of ids that were not supplied are removed; an answer without any
  valid citation is regenerated once, then replaced by the extractive answer;
* statute / article numbers not present in the supplied chunks (the LLM must
  never be their source) trigger one regeneration, then are replaced by
  "ilgili kanun hükmü";
* a failed call falls back to the extractive answer with a note.
FakeChatAnswerer (offline) returns the deterministic extractive answer.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from .call_gate import CallGate
from .chat_index import Chunk
from .text_utils import searchable

DISCLAIMER = (
    "Bu yanıt, yüklenen sözleşmenin ve otomatik analiz sonuçlarının içeriğine dayanır; "
    "hukuki danışmanlık değildir. Önemli kararlardan önce bir avukata danışın."
)
NOT_COVERED_ANSWER = (
    "Bu soru, yüklenen sözleşmede ve analiz sonuçlarında ele alınmıyor; sözleşmede bu konuyla "
    "ilgili bir hüküm bulunamadı."
)
NOTE_LEXICAL_ONLY = "Anlamsal arama kullanılamadı; yalnızca kelime eşleşmesiyle arama yapıldı."
NOTE_EXTRACTIVE_FALLBACK = (
    "Yanıt modeli kullanılamadı veya geçerli kaynak gösteremedi; sözleşmeden ilgili bölümler alıntılandı."
)
NOTE_STATUTE_STRIPPED = (
    "Yanıtta kaynaklarda bulunmayan kanun veya madde numaraları vardı; bunlar çıkarıldı."
)
NOTE_EXTRACTIVE_MODE = "Çevrimdışı mod: yanıt, en ilgili bölümlerden alıntı yapılarak oluşturuldu."

NOT_COVERED_MARKER = "KAPSAM_DIŞI"
_SNIPPET_CHARS = 240
_HISTORY_ANSWER_CHARS = 400
_CITATION_RE = re.compile(r"\[([A-Za-z0-9_.\-]+(?:\s*,\s*[A-Za-z0-9_.\-]+)*)\]")
_STATUTE_RE = re.compile(
    r"\b(?:TBK|TTK|HMK|TMK|İİK|IIK|İK|KVKK|FSEK|BK)\b\.?\s*(?:m\.?|md\.?|madde(?:si)?)?\s*\d+(?:/\d+)?"
    r"|\b\d{3,5}\s+say[ıi]l[ıi]"
    r"|\bm(?:d)?\.\s*\d+(?:/\d+)?"
    r"|\bmadde\s+\d+(?:/\d+)?"
    r"|\b\d+(?:/\d+)?\s*\.\s*madde\w*",
    re.IGNORECASE,
)


@dataclass
class Turn:
    question: str
    answer: str


@dataclass
class DraftAnswer:
    text: str
    covered: bool
    answered_by: str  # "llm" | "extractive" | "not_covered"
    cited_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class ChatAnswerer(Protocol):
    async def answer(self, question: str, history: list[Turn], chunks: list[Chunk]) -> DraftAnswer:
        ...


def snippet(text: str, limit: int = _SNIPPET_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def not_covered() -> DraftAnswer:
    return DraftAnswer(NOT_COVERED_ANSWER, False, "not_covered")


def extractive_answer(chunks: list[Chunk], limit: int = 3) -> DraftAnswer:
    """Deterministic answer: quotes the top chunks with their ids."""
    if not chunks:
        return not_covered()
    top = chunks[:limit]
    lines = ["Sözleşmede ve analizde bu soruyla en ilgili bölümler:"]
    lines += [f"- [{chunk.id}] {chunk.title + ': ' if chunk.title else ''}{snippet(chunk.text)}" for chunk in top]
    return DraftAnswer("\n".join(lines), True, "extractive", [chunk.id for chunk in top])


# ---------------------------------------------------------------- validation
def cited_ids(text: str) -> list[str]:
    ids: list[str] = []
    for match in _CITATION_RE.finditer(text):
        for item in match.group(1).split(","):
            item = item.strip()
            if item and item not in ids:
                ids.append(item)
    return ids


def strip_unknown_citations(text: str, allowed: set[str]) -> tuple[str, list[str]]:
    kept: list[str] = []

    def replace(match: re.Match) -> str:
        items = [item.strip() for item in match.group(1).split(",") if item.strip() in allowed]
        for item in items:
            if item not in kept:
                kept.append(item)
        return f"[{', '.join(items)}]" if items else ""

    cleaned = _CITATION_RE.sub(replace, text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip(), kept


def allowed_numbers(chunks: list[Chunk]) -> set[str]:
    return set(re.findall(r"\d+", " ".join(f"{chunk.title or ''} {chunk.text}" for chunk in chunks)))


def unsupported_references(text: str, numbers: set[str]) -> list[str]:
    return [
        match.group(0)
        for match in _STATUTE_RE.finditer(text)
        if any(number not in numbers for number in re.findall(r"\d+", match.group(0)))
    ]


def strip_references(text: str, numbers: set[str]) -> str:
    def replace(match: re.Match) -> str:
        if all(number in numbers for number in re.findall(r"\d+", match.group(0))):
            return match.group(0)
        return "ilgili kanun hükmü"

    return _STATUTE_RE.sub(replace, text)


def is_not_covered(text: str) -> bool:
    key = searchable(text).strip().replace(" ", "_")
    return key.startswith(searchable(NOT_COVERED_MARKER)) or (len(key) < 40 and "kapsam_disi" in key)


# ------------------------------------------------------------------ prompt
def answer_prompt(question: str, history: list[Turn], chunks: list[Chunk], strict: bool = False) -> str:
    sources = "\n\n".join(
        f"[{chunk.id}] ({chunk.type}{', ' + chunk.title if chunk.title else ''})\n{chunk.text}" for chunk in chunks
    )
    past = "\n".join(
        f"Kullanıcı: {turn.question}\nAsistan: {snippet(turn.answer, _HISTORY_ANSWER_CHARS)}" for turn in history
    )
    prompt = (
        "You answer questions about ONE Turkish contract that was uploaded and analysed. "
        "Use ONLY the numbered sources below (contract clauses and analysis results); do not use "
        "outside knowledge. Answer in Turkish with correct Turkish characters, in at most 6 sentences, "
        "plainly, addressing the user. After every statement, cite the supporting source ids in "
        "square brackets exactly as given, e.g. [clause-3] or [finding-1, check-lease_deposit_cap]. "
        "Do not mention any law name, law number or article number unless it appears in the cited "
        "source text. If the sources do not answer the question, reply with exactly "
        f"{NOT_COVERED_MARKER} and nothing else. Do not give legal advice beyond what the sources say.\n"
    )
    if strict:
        prompt += (
            "Your previous answer cited unknown sources or law/article numbers that are not in the "
            "sources. Cite only the ids below and only numbers that appear in the source text.\n"
        )
    if past:
        prompt += f"\nRecent conversation (for context only):\n{past}\n"
    return prompt + f"\nSources:\n{sources}\n\nQuestion: {question}\nAnswer:"


# ---------------------------------------------------------------- answerers
class FakeChatAnswerer:
    async def answer(self, question: str, history: list[Turn], chunks: list[Chunk]) -> DraftAnswer:
        draft = extractive_answer(chunks)
        if draft.covered:
            draft.notes.append(NOTE_EXTRACTIVE_MODE)
        return draft


class GeminiChatAnswerer:
    def __init__(self, app_settings: Any, gate: CallGate | None = None) -> None:
        from google import genai

        if not app_settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required for GeminiChatAnswerer.")
        self._model = app_settings.gemini_model
        self._client = genai.Client(api_key=app_settings.gemini_api_key)
        self._gate = gate or CallGate.from_settings(app_settings)

    async def _generate(self, prompt: str) -> str:
        async def call() -> Any:
            return await self._client.aio.models.generate_content(model=self._model, contents=prompt)

        response = await self._gate.run(call)
        return (response.text or "").strip()

    async def answer(self, question: str, history: list[Turn], chunks: list[Chunk]) -> DraftAnswer:
        if not chunks:
            return not_covered()
        allowed = {chunk.id for chunk in chunks}
        numbers = allowed_numbers(chunks)
        for attempt in (1, 2):
            try:
                raw = await self._generate(answer_prompt(question, history, chunks, strict=attempt == 2))
            except Exception:
                break
            if not raw:
                continue
            if is_not_covered(raw):
                return not_covered()
            text, kept = strip_unknown_citations(raw, allowed)
            bad = unsupported_references(text, numbers)
            if (not kept or bad) and attempt == 1:
                continue
            if not kept:
                break
            notes: list[str] = []
            if bad:
                text = strip_references(text, numbers)
                notes.append(NOTE_STATUTE_STRIPPED)
            return DraftAnswer(text, True, "llm", kept, notes)
        draft = extractive_answer(chunks)
        draft.notes.append(NOTE_EXTRACTIVE_FALLBACK)
        return draft

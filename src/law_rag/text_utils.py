"""Small text helpers shared by the analyzers, the CRAG grader and segmentation."""

import json
import re
import unicodedata
from typing import Any


def searchable(text: str) -> str:
    """Casefold and strip diacritics so Turkish text can be matched loosely.

    The dotless "ı" does not decompose under NFKD, so it is mapped explicitly.
    """
    normalized = unicodedata.normalize("NFKD", text.casefold().replace("ı", "i"))
    return "".join(char for char in normalized if not unicodedata.combining(char))


# Function words and question words that carry no topic, after searchable().
# Used by the chat retriever (lexical score) and the offline fake embedder.
STOPWORDS: frozenset[str] = frozenset(
    """
    acaba ama ancak bana beni ben bir biri bu bunu bunun da de daha diye en gibi hangi
    hem her icin ile ise ki kim mi mu mı mü midir mudur na nasil ne neden nedir neler
    nerede nereye nicin o olan olarak olur olursa onu sen siz soyle su sunu ve veya ya
    yani var yok mi misin miyim miyiz musun muyum benim bizim sizin icinde hakkinda
    nelerdir kadar sonra once zaman gerekir gerekiyor
    the a an of to and or is are what how can do does i my
    """.split()
)


def word_tokens(text: str) -> list[str]:
    """Lowercase, diacritic-free alphanumeric tokens without stopwords."""
    return [token for token in re.findall(r"[a-z0-9]+", searchable(text)) if token not in STOPWORDS]


def json_array_from_text(text: str) -> list[dict[str, Any]]:
    """Parse a JSON array of objects out of free-form model output.

    Tolerates markdown fences and prose around the array. Raises ValueError
    (or json.JSONDecodeError) when no array can be parsed.
    """
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    elif "[" in cleaned and "]" in cleaned:
        cleaned = cleaned[cleaned.find("[") : cleaned.rfind("]") + 1]

    payload = json.loads(cleaned)
    if not isinstance(payload, list):
        raise ValueError("Model response must be a JSON array.")
    return [item for item in payload if isinstance(item, dict)]


def split_text_by_budget(text: str, budget: int) -> list[str]:
    """Split text into chunks of at most `budget` characters on line boundaries.

    A single line longer than the budget is hard-split; nothing is dropped.
    """
    if budget <= 0:
        raise ValueError("budget must be positive")
    if len(text) <= budget:
        return [text] if text else []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines():
        pieces = [line[i : i + budget] for i in range(0, len(line), budget)] or [""]
        for piece in pieces:
            added = len(piece) + (1 if current else 0)
            if current and current_len + added > budget:
                chunks.append("\n".join(current))
                current, current_len = [], 0
                added = len(piece)
            current.append(piece)
            current_len += added
    if current:
        chunks.append("\n".join(current))
    return [chunk for chunk in chunks if chunk.strip()]


_LAW_CITATION_RE = re.compile(
    r"\b(?:TBK|TTK|HMK|TMK|İİK|IIK|İK|KVKK|FSEK|BK)\b\.?\s*(?:m\.?|md\.?|madde(?:si)?)?\s*\d+(?:/\d+)?"
    r"|\b\d{3,5}\s+say[ıi]l[ıi]"
    r"|\bm(?:d)?\.\s*\d+(?:/\d+)?"
    r"|kanun\w*(?:['’]?(?:n?[ıiuü]n|un|in|de|da|a|e))?\s+(?:m\.?|md\.?)?\s*\d+(?:/\d+)?(?:\s*\.\s*madde\w*)?",
    re.IGNORECASE,
)
_CLAUSE_REF_RE = re.compile(
    r"\bmadde\s+\d+(?:/\d+)?"
    r"|\b\d+(?:/\d+)?\s*\.\s*madde\w*",
    re.IGNORECASE,
)
STATUTE_RE = re.compile(f"{_LAW_CITATION_RE.pattern}|{_CLAUSE_REF_RE.pattern}", re.IGNORECASE)


def _match_numbers(pattern: re.Pattern[str], text: str) -> set[str]:
    numbers: set[str] = set()
    for match in pattern.finditer(text or ""):
        numbers.update(re.findall(r"\d+", match.group(0)))
    return numbers


def extract_statute_numbers(text: str) -> tuple[set[str], set[str]]:
    law_nums = _match_numbers(_LAW_CITATION_RE, text)
    clause_nums = _match_numbers(_CLAUSE_REF_RE, text) | law_nums
    return law_nums, clause_nums


def unsupported_statutes(text: str, law_nums: set[str], clause_nums: set[str]) -> list[str]:
    bad: list[str] = []
    for match in STATUTE_RE.finditer(text or ""):
        token = match.group(0)
        allowed = law_nums if _LAW_CITATION_RE.fullmatch(token) else clause_nums
        if any(num not in allowed for num in re.findall(r"\d+", token)):
            bad.append(token)
    return bad


def strip_unsupported_statutes(text: str, law_nums: set[str], clause_nums: set[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        allowed = law_nums if _LAW_CITATION_RE.fullmatch(token) else clause_nums
        if all(num in allowed for num in re.findall(r"\d+", token)):
            return token
        return "ilgili kanun hükmü"

    return STATUTE_RE.sub(replace, text or "")

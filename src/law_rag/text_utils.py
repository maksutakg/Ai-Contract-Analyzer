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

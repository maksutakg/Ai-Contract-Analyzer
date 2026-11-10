"""Text embedders for the contract chat retriever.

* GeminiEmbedder calls the Gemini embeddings endpoint through google-genai
  (`client.aio.models.embed_content`). Default model `gemini-embedding-001`
  (EMBEDDING_MODEL): documents are embedded with task_type RETRIEVAL_DOCUMENT,
  questions with RETRIEVAL_QUERY, at EMBEDDING_DIMENSIONS (768 by default; the
  docs say vectors below 3072 dimensions must be normalised by the caller,
  which is done here for every vector). For the `gemini-embedding-2` family the
  docs say task_type is not supported and a list of strings is aggregated into
  one vector, so each text is sent as its own Content with the documented
  "title: none | text: ..." / "task: search result | query: ..." prefixes.
* FakeEmbedder is deterministic and offline: hashed character 3- and 4-grams of
  the first 7 characters of each diacritic-free word (stopwords removed).
  Shared n-grams make Turkish inflections such as "depozitomu" and "depozito"
  near neighbours, and also partial matches such as "kiracı" / "kiralanan".
"""

import math
import zlib
from typing import Any, Protocol

from .call_gate import CallGate
from .text_utils import word_tokens

Vector = list[float]
_PREFIX_CHARS = 7


class Embedder(Protocol):
    name: str
    # Cosine similarity below which a dense-only match is not trusted.
    default_min_similarity: float

    async def embed_documents(self, texts: list[str]) -> list[Vector]:
        ...

    async def embed_query(self, text: str) -> Vector:
        ...


def normalize(vector: list[float]) -> Vector:
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else list(vector)


def cosine(a: Vector, b: Vector) -> float:
    """Dot product; both vectors are already unit length."""
    return sum(x * y for x, y in zip(a, b))


class FakeEmbedder:
    name = "fake-char-ngram"
    default_min_similarity = 0.3

    def __init__(self, dimensions: int = 512) -> None:
        self._dimensions = dimensions

    def _embed(self, text: str) -> Vector:
        vector = [0.0] * self._dimensions
        for token in word_tokens(text):
            # Only the word start: Turkish roots come first and shared suffixes
            # ("-ebilir", "-mesi") would otherwise make unrelated words similar.
            padded = f" {token[:_PREFIX_CHARS]}" + (" " if len(token) <= _PREFIX_CHARS else "")
            for size in (3, 4):
                for start in range(max(1, len(padded) - size + 1)):
                    gram = padded[start : start + size]
                    vector[zlib.crc32(gram.encode()) % self._dimensions] += 1.0
        return normalize([math.log1p(value) for value in vector])

    async def embed_documents(self, texts: list[str]) -> list[Vector]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, text: str) -> Vector:
        return self._embed(text)


class GeminiEmbedder:
    # Unverified starting point for gemini-embedding-001 at 768 dimensions; set
    # CHAT_MIN_DENSE_SIMILARITY after measuring (evaluation package).
    default_min_similarity = 0.6

    def __init__(self, app_settings: Any, gate: CallGate | None = None) -> None:
        from google import genai

        if not app_settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required for GeminiEmbedder.")
        self.name = app_settings.embedding_model
        self._dimensions = app_settings.embedding_dimensions
        self._batch_size = app_settings.embedding_batch_size
        self._client = genai.Client(api_key=app_settings.gemini_api_key)
        self._gate = gate or CallGate.from_settings(app_settings)

    @property
    def _is_v2(self) -> bool:
        return self.name.startswith("gemini-embedding-2")

    async def _embed(self, texts: list[str], task_type: str) -> list[Vector]:
        from google.genai import types

        if self._is_v2:
            prefix = "task: search result | query: " if task_type == "RETRIEVAL_QUERY" else "title: none | text: "
            contents: Any = [types.Content(parts=[types.Part(text=prefix + text)]) for text in texts]
            config = types.EmbedContentConfig(output_dimensionality=self._dimensions)
        else:
            contents = texts
            config = types.EmbedContentConfig(task_type=task_type, output_dimensionality=self._dimensions)

        async def call() -> Any:
            return await self._client.aio.models.embed_content(model=self.name, contents=contents, config=config)

        response = await self._gate.run(call)
        embeddings = response.embeddings or []
        if len(embeddings) != len(texts):
            raise ValueError("Embedding response does not match the number of inputs.")
        return [normalize(list(item.values or [])) for item in embeddings]

    async def embed_documents(self, texts: list[str]) -> list[Vector]:
        vectors: list[Vector] = []
        for start in range(0, len(texts), self._batch_size):
            vectors.extend(await self._embed(texts[start : start + self._batch_size], "RETRIEVAL_DOCUMENT"))
        return vectors

    async def embed_query(self, text: str) -> Vector:
        return (await self._embed([text], "RETRIEVAL_QUERY"))[0]

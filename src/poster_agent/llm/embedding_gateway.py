"""Embedding provider boundary and OpenAI adapter."""

from typing import Protocol

from openai import AsyncOpenAI, OpenAIError

from poster_agent.domain.errors import BrandKnowledgeError
from poster_agent.llm.retry import openai_retrying


class EmbeddingGateway(Protocol):
    """Convert text into vectors without exposing provider SDK types."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed non-empty strings in input order."""

        ...


class OpenAIEmbeddingGateway:
    """OpenAI embeddings adapter with bounded transient retries."""

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 60.0) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=0,
        )
        self._model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        cleaned = [text.strip() for text in texts]
        if not cleaned or any(not text for text in cleaned):
            raise BrandKnowledgeError("Embedding input must contain non-empty text.")

        vectors: list[list[float]] = []
        batch_size = 64
        for start in range(0, len(cleaned), batch_size):
            vectors.extend(await self._embed_batch(cleaned[start : start + batch_size]))
        return vectors

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        try:
            async for attempt in openai_retrying():
                with attempt:
                    response = await self._client.embeddings.create(
                        input=texts,
                        model=self._model,
                        encoding_format="float",
                    )
        except OpenAIError as exc:
            raise BrandKnowledgeError(
                "OpenAI embedding failed. Check credentials, model access, and network."
            ) from exc

        ordered = sorted(response.data, key=lambda item: item.index)
        if len(ordered) != len(texts):
            raise BrandKnowledgeError("Embedding provider returned an unexpected vector count.")
        return [self._normalize(item.embedding) for item in ordered]

    @staticmethod
    def _normalize(vector: list[float]) -> list[float]:
        magnitude = sum(value * value for value in vector) ** 0.5
        if magnitude == 0:
            return vector
        return [value / magnitude for value in vector]

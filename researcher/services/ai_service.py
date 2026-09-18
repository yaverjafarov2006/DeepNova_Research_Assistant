"""The only place in the codebase that touches `ai.*`.

Every call to the provided module goes through here, which gives us one spot
for retries, logging and timing — exactly as the assignment's contract demands
("do not call provider SDKs or source APIs directly from your business logic").

`ai.synthesize` is synchronous (the LLM SDKs are blocking), so it runs in a
worker thread via `asyncio.to_thread`; otherwise a single synthesis would
freeze the event loop for several seconds.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ai import fetch_arxiv, fetch_web, fetch_wikipedia, synthesize
from ai.providers.base import LLMProvider, ProviderError
from ai.schemas import AnswerWithCitations, Source

from researcher.config import Settings
from researcher.logging_setup import get_logger
from researcher.services.retry import retry_async

logger = get_logger(__name__)


def _retryable_exceptions() -> tuple[type[BaseException], ...]:
    """Transient error types. httpx is optional, so it's imported defensively."""
    errors: list[type[BaseException]] = [ProviderError, OSError]
    try:
        import httpx  # type: ignore

        errors.append(httpx.HTTPError)
    except ImportError:  # pragma: no cover - httpx is a hard dep in practice
        pass
    return tuple(errors)


class AIService:
    """Thin, retrying, logged facade over the provided AI module."""

    def __init__(self, settings: Settings, *, llm: LLMProvider | None = None) -> None:
        self.settings = settings
        self._llm = llm  # injectable → tests never need an API key
        self._retryable = _retryable_exceptions()

    # --- source fetchers -------------------------------------------------

    async def fetch(
        self,
        source: str,
        query: str,
        *,
        client: Any = None,
        max_results: int | None = None,
    ) -> list[Source]:
        """Fetch one source by name, with retries."""
        n = max_results or self.settings.max_results_per_source

        if source == "wikipedia":
            call = lambda: fetch_wikipedia(query, max_results=n, client=client)  # noqa: E731
        elif source == "arxiv":
            call = lambda: fetch_arxiv(query, max_results=n, client=client)  # noqa: E731
        elif source == "web":
            call = lambda: fetch_web(query, max_results=n, client=client)  # noqa: E731
        else:
            raise ValueError(f"unknown source {source!r}")

        return await retry_async(
            call,
            attempts=self.settings.retry_attempts,
            initial_delay=self.settings.retry_initial_delay,
            max_delay=self.settings.retry_max_delay,
            retry_on=self._retryable,
            label=f"fetch:{source}",
        )

    # --- synthesis -------------------------------------------------------

    async def synthesize(
        self, question: str, sources: list[Source]
    ) -> AnswerWithCitations:
        """Run the (blocking) synthesizer off the event loop, with retries."""
        if not sources:
            raise ValueError("cannot synthesize without sources")

        async def _call() -> AnswerWithCitations:
            return await asyncio.to_thread(
                synthesize, question, sources, llm=self._llm
            )

        logger.info("synthesizing answer from %d sources", len(sources))
        return await retry_async(
            _call,
            attempts=self.settings.retry_attempts,
            initial_delay=self.settings.retry_initial_delay,
            max_delay=self.settings.retry_max_delay,
            retry_on=self._retryable,
            label="synthesize",
        )

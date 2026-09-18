"""Business logic: validate → fetch in parallel → synthesize → report.

The CLI is a thin shell over this class; tests drive it directly. Nothing here
imports `click`, `httpx` or any provider SDK, which is what keeps the layer
testable offline.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Sequence

from ai.providers.base import LLMProvider
from ai.schemas import AnswerWithCitations, Citation, Source

from researcher.config import Settings, get_settings
from researcher.concurrency.orchestrator import SourceOrchestrator
from researcher.logging_setup import get_logger
from researcher.models import FetchReport, ResearchResult, Timer
from researcher.services.ai_service import AIService
from researcher.services.cache import ResearchCache
from researcher.storage.cache_store import CacheStore, build_cache_store
from researcher.validation import sanitise_output, validate_question

logger = get_logger(__name__)


class NoSourcesError(RuntimeError):
    """Every source failed or returned nothing — there is nothing to synthesize."""


def _fingerprint(sources: Sequence[Source]) -> str:
    """Short hash of the source set, so the answer cache is keyed by evidence."""
    joined = "|".join(sorted(s.url.strip().lower() for s in sources))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]


class Researcher:
    """One research call, end to end."""

    def __init__(
        self,
        ai_service: AIService,
        orchestrator: SourceOrchestrator,
        cache: ResearchCache,
        settings: Settings,
    ) -> None:
        self.ai = ai_service
        self.orchestrator = orchestrator
        self.cache = cache
        self.settings = settings

    # --- main entry point ------------------------------------------------

    async def ask(
        self,
        question: str,
        *,
        sources: Sequence[str] | None = None,
        client: Any = None,
    ) -> ResearchResult:
        """Answer `question` with citations. Raises on invalid input only."""
        clean = validate_question(
            question,
            min_length=self.settings.min_question_length,
            max_length=self.settings.max_question_length,
        )
        logger.info("research started: %r", clean)

        total = Timer()
        with total:
            report = await self.orchestrator.fetch_all(
                clean, sources=sources, client=client
            )
            collected = report.sources

            if not collected:
                failures = "; ".join(o.summary() for o in report.failed) or "boş nəticə"
                raise NoSourcesError(
                    f"Heç bir mənbədən nəticə alınmadı ({failures})."
                )

            fingerprint = _fingerprint(collected)
            cached_answer = await self.cache.get_answer(clean, fingerprint)

            synth = Timer()
            if cached_answer is not None:
                logger.info("answer served from cache")
                answer = self._rebuild_answer(cached_answer, collected)
                from_cache = True
            else:
                with synth:
                    answer = await self.ai.synthesize(clean, collected)
                answer = AnswerWithCitations(
                    question=answer.question,
                    answer=sanitise_output(answer.answer),
                    citations=answer.citations,
                )
                await self.cache.set_answer(clean, fingerprint, answer.to_dict())
                from_cache = False

        result = ResearchResult.from_answer(
            answer,
            report,
            synth_ms=synth.ms,
            total_ms=total.ms,
            answer_from_cache=from_cache,
        )
        logger.info(
            "research finished in %.0f ms (fetch %.0f ms parallel vs %.0f ms sequential, "
            "speed-up ×%.2f)",
            result.total_ms, result.fetch_wall_ms, result.fetch_sequential_ms, result.speedup,
        )
        return result

    # --- benchmark -------------------------------------------------------

    async def benchmark(
        self, question: str, *, sources: Sequence[str] | None = None
    ) -> dict[str, FetchReport]:
        """Fetch the same question sequentially and in parallel, cache off.

        Returns both reports so the README can quote real numbers.
        """
        clean = validate_question(
            question,
            min_length=self.settings.min_question_length,
            max_length=self.settings.max_question_length,
        )
        was_enabled = self.cache.enabled
        self.cache.enabled = False
        try:
            sequential = await self.orchestrator.fetch_sequential(clean, sources=sources)
            parallel = await self.orchestrator.fetch_all(clean, sources=sources)
        finally:
            self.cache.enabled = was_enabled
        return {"sequential": sequential, "parallel": parallel}

    # --- helpers ---------------------------------------------------------

    @staticmethod
    def _rebuild_answer(
        payload: dict, collected: Sequence[Source]
    ) -> AnswerWithCitations:
        """Turn a cached `to_dict()` payload back into a rich answer object."""
        by_url = {s.url: s for s in collected}
        citations: list[Citation] = []
        for item in payload.get("citations", []):
            src = by_url.get(item.get("url"))
            if src is None:
                continue
            citations.append(Citation(index=int(item["index"]), source=src))
        return AnswerWithCitations(
            question=payload["question"],
            answer=payload["answer"],
            citations=citations,
        )


def build_researcher(
    settings: Settings | None = None,
    *,
    llm: LLMProvider | None = None,
    store: CacheStore | None = None,
    use_cache: bool | None = None,
    demo: bool = False,
) -> Researcher:
    """Wire the whole object graph. The CLI and the tests both call this."""
    settings = settings or get_settings()
    store = store or build_cache_store(settings.cache_backend, settings.cache_dir)
    enabled = settings.cache_enabled if use_cache is None else use_cache
    cache = ResearchCache(
        store, ttl_seconds=settings.cache_ttl_seconds, enabled=enabled
    )
    if demo:
        from researcher.demo import DemoAIService

        ai_service: AIService = DemoAIService(settings, llm=llm)
    else:
        ai_service = AIService(settings, llm=llm)
    orchestrator = SourceOrchestrator(ai_service, cache, settings)
    return Researcher(ai_service, orchestrator, cache, settings)

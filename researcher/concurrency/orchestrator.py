"""Parallel source orchestration — the heart of the assignment.

Guarantees
----------
1. **Parallel.** The three fetchers run under one `asyncio.gather`, so the
   wall-clock cost is `max(t_wiki, t_arxiv, t_web)`, not their sum.
2. **Per-source timeout.** Each task carries its own timeout. A stalled
   Wikipedia call cannot eat arXiv's budget.
3. **Graceful degradation.** `return_exceptions=True` plus a per-task
   try/except means one dead source degrades the answer instead of killing it;
   the failure is recorded in `FetchReport.notes()` and surfaced to the user.
4. **One connection pool.** A single `httpx.AsyncClient` is shared by all three
   fetchers (they all accept a `client=` kwarg), so TLS handshakes are not
   repeated three times per question.
5. **Cache-aware.** A cached source returns instantly and never hits the
   network; cache lookups themselves are part of the same parallel round.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any, Iterable, Sequence

from researcher.config import SOURCE_NAMES, Settings
from researcher.logging_setup import get_logger
from researcher.models import FetchReport, FetchStatus, SourceFetchOutcome
from researcher.services.ai_service import AIService
from researcher.services.cache import ResearchCache

logger = get_logger(__name__)


@contextlib.asynccontextmanager
async def _timeout(seconds: float):
    """`asyncio.timeout` on 3.11+, with a portable fallback."""
    timeout_cm = getattr(asyncio, "timeout", None)
    if timeout_cm is not None:
        async with timeout_cm(seconds):
            yield
    else:  # pragma: no cover - Python 3.10 and older
        task = asyncio.current_task()
        handle = asyncio.get_running_loop().call_later(
            seconds, lambda: task.cancel() if task else None
        )
        try:
            yield
        except asyncio.CancelledError as exc:
            raise asyncio.TimeoutError from exc
        finally:
            handle.cancel()


class SourceOrchestrator:
    """Runs the configured fetchers concurrently and reports on each one."""

    def __init__(
        self,
        ai_service: AIService,
        cache: ResearchCache,
        settings: Settings,
    ) -> None:
        self.ai = ai_service
        self.cache = cache
        self.settings = settings

    # --- public API ------------------------------------------------------

    async def fetch_all(
        self,
        query: str,
        *,
        sources: Sequence[str] | None = None,
        client: Any = None,
    ) -> FetchReport:
        """Fetch every enabled source in parallel. Never raises on source failure."""
        enabled = tuple(sources or self.settings.enabled_sources)
        own_client = False
        if client is None:
            client = self._new_client()
            own_client = client is not None

        started = time.perf_counter()
        try:
            tasks = [self._fetch_one(name, query, client) for name in enabled]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            if own_client:
                await client.aclose()
        wall_ms = (time.perf_counter() - started) * 1000.0

        outcomes = self._normalise(enabled, results)
        outcomes += [
            SourceFetchOutcome(name=name, status=FetchStatus.SKIPPED)
            for name in SOURCE_NAMES
            if name not in enabled
        ]

        report = FetchReport(outcomes=outcomes, wall_ms=wall_ms)
        logger.info(
            "parallel fetch finished in %.0f ms (sequential equivalent %.0f ms) — %s",
            report.wall_ms,
            report.sequential_ms,
            "; ".join(o.summary() for o in outcomes if o.status is not FetchStatus.SKIPPED),
        )
        return report

    async def fetch_sequential(
        self,
        query: str,
        *,
        sources: Sequence[str] | None = None,
        client: Any = None,
    ) -> FetchReport:
        """Same work, one source after another. Used only by the benchmark."""
        enabled = tuple(sources or self.settings.enabled_sources)
        own_client = False
        if client is None:
            client = self._new_client()
            own_client = client is not None

        started = time.perf_counter()
        outcomes: list[SourceFetchOutcome] = []
        try:
            for name in enabled:
                outcomes.append(await self._fetch_one(name, query, client))
        finally:
            if own_client:
                await client.aclose()
        wall_ms = (time.perf_counter() - started) * 1000.0
        return FetchReport(outcomes=outcomes, wall_ms=wall_ms)

    # --- internals -------------------------------------------------------

    def _new_client(self) -> Any:
        """One shared connection pool for all fetchers in this request."""
        try:
            import httpx  # type: ignore
        except ImportError:  # pragma: no cover
            logger.warning("httpx not installed — fetchers will manage their own clients")
            return None
        return httpx.AsyncClient(
            timeout=self.settings.per_source_timeout_seconds,
            headers={"User-Agent": "async-research-assistant/1.0 (NAIC Topic 4)"},
            follow_redirects=True,
        )

    async def _fetch_one(
        self, name: str, query: str, client: Any
    ) -> SourceFetchOutcome:
        """Cache lookup → timed, retried fetch → outcome. Never raises."""
        started = time.perf_counter()

        cached = await self.cache.get_sources(name, query)
        if cached is not None:
            elapsed = (time.perf_counter() - started) * 1000.0
            return SourceFetchOutcome(
                name=name,
                status=FetchStatus.OK if cached else FetchStatus.EMPTY,
                count=len(cached),
                elapsed_ms=elapsed,
                from_cache=True,
                sources=cached,
            )

        try:
            async with _timeout(self.settings.per_source_timeout_seconds):
                sources = await self.ai.fetch(name, query, client=client)
        except (asyncio.TimeoutError, TimeoutError):
            elapsed = (time.perf_counter() - started) * 1000.0
            logger.warning(
                "%s timed out after %.1fs", name, self.settings.per_source_timeout_seconds
            )
            return SourceFetchOutcome(
                name=name,
                status=FetchStatus.TIMEOUT,
                elapsed_ms=elapsed,
                error=f"{self.settings.per_source_timeout_seconds:.0f}s timeout aşıldı",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000.0
            logger.warning("%s failed: %s", name, exc)
            return SourceFetchOutcome(
                name=name,
                status=FetchStatus.ERROR,
                elapsed_ms=elapsed,
                error=str(exc)[:300],
            )

        elapsed = (time.perf_counter() - started) * 1000.0
        if sources:
            await self.cache.set_sources(name, query, sources)
        return SourceFetchOutcome(
            name=name,
            status=FetchStatus.OK if sources else FetchStatus.EMPTY,
            count=len(sources),
            elapsed_ms=elapsed,
            sources=list(sources),
        )

    @staticmethod
    def _normalise(
        names: Iterable[str], results: Sequence[Any]
    ) -> list[SourceFetchOutcome]:
        """Turn gather's mixed results into outcomes (defence in depth)."""
        outcomes: list[SourceFetchOutcome] = []
        for name, result in zip(names, results):
            if isinstance(result, SourceFetchOutcome):
                outcomes.append(result)
            elif isinstance(result, BaseException):
                outcomes.append(
                    SourceFetchOutcome(
                        name=name, status=FetchStatus.ERROR, error=str(result)[:300]
                    )
                )
            else:  # pragma: no cover - shape guard
                outcomes.append(
                    SourceFetchOutcome(
                        name=name,
                        status=FetchStatus.ERROR,
                        error=f"unexpected result type {type(result)!r}",
                    )
                )
        return outcomes

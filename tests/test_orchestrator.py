"""Tests for the parallel orchestrator: concurrency, timeouts, degradation."""

from __future__ import annotations

import asyncio
import time

import pytest

from ai.providers.base import ProviderError
from ai.schemas import Source
from researcher.concurrency.orchestrator import SourceOrchestrator
from researcher.models import FetchStatus

from conftest import StubAIService

pytestmark = pytest.mark.asyncio


def _orch(settings, cache, script) -> SourceOrchestrator:
    return SourceOrchestrator(StubAIService(settings, script), cache, settings)


async def test_fetch_all_combines_every_source(
    settings, cache, wiki_sources, arxiv_sources, web_sources
):
    orch = _orch(settings, cache, {
        "wikipedia": wiki_sources, "arxiv": arxiv_sources, "web": web_sources,
    })
    report = await orch.fetch_all("photosynthesis")
    assert len(report.sources) == 3
    assert {o.status for o in report.outcomes} == {FetchStatus.OK}
    assert not report.degraded


async def test_sources_are_deduplicated_by_url(settings, cache, wiki_sources):
    duplicate = [Source(
        title="Other title",
        url=wiki_sources[0].url + "/",   # same URL, trailing slash
        snippet="dup",
        origin="web",
    )]
    orch = _orch(settings, cache, {
        "wikipedia": wiki_sources, "arxiv": [], "web": duplicate,
    })
    report = await orch.fetch_all("q")
    assert len(report.sources) == 1


async def test_runs_in_parallel_not_sequentially(settings, cache):
    async def slow(_query):
        await asyncio.sleep(0.15)
        return []

    orch = _orch(settings, cache, {"wikipedia": slow, "arxiv": slow, "web": slow})
    started = time.perf_counter()
    report = await orch.fetch_all("q")
    elapsed = time.perf_counter() - started

    # Three 150 ms tasks: parallel ≈ 0.15 s, sequential would be ≈ 0.45 s.
    assert elapsed < 0.35
    assert report.sequential_ms > report.wall_ms


async def test_failing_source_degrades_gracefully(settings, cache, wiki_sources):
    orch = _orch(settings, cache, {
        "wikipedia": wiki_sources,
        "arxiv": ProviderError("arXiv down"),
        "web": [],
    })
    report = await orch.fetch_all("q")
    assert report.sources == wiki_sources          # answer still possible
    assert report.degraded
    arxiv = next(o for o in report.outcomes if o.name == "arxiv")
    assert arxiv.status is FetchStatus.ERROR
    assert "arXiv down" in (arxiv.error or "")
    assert any("arxiv" in note for note in report.notes())


async def test_slow_source_times_out_without_blocking_others(
    settings, cache, wiki_sources
):
    orch = _orch(settings, cache, {
        "wikipedia": wiki_sources,
        "arxiv": 5.0,            # sleeps far past the 0.5 s per-source timeout
        "web": wiki_sources,
    })
    started = time.perf_counter()
    report = await orch.fetch_all("q")
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0
    arxiv = next(o for o in report.outcomes if o.name == "arxiv")
    assert arxiv.status is FetchStatus.TIMEOUT
    assert report.degraded


async def test_all_sources_failing_yields_no_sources(settings, cache):
    orch = _orch(settings, cache, {
        "wikipedia": ProviderError("x"),
        "arxiv": ProviderError("y"),
        "web": ProviderError("z"),
    })
    report = await orch.fetch_all("q")
    assert report.sources == []
    assert not report.degraded          # nothing survived → not "degraded", failed
    assert len(report.failed) == 3


async def test_source_subset_marks_others_skipped(settings, cache, wiki_sources):
    orch = _orch(settings, cache, {"wikipedia": wiki_sources})
    report = await orch.fetch_all("q", sources=["wikipedia"])
    statuses = {o.name: o.status for o in report.outcomes}
    assert statuses["wikipedia"] is FetchStatus.OK
    assert statuses["arxiv"] is FetchStatus.SKIPPED
    assert statuses["web"] is FetchStatus.SKIPPED


async def test_second_call_is_served_from_cache(settings, cache, wiki_sources):
    ai = StubAIService(settings, {"wikipedia": wiki_sources, "arxiv": [], "web": []})
    orch = SourceOrchestrator(ai, cache, settings)

    await orch.fetch_all("What is photosynthesis?")
    report = await orch.fetch_all("what is PHOTOSYNTHESIS")  # different casing

    wiki = next(o for o in report.outcomes if o.name == "wikipedia")
    assert wiki.from_cache
    assert ai.calls.count("wikipedia") == 1     # the network was hit once


async def test_empty_result_is_reported_as_empty(settings, cache):
    orch = _orch(settings, cache, {"wikipedia": [], "arxiv": [], "web": []})
    report = await orch.fetch_all("q")
    assert all(o.status is FetchStatus.EMPTY for o in report.outcomes)
    assert report.sources == []


async def test_sequential_mode_is_slower_than_parallel(settings, cache):
    async def slow(_query):
        await asyncio.sleep(0.08)
        return []

    orch = _orch(settings, cache, {"wikipedia": slow, "arxiv": slow, "web": slow})
    sequential = await orch.fetch_sequential("q")
    parallel = await orch.fetch_all("q")
    assert sequential.wall_ms > parallel.wall_ms

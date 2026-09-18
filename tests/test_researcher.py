"""End-to-end tests of the business logic (still fully offline)."""

from __future__ import annotations

import pytest

from ai.providers.base import ProviderError
from researcher.core.researcher import NoSourcesError, build_researcher
from researcher.models import FetchStatus
from researcher.services.cache import ResearchCache
from researcher.storage.cache_store import InMemoryCacheStore
from researcher.validation import ValidationError

pytestmark = pytest.mark.asyncio


async def test_ask_returns_answer_with_citations(
    make_researcher, wiki_sources, arxiv_sources, web_sources
):
    r = make_researcher({
        "wikipedia": wiki_sources, "arxiv": arxiv_sources, "web": web_sources,
    })
    result = await r.ask("What is photosynthesis?")

    assert result.question == "What is photosynthesis?"
    assert "[1]" in result.answer
    assert [c["index"] for c in result.citations] == [1, 2]
    assert result.citations[0]["url"] == wiki_sources[0].url
    assert not result.degraded


async def test_ask_rejects_invalid_question(make_researcher, wiki_sources):
    r = make_researcher({"wikipedia": wiki_sources})
    with pytest.raises(ValidationError):
        await r.ask("  ")


async def test_ask_raises_when_every_source_fails(make_researcher):
    r = make_researcher({
        "wikipedia": ProviderError("a"),
        "arxiv": ProviderError("b"),
        "web": ProviderError("c"),
    })
    with pytest.raises(NoSourcesError):
        await r.ask("What is photosynthesis?")


async def test_ask_degrades_when_one_source_fails(
    make_researcher, wiki_sources, web_sources
):
    r = make_researcher({
        "wikipedia": wiki_sources,
        "arxiv": ProviderError("arXiv unreachable"),
        "web": web_sources,
    })
    result = await r.ask("What is photosynthesis?")
    assert result.degraded
    assert result.notes and "arxiv" in result.notes[0]
    assert result.answer                      # answer still produced


async def test_ask_restricted_to_subset_of_sources(make_researcher, wiki_sources):
    r = make_researcher({"wikipedia": wiki_sources})
    result = await r.ask("What is photosynthesis?", sources=["wikipedia"])
    statuses = {o.name: o.status for o in result.outcomes}
    assert statuses["web"] is FetchStatus.SKIPPED


async def test_timings_are_recorded(make_researcher, wiki_sources):
    r = make_researcher({"wikipedia": wiki_sources, "arxiv": [], "web": []})
    result = await r.ask("What is photosynthesis?")
    assert result.total_ms > 0
    assert result.fetch_wall_ms > 0
    assert result.speedup >= 1.0 or result.fetch_sequential_ms >= 0


async def test_answer_is_cached_and_llm_called_once(
    make_researcher, wiki_sources, fake_llm
):
    r = make_researcher({"wikipedia": wiki_sources, "arxiv": [], "web": []})
    first = await r.ask("What is photosynthesis?")
    second = await r.ask("what is PHOTOSYNTHESIS")

    assert len(fake_llm.calls) == 1          # second call reused the cache
    assert second.answer_from_cache
    assert second.answer == first.answer
    assert [c["index"] for c in second.citations] == [c["index"] for c in first.citations]


async def test_no_cache_mode_calls_llm_every_time(
    settings, make_researcher, wiki_sources, fake_llm
):
    disabled = ResearchCache(InMemoryCacheStore(), ttl_seconds=60, enabled=False)
    r = make_researcher(
        {"wikipedia": wiki_sources, "arxiv": [], "web": []}, research_cache=disabled
    )
    await r.ask("What is photosynthesis?")
    await r.ask("What is photosynthesis?")
    assert len(fake_llm.calls) == 2


async def test_output_is_sanitised(make_researcher, wiki_sources, fake_llm):
    fake_llm.response = "\x1b[31mDangerous\x1b[0m answer [1]."
    r = make_researcher({"wikipedia": wiki_sources, "arxiv": [], "web": []})
    result = await r.ask("What is photosynthesis?")
    assert "\x1b" not in result.answer
    assert "Dangerous answer" in result.answer


async def test_result_to_dict_shape(make_researcher, wiki_sources):
    r = make_researcher({"wikipedia": wiki_sources, "arxiv": [], "web": []})
    payload = (await r.ask("What is photosynthesis?")).to_dict()
    assert set(payload) >= {
        "question", "answer", "citations", "timings_ms", "sources", "degraded"
    }
    assert set(payload["timings_ms"]) == {
        "fetch_parallel", "fetch_sequential_equivalent", "speedup", "synthesis", "total"
    }


async def test_benchmark_returns_both_reports(make_researcher, wiki_sources):
    r = make_researcher({"wikipedia": wiki_sources, "arxiv": [], "web": []})
    reports = await r.benchmark("What is photosynthesis?")
    assert set(reports) == {"sequential", "parallel"}
    assert reports["parallel"].wall_ms >= 0


async def test_build_researcher_wires_everything(settings, fake_llm):
    r = build_researcher(settings, llm=fake_llm, store=InMemoryCacheStore())
    assert r.settings is settings
    assert r.orchestrator.cache is r.cache

"""Tests for the AI facade: dispatch, retries, and threaded synthesis."""

from __future__ import annotations

import pytest

from ai.providers.base import ProviderError
from researcher.services import ai_service as ai_service_module
from researcher.services.ai_service import AIService

pytestmark = pytest.mark.asyncio


async def test_fetch_dispatches_to_the_right_coroutine(monkeypatch, settings, wiki_sources):
    seen: dict[str, tuple] = {}

    async def fake_wiki(query, *, max_results=3, client=None):
        seen["wikipedia"] = (query, max_results)
        return wiki_sources

    monkeypatch.setattr(ai_service_module, "fetch_wikipedia", fake_wiki)
    service = AIService(settings)
    out = await service.fetch("wikipedia", "photosynthesis")

    assert out == wiki_sources
    assert seen["wikipedia"] == ("photosynthesis", settings.max_results_per_source)


async def test_fetch_rejects_unknown_source(settings):
    with pytest.raises(ValueError, match="unknown source"):
        await AIService(settings).fetch("reddit", "q")


async def test_fetch_retries_transient_provider_errors(monkeypatch, settings, web_sources):
    calls = {"n": 0}

    async def flaky(query, *, max_results=3, client=None, provider=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ProviderError("temporary network glitch")
        return web_sources

    monkeypatch.setattr(ai_service_module, "fetch_web", flaky)
    out = await AIService(settings).fetch("web", "q")

    assert out == web_sources
    assert calls["n"] == 2          # retried exactly once (retry_attempts=2)


async def test_fetch_does_not_retry_missing_api_key(monkeypatch, settings):
    calls = {"n": 0}

    async def no_key(query, *, max_results=3, client=None, provider=None):
        calls["n"] += 1
        raise ProviderError("TAVILY_API_KEY is not set.")

    monkeypatch.setattr(ai_service_module, "fetch_web", no_key)
    with pytest.raises(ProviderError):
        await AIService(settings).fetch("web", "q")
    assert calls["n"] == 1


async def test_synthesize_runs_off_the_event_loop(settings, fake_llm, wiki_sources):
    answer = await AIService(settings, llm=fake_llm).synthesize("Q?", wiki_sources)
    assert answer.question == "Q?"
    assert fake_llm.calls, "the LLM should have been called"


async def test_synthesize_requires_sources(settings, fake_llm):
    with pytest.raises(ValueError):
        await AIService(settings, llm=fake_llm).synthesize("Q?", [])

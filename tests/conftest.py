"""Shared fixtures for Topic 4 smoke tests."""

from __future__ import annotations

from typing import Any

import pytest

from ai.providers.base import LLMProvider
from ai.sources import WebSearchProvider
from ai.schemas import Source


class FakeLLM(LLMProvider):
    """Returns a fixed text response. Records calls for inspection."""

    def __init__(self, response: str | None = None) -> None:
        self.response = response or (
            "Photosynthesis is the process by which plants convert light "
            "energy into chemical energy [1]. The reaction takes place in "
            "the chloroplasts and produces oxygen as a byproduct [2]."
        )
        self.calls: list[str] = []

    def complete(
        self,
        prompt: str,
        *,
        json_schema: dict | None = None,
        max_tokens: int = 1024,
    ) -> str:
        self.calls.append(prompt)
        return self.response


class FakeWebSearch(WebSearchProvider):
    """Returns canned web results without touching the network."""

    def __init__(self, results: list[Source] | None = None) -> None:
        self.results = results or [
            Source(
                title="Photosynthesis — Encyclopedia",
                url="https://example.com/photosynthesis",
                snippet="A biological process used by plants and some bacteria.",
                origin="web",
            )
        ]
        self.calls: list[str] = []

    async def search(
        self,
        query: str,
        *,
        max_results: int = 3,
        client: Any = None,
    ) -> list[Source]:
        self.calls.append(query)
        return self.results[:max_results]


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def fake_web() -> FakeWebSearch:
    return FakeWebSearch()


@pytest.fixture
def sample_sources() -> list[Source]:
    return [
        Source(
            title="Photosynthesis (Wikipedia)",
            url="https://en.wikipedia.org/wiki/Photosynthesis",
            snippet="Photosynthesis is a process used by plants and other organisms "
                    "to convert light energy into chemical energy.",
            origin="wikipedia",
        ),
        Source(
            title="Calvin cycle (Wikipedia)",
            url="https://en.wikipedia.org/wiki/Calvin_cycle",
            snippet="The Calvin cycle is a series of biochemical redox reactions "
                    "in the stroma of chloroplasts.",
            origin="wikipedia",
        ),
    ]


# ===========================================================================
# SE-layer fixtures (added by the student — the fixtures above are provided
# by the instructor and are left untouched).
# ===========================================================================

import asyncio  # noqa: E402
import time  # noqa: E402

from researcher.config import Settings  # noqa: E402
from researcher.core.researcher import Researcher  # noqa: E402
from researcher.concurrency.orchestrator import SourceOrchestrator  # noqa: E402
from researcher.services.ai_service import AIService  # noqa: E402
from researcher.services.cache import ResearchCache  # noqa: E402
from researcher.storage.cache_store import InMemoryCacheStore  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Fast, deterministic settings: no real sleeps, no real filesystem cache."""
    return Settings(
        cache_backend="memory",
        cache_dir=tmp_path / "cache",
        cache_ttl_seconds=60,
        per_source_timeout_seconds=0.5,
        retry_attempts=2,
        retry_initial_delay=0.01,
        retry_max_delay=0.02,
        max_results_per_source=2,
        log_level="WARNING",
    )


@pytest.fixture
def memory_store() -> InMemoryCacheStore:
    return InMemoryCacheStore()


@pytest.fixture
def cache(memory_store, settings) -> ResearchCache:
    return ResearchCache(memory_store, ttl_seconds=settings.cache_ttl_seconds)


class StubAIService(AIService):
    """AIService whose fetchers are scripted per source name.

    `script[name]` may be a list of Source, an Exception to raise, or a float
    (seconds to sleep before returning an empty list — used for timeout tests).
    """

    def __init__(self, settings: Settings, script: dict, llm=None) -> None:
        super().__init__(settings, llm=llm)
        self.script = script
        self.calls: list[str] = []

    async def fetch(self, source, query, *, client=None, max_results=None):
        self.calls.append(source)
        action = self.script.get(source, [])
        if isinstance(action, BaseException):
            raise action
        if isinstance(action, (int, float)):
            await asyncio.sleep(float(action))
            return []
        if callable(action):
            return await action(query)
        return list(action)


@pytest.fixture
def wiki_sources() -> list[Source]:
    return [
        Source(
            title="Photosynthesis",
            url="https://en.wikipedia.org/wiki/Photosynthesis",
            snippet="Plants convert light into chemical energy.",
            origin="wikipedia",
        )
    ]


@pytest.fixture
def arxiv_sources() -> list[Source]:
    return [
        Source(
            title="Attention Is All You Need",
            url="https://arxiv.org/abs/1706.03762",
            snippet="We propose the Transformer architecture.",
            origin="arxiv",
        )
    ]


@pytest.fixture
def web_sources() -> list[Source]:
    return [
        Source(
            title="How plants make food",
            url="https://example.com/plants",
            snippet="Chlorophyll absorbs sunlight.",
            origin="web",
        )
    ]


@pytest.fixture
def make_researcher(settings, cache, fake_llm):
    """Factory: build a Researcher whose fetchers follow a script."""

    def _factory(script: dict, *, custom_settings: Settings | None = None,
                 llm=None, research_cache: ResearchCache | None = None) -> Researcher:
        cfg = custom_settings or settings
        used_cache = research_cache or cache
        ai = StubAIService(cfg, script, llm=llm or fake_llm)
        orch = SourceOrchestrator(ai, used_cache, cfg)
        return Researcher(ai, orch, used_cache, cfg)

    return _factory


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Guarantee no test opens a real connection pool."""
    monkeypatch.setattr(
        SourceOrchestrator, "_new_client", lambda self: None, raising=True
    )

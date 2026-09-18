"""Offline demo mode — `python -m researcher ask "..." --demo`.

Runs the *entire* real pipeline (validation → parallel orchestration →
timeouts → cache → citation rendering) with two things swapped out:

* a templated `DemoLLM` instead of a real provider, and
* canned sources instead of live HTTP.

Useful when there is no API key, no network, or when demoing the project and
you don't want a live API call in front of an audience.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from ai.providers.base import LLMProvider
from ai.schemas import Source

from researcher.config import Settings
from researcher.services.ai_service import AIService

# Simulated per-source latency, so the parallel-vs-sequential difference is
# visible in the demo output rather than being lost in the noise.
_LATENCY = {"wikipedia": 0.30, "arxiv": 0.45, "web": 0.25}


class DemoLLM(LLMProvider):
    """Writes a templated answer that cites the sources it was handed."""

    def complete(self, prompt: str, *, json_schema: dict | None = None,
                 max_tokens: int = 1024) -> str:
        n = len(re.findall(r"^\[(\d+)\]", prompt, re.MULTILINE))
        if n == 0:
            return "Mövcud mənbələr əsasında cavab vermək mümkün deyil."
        cited = ", ".join(f"[{i}]" for i in range(1, min(n, 3) + 1))
        return (
            "Bu, demo rejimində yaradılmış nümunə cavabdır: mənbələr üzrə əsas "
            f"məqamlar {cited} istinadları ilə birləşdirilib. Mənbələr əsas "
            "iddialarda üst-üstə düşür, vurğu fərqləri hər istinadda qeyd olunub [1]."
        )


_CANNED: dict[str, list[Source]] = {
    "wikipedia": [
        Source(
            title="Photosynthesis",
            url="https://en.wikipedia.org/wiki/Photosynthesis",
            snippet="Photosynthesis is a process used by plants and other organisms "
                    "to convert light energy into chemical energy.",
            origin="wikipedia",
        )
    ],
    "arxiv": [
        Source(
            title="Attention Is All You Need",
            url="https://arxiv.org/abs/1706.03762",
            snippet="We propose a new simple network architecture, the Transformer, "
                    "based solely on attention mechanisms.",
            origin="arxiv",
        )
    ],
    "web": [
        Source(
            title="How plants make food",
            url="https://example.com/plants",
            snippet="Plants use chlorophyll to absorb sunlight and produce glucose "
                    "from carbon dioxide and water.",
            origin="web",
        )
    ],
}


class DemoAIService(AIService):
    """AIService that never touches the network."""

    def __init__(self, settings: Settings, *, llm: LLMProvider | None = None) -> None:
        super().__init__(settings, llm=llm or DemoLLM())

    async def fetch(self, source: str, query: str, *, client: Any = None,
                    max_results: int | None = None) -> list[Source]:
        if source not in _CANNED:
            raise ValueError(f"unknown source {source!r}")
        await asyncio.sleep(_LATENCY[source])   # pretend it's a real round-trip
        return list(_CANNED[source])

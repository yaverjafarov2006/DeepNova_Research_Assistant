"""Domain models for the SE layer.

These are *our* models. `ai.Source`, `ai.Citation` and `ai.AnswerWithCitations`
belong to the provided module and are never redefined here — we compose them.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai.schemas import AnswerWithCitations, Source


class FetchStatus(str, Enum):
    """Outcome of a single source fetch."""

    OK = "ok"
    EMPTY = "empty"          # succeeded but returned nothing
    TIMEOUT = "timeout"      # exceeded per-source timeout
    ERROR = "error"          # raised (provider error, HTTP error, bad key…)
    SKIPPED = "skipped"      # disabled via --sources


class SourceFetchOutcome(BaseModel):
    """Per-source result, including timing — this is what the benchmark reads."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: FetchStatus
    count: int = 0
    elapsed_ms: float = 0.0
    from_cache: bool = False
    error: str | None = None
    sources: list[Source] = Field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.status in (FetchStatus.OK, FetchStatus.EMPTY)

    def summary(self) -> str:
        cache = " (cache)" if self.from_cache else ""
        if self.status is FetchStatus.OK:
            return f"{self.name}: {self.count} nəticə, {self.elapsed_ms:.0f} ms{cache}"
        if self.status is FetchStatus.EMPTY:
            return f"{self.name}: nəticə yoxdur, {self.elapsed_ms:.0f} ms{cache}"
        if self.status is FetchStatus.SKIPPED:
            return f"{self.name}: skipped"
        return f"{self.name}: {self.status.value} — {self.error}"


class FetchReport(BaseModel):
    """Everything the orchestrator learned during one parallel fetch round."""

    model_config = ConfigDict(extra="forbid")

    outcomes: list[SourceFetchOutcome] = Field(default_factory=list)
    wall_ms: float = 0.0

    @property
    def sources(self) -> list[Source]:
        """All fetched sources, de-duplicated by URL, in source order."""
        seen: set[str] = set()
        out: list[Source] = []
        for outcome in self.outcomes:
            for src in outcome.sources:
                key = src.url.strip().rstrip("/").lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(src)
        return out

    @property
    def sequential_ms(self) -> float:
        """What the same work would have cost one-after-another."""
        return sum(o.elapsed_ms for o in self.outcomes)

    @property
    def failed(self) -> list[SourceFetchOutcome]:
        return [
            o for o in self.outcomes
            if o.status in (FetchStatus.TIMEOUT, FetchStatus.ERROR)
        ]

    @property
    def degraded(self) -> bool:
        """True when at least one source failed but we still have material."""
        return bool(self.failed) and bool(self.sources)

    def notes(self) -> list[str]:
        """Human-readable degradation notes for the CLI/report."""
        return [
            f"{o.name} mənbəsi əlçatmaz oldu ({o.status.value}): {o.error}"
            for o in self.failed
        ]


class ResearchResult(BaseModel):
    """Final result of one `ask` — answer, citations, and full provenance."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    question: str
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    outcomes: list[SourceFetchOutcome] = Field(default_factory=list)
    fetch_wall_ms: float = 0.0
    fetch_sequential_ms: float = 0.0
    synth_ms: float = 0.0
    total_ms: float = 0.0
    degraded: bool = False
    notes: list[str] = Field(default_factory=list)
    answer_from_cache: bool = False

    @classmethod
    def from_answer(
        cls,
        answer: AnswerWithCitations,
        report: "FetchReport",
        *,
        synth_ms: float,
        total_ms: float,
        answer_from_cache: bool = False,
    ) -> "ResearchResult":
        payload = answer.to_dict()
        return cls(
            question=payload["question"],
            answer=payload["answer"],
            citations=payload["citations"],
            outcomes=report.outcomes,
            fetch_wall_ms=report.wall_ms,
            fetch_sequential_ms=report.sequential_ms,
            synth_ms=synth_ms,
            total_ms=total_ms,
            degraded=report.degraded,
            notes=report.notes(),
            answer_from_cache=answer_from_cache,
        )

    @property
    def speedup(self) -> float:
        """Sequential / parallel wall time for the fetch stage."""
        if self.fetch_wall_ms <= 0:
            return 1.0
        return self.fetch_sequential_ms / self.fetch_wall_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "question": self.question,
            "answer": self.answer,
            "citations": self.citations,
            "degraded": self.degraded,
            "notes": self.notes,
            "timings_ms": {
                "fetch_parallel": round(self.fetch_wall_ms, 1),
                "fetch_sequential_equivalent": round(self.fetch_sequential_ms, 1),
                "speedup": round(self.speedup, 2),
                "synthesis": round(self.synth_ms, 1),
                "total": round(self.total_ms, 1),
            },
            "sources": [
                {
                    "name": o.name,
                    "status": o.status.value,
                    "count": o.count,
                    "elapsed_ms": round(o.elapsed_ms, 1),
                    "from_cache": o.from_cache,
                    "error": o.error,
                }
                for o in self.outcomes
            ],
        }


class Timer:
    """Tiny context manager for wall-clock milliseconds."""

    def __init__(self) -> None:
        self.ms: float = 0.0
        self._start: float = 0.0

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.ms = (time.perf_counter() - self._start) * 1000.0

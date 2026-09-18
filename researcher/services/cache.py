"""TTL-aware cache service keyed by `(source, canonical query)`.

Responsibilities that don't belong in a raw key/value store:

* build the cache key — `v1:<source>:<sha1 of canonical query>`, so
  "WHAT IS PHOTOSYNTHESIS?" and "what is photosynthesis" hit one entry;
* serialise/deserialise `ai.Source` objects to plain JSON;
* count hits/misses so the CLI can report cache effectiveness;
* stay out of the way when caching is disabled (`--no-cache`).
"""

from __future__ import annotations

import hashlib
from typing import Any

from ai.schemas import Source

from researcher.logging_setup import get_logger
from researcher.storage.cache_store import CacheStore
from researcher.validation import canonical_query

logger = get_logger(__name__)

KEY_VERSION = "v1"


def make_key(source: str, query: str, *, extra: str = "") -> str:
    """Deterministic cache key for a (source, query) pair."""
    normalised = canonical_query(query)
    digest = hashlib.sha1(normalised.encode("utf-8")).hexdigest()[:20]
    suffix = f":{extra}" if extra else ""
    return f"{KEY_VERSION}:{source}:{digest}{suffix}"


class ResearchCache:
    """Domain-aware wrapper around a `CacheStore`."""

    def __init__(
        self,
        store: CacheStore,
        *,
        ttl_seconds: int = 86_400,
        enabled: bool = True,
    ) -> None:
        self._store = store
        self._ttl = ttl_seconds
        self.enabled = enabled
        self.hits = 0
        self.misses = 0

    # --- sources ---------------------------------------------------------

    async def get_sources(self, source: str, query: str) -> list[Source] | None:
        if not self.enabled:
            return None
        raw = await self._store.get(make_key(source, query))
        if raw is None:
            self.misses += 1
            return None
        try:
            sources = [Source(**item) for item in raw]
        except Exception as exc:  # stale schema — treat as a miss
            logger.warning("cache payload no longer matches Source schema: %s", exc)
            await self._store.delete(make_key(source, query))
            self.misses += 1
            return None
        self.hits += 1
        logger.debug("cache HIT %s (%d sources)", source, len(sources))
        return sources

    async def set_sources(self, source: str, query: str, sources: list[Source]) -> None:
        if not self.enabled:
            return
        payload: list[dict[str, Any]] = [s.model_dump() for s in sources]
        await self._store.set(make_key(source, query), payload, self._ttl)
        logger.debug("cache STORE %s (%d sources)", source, len(sources))

    # --- synthesized answers --------------------------------------------

    async def get_answer(self, question: str, source_fingerprint: str) -> dict | None:
        if not self.enabled:
            return None
        raw = await self._store.get(make_key("answer", question, extra=source_fingerprint))
        if raw is None:
            self.misses += 1
            return None
        self.hits += 1
        return raw

    async def set_answer(
        self, question: str, source_fingerprint: str, payload: dict
    ) -> None:
        if not self.enabled:
            return
        await self._store.set(
            make_key("answer", question, extra=source_fingerprint), payload, self._ttl
        )

    # --- maintenance -----------------------------------------------------

    async def clear(self) -> int:
        return await self._store.clear()

    async def purge_expired(self) -> int:
        return await self._store.purge_expired()

    @property
    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}

"""Tests for the cache backends and the cache service."""

from __future__ import annotations

import json
import time

import pytest

from ai.schemas import Source
from researcher.services.cache import ResearchCache, make_key
from researcher.storage.cache_store import (
    FileSystemCacheStore,
    InMemoryCacheStore,
    build_cache_store,
)

pytestmark = pytest.mark.asyncio


# --- factory --------------------------------------------------------------

async def test_build_cache_store_selects_backend(tmp_path):
    assert isinstance(build_cache_store("memory"), InMemoryCacheStore)
    assert isinstance(build_cache_store("file", tmp_path), FileSystemCacheStore)
    with pytest.raises(ValueError):
        build_cache_store("postgres")


# --- in-memory store ------------------------------------------------------

async def test_memory_store_roundtrip(memory_store):
    await memory_store.set("k", {"a": 1}, 60)
    assert await memory_store.get("k") == {"a": 1}


async def test_memory_store_missing_key_returns_none(memory_store):
    assert await memory_store.get("nope") is None


async def test_memory_store_respects_ttl(memory_store, monkeypatch):
    await memory_store.set("k", "v", 1)
    future = time.time() + 10_000
    monkeypatch.setattr(time, "time", lambda: future)
    assert await memory_store.get("k") is None


async def test_memory_store_zero_ttl_never_expires(memory_store):
    await memory_store.set("k", "v", 0)
    assert await memory_store.get("k") == "v"


async def test_memory_store_clear_and_delete(memory_store):
    await memory_store.set("a", 1, 60)
    await memory_store.set("b", 2, 60)
    await memory_store.delete("a")
    assert await memory_store.get("a") is None
    assert await memory_store.clear() == 1


async def test_memory_store_purge_expired(memory_store):
    await memory_store.set("fresh", 1, 600)
    await memory_store.set("stale", 2, 600)
    memory_store._data["stale"].expires_at = time.time() - 1
    assert await memory_store.purge_expired() == 1
    assert await memory_store.get("fresh") == 1


# --- filesystem store -----------------------------------------------------

async def test_file_store_roundtrip_and_persistence(tmp_path):
    store = FileSystemCacheStore(tmp_path)
    await store.set("k", ["x"], 60)
    reopened = FileSystemCacheStore(tmp_path)  # simulate a restart
    assert await reopened.get("k") == ["x"]


async def test_file_store_expired_entry_is_removed(tmp_path):
    store = FileSystemCacheStore(tmp_path)
    await store.set("k", "v", 1)
    path = store._path("k")
    payload = json.loads(path.read_text())
    payload["expires_at"] = time.time() - 5
    path.write_text(json.dumps(payload))
    assert await store.get("k") is None
    assert not path.exists()


async def test_file_store_survives_corrupt_file(tmp_path):
    store = FileSystemCacheStore(tmp_path)
    await store.set("k", "v", 60)
    store._path("k").write_text("{not json")
    assert await store.get("k") is None


async def test_file_store_purge_expired(tmp_path):
    store = FileSystemCacheStore(tmp_path)
    await store.set("a", 1, 60)
    await store.set("b", 2, 60)
    p = store._path("b")
    payload = json.loads(p.read_text())
    payload["expires_at"] = time.time() - 5
    p.write_text(json.dumps(payload))
    assert await store.purge_expired() == 1
    assert await store.get("a") == 1


# --- key canonicalisation -------------------------------------------------

async def test_cache_key_is_case_and_space_insensitive():
    assert make_key("web", "WHAT IS PHOTOSYNTHESIS?") == make_key(
        "web", "  what is photosynthesis "
    )


async def test_cache_key_differs_per_source():
    assert make_key("web", "q") != make_key("arxiv", "q")


# --- cache service --------------------------------------------------------

async def test_cache_service_roundtrips_sources(cache, wiki_sources):
    await cache.set_sources("wikipedia", "What is photosynthesis?", wiki_sources)
    got = await cache.get_sources("wikipedia", "what is PHOTOSYNTHESIS")
    assert got is not None
    assert got[0].title == wiki_sources[0].title
    assert isinstance(got[0], Source)
    assert cache.stats["hits"] == 1


async def test_cache_service_counts_misses(cache):
    assert await cache.get_sources("web", "unknown") is None
    assert cache.stats["misses"] == 1


async def test_disabled_cache_never_stores(memory_store, wiki_sources):
    cache = ResearchCache(memory_store, ttl_seconds=60, enabled=False)
    await cache.set_sources("wikipedia", "q", wiki_sources)
    assert await cache.get_sources("wikipedia", "q") is None
    assert await memory_store.get(make_key("wikipedia", "q")) is None


async def test_cache_service_drops_payload_with_stale_schema(cache, memory_store):
    await memory_store.set(
        make_key("web", "q"), [{"title": "t", "url": "u"}], 60  # missing fields
    )
    assert await cache.get_sources("web", "q") is None


async def test_cache_service_answer_roundtrip(cache):
    payload = {"question": "q", "answer": "a [1]", "citations": []}
    await cache.set_answer("q", "fp123", payload)
    assert await cache.get_answer("q", "fp123") == payload
    assert await cache.get_answer("q", "other-fp") is None

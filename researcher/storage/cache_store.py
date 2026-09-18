"""Pluggable cache backends.

`CacheStore` is the contract; two concrete stores ship with the project:

* `InMemoryCacheStore`  — a dict. Fast, per-process, used in tests.
* `FileSystemCacheStore` — one JSON file per key under `CACHE_DIR`. Survives
  restarts, no server to run, easy to inspect while debugging.

The same abstract-base + factory pattern the provided `ai/providers` package
uses, so a PostgreSQL store can be added later without touching callers.

All methods are async: the filesystem store does its blocking I/O in a thread
(`asyncio.to_thread`) so it never stalls the event loop while three source
fetches are in flight.
"""

from __future__ import annotations

import abc
import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from researcher.logging_setup import get_logger

logger = get_logger(__name__)


class CacheEntry:
    """A stored value plus its expiry metadata."""

    __slots__ = ("value", "created_at", "expires_at")

    def __init__(self, value: Any, created_at: float, expires_at: float | None) -> None:
        self.value = value
        self.created_at = created_at
        self.expires_at = expires_at

    def is_expired(self, now: float | None = None) -> bool:
        if self.expires_at is None:
            return False
        return (now if now is not None else time.time()) >= self.expires_at

    def to_json(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "CacheEntry":
        return cls(
            value=payload["value"],
            created_at=float(payload.get("created_at", 0.0)),
            expires_at=(
                None if payload.get("expires_at") is None
                else float(payload["expires_at"])
            ),
        )


class CacheStore(abc.ABC):
    """Contract for TTL-aware key/value stores."""

    @abc.abstractmethod
    async def get(self, key: str) -> Any | None:
        """Return the stored value, or None if missing/expired."""

    @abc.abstractmethod
    async def set(self, key: str, value: Any, ttl_seconds: int | None) -> None:
        """Store a value. `ttl_seconds=None` or 0 means never expire."""

    @abc.abstractmethod
    async def delete(self, key: str) -> None:
        """Remove one key (no error if absent)."""

    @abc.abstractmethod
    async def clear(self) -> int:
        """Drop everything. Returns how many entries were removed."""

    async def purge_expired(self) -> int:
        """Remove expired entries. Returns how many were removed."""
        return 0


class InMemoryCacheStore(CacheStore):
    """Process-local dict store. Nothing survives a restart."""

    def __init__(self) -> None:
        self._data: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            if entry.is_expired():
                self._data.pop(key, None)
                logger.debug("cache entry expired: %s", key)
                return None
            return entry.value

    async def set(self, key: str, value: Any, ttl_seconds: int | None) -> None:
        now = time.time()
        expires = None if not ttl_seconds else now + ttl_seconds
        async with self._lock:
            self._data[key] = CacheEntry(value, now, expires)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)

    async def clear(self) -> int:
        async with self._lock:
            n = len(self._data)
            self._data.clear()
            return n

    async def purge_expired(self) -> int:
        now = time.time()
        async with self._lock:
            stale = [k for k, e in self._data.items() if e.is_expired(now)]
            for k in stale:
                del self._data[k]
            return len(stale)


class FileSystemCacheStore(CacheStore):
    """One JSON file per key, named by a hash of the key.

    The original key is kept inside the file so the directory stays debuggable
    (`cat .cache/<hash>.json | jq .key`).
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self.directory / f"{digest}.json"

    async def get(self, key: str) -> Any | None:
        path = self._path(key)

        def _read() -> Any | None:
            if not path.is_file():
                return None
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                entry = CacheEntry.from_json(payload)
            except (json.JSONDecodeError, KeyError, OSError, ValueError):
                # A corrupt cache file must never break a research call.
                logger.warning("corrupt cache file dropped: %s", path.name)
                path.unlink(missing_ok=True)
                return None
            if entry.is_expired():
                path.unlink(missing_ok=True)
                return None
            return entry.value

        return await asyncio.to_thread(_read)

    async def set(self, key: str, value: Any, ttl_seconds: int | None) -> None:
        path = self._path(key)
        now = time.time()
        payload = {
            "key": key,
            "value": value,
            "created_at": now,
            "expires_at": None if not ttl_seconds else now + ttl_seconds,
        }

        def _write() -> None:
            tmp = path.with_suffix(".tmp")
            try:
                tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                tmp.replace(path)  # atomic — no half-written cache files
            except OSError as exc:
                logger.warning("could not write cache entry %s: %s", path.name, exc)
                tmp.unlink(missing_ok=True)

        await asyncio.to_thread(_write)

    async def delete(self, key: str) -> None:
        path = self._path(key)
        await asyncio.to_thread(lambda: path.unlink(missing_ok=True))

    async def clear(self) -> int:
        def _clear() -> int:
            n = 0
            for f in self.directory.glob("*.json"):
                f.unlink(missing_ok=True)
                n += 1
            return n

        return await asyncio.to_thread(_clear)

    async def purge_expired(self) -> int:
        def _purge() -> int:
            now = time.time()
            n = 0
            for f in self.directory.glob("*.json"):
                try:
                    payload = json.loads(f.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    f.unlink(missing_ok=True)
                    n += 1
                    continue
                expires = payload.get("expires_at")
                if expires is not None and now >= float(expires):
                    f.unlink(missing_ok=True)
                    n += 1
            return n

        return await asyncio.to_thread(_purge)


def build_cache_store(backend: str, directory: str | Path = "./.cache") -> CacheStore:
    """Factory — mirrors `ai.providers.factory.get_llm()`."""
    name = (backend or "").lower().strip()
    if name == "memory":
        return InMemoryCacheStore()
    if name in ("file", "filesystem", "fs", "json"):
        return FileSystemCacheStore(directory)
    raise ValueError(f"Unknown CACHE_BACKEND={backend!r}. Expected memory | file.")

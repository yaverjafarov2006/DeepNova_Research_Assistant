"""Exponential-backoff retry helper for async calls.

Deliberately small and dependency-free so the behaviour is fully deterministic
in tests (`jitter=0.0` makes the delays exact).

    result = await retry_async(
        lambda: fetch_wikipedia(q, client=client),
        attempts=3, initial_delay=0.5, max_delay=8.0,
        retry_on=(ProviderError, httpx.HTTPError),
    )

Design decisions worth defending in the report:

* Only *transient* failures are retried. A missing API key raises
  `ProviderError` too, but retrying it three times just wastes 3.5 seconds —
  `is_permanent()` filters those out.
* Delay grows 0.5s → 1s → 2s → 4s, capped at `max_delay`, with optional
  jitter so parallel retries don't resynchronise into a thundering herd.
"""

from __future__ import annotations

import asyncio
import random
from typing import Awaitable, Callable, Iterable, TypeVar

from researcher.logging_setup import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

# Substrings that mark a failure as configuration-related, not transient.
_PERMANENT_MARKERS = (
    "is not set",
    "package is required",
    "unknown web_search_provider",
    "unknown llm_provider",
    "unsupported image type",
)


def is_permanent(exc: BaseException) -> bool:
    """True when retrying cannot possibly help (bad config, missing package)."""
    message = str(exc).lower()
    return any(marker in message for marker in _PERMANENT_MARKERS)


def backoff_delay(
    attempt: int,
    *,
    initial_delay: float = 0.5,
    max_delay: float = 8.0,
    jitter: float = 0.1,
) -> float:
    """Delay before retry number `attempt` (1-based)."""
    raw = initial_delay * (2 ** (attempt - 1))
    delay = min(raw, max_delay)
    if jitter:
        delay += random.uniform(0, jitter * delay)
    return delay


async def retry_async(
    func: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    initial_delay: float = 0.5,
    max_delay: float = 8.0,
    jitter: float = 0.1,
    retry_on: Iterable[type[BaseException]] = (Exception,),
    label: str = "call",
) -> T:
    """Run `func()`, retrying transient failures with exponential backoff."""
    retry_on_tuple = tuple(retry_on)
    last_exc: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            return await func()
        except asyncio.CancelledError:
            raise  # never swallow cancellation (timeouts rely on it)
        except retry_on_tuple as exc:
            last_exc = exc
            if is_permanent(exc):
                logger.error("%s failed permanently: %s", label, exc)
                raise
            if attempt == attempts:
                logger.error("%s failed after %d attempts: %s", label, attempts, exc)
                raise
            delay = backoff_delay(
                attempt, initial_delay=initial_delay, max_delay=max_delay, jitter=jitter
            )
            logger.warning(
                "%s failed (attempt %d/%d): %s — retrying in %.2fs",
                label, attempt, attempts, exc, delay,
            )
            await asyncio.sleep(delay)

    assert last_exc is not None  # pragma: no cover - unreachable
    raise last_exc

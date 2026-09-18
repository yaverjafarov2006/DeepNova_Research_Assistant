"""Tests for the exponential-backoff retry helper."""

from __future__ import annotations

import asyncio

import pytest

from ai.providers.base import ProviderError
from researcher.services.retry import backoff_delay, is_permanent, retry_async


@pytest.mark.asyncio
async def test_returns_immediately_on_success():
    calls = {"n": 0}

    async def ok():
        calls["n"] += 1
        return "value"

    assert await retry_async(ok, attempts=3, initial_delay=0.001) == "value"
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_retries_until_success():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProviderError("temporary upstream failure")
        return "ok"

    result = await retry_async(
        flaky, attempts=3, initial_delay=0.001, jitter=0.0, retry_on=(ProviderError,)
    )
    assert result == "ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_raises_after_exhausting_attempts():
    calls = {"n": 0}

    async def always_fails():
        calls["n"] += 1
        raise ProviderError("upstream down")

    with pytest.raises(ProviderError):
        await retry_async(
            always_fails, attempts=3, initial_delay=0.001, jitter=0.0,
            retry_on=(ProviderError,),
        )
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_permanent_errors_are_not_retried():
    calls = {"n": 0}

    async def bad_config():
        calls["n"] += 1
        raise ProviderError("TAVILY_API_KEY is not set.")

    with pytest.raises(ProviderError):
        await retry_async(
            bad_config, attempts=5, initial_delay=0.001, retry_on=(ProviderError,)
        )
    assert calls["n"] == 1  # no point retrying a missing key


@pytest.mark.asyncio
async def test_unlisted_exception_propagates_immediately():
    calls = {"n": 0}

    async def wrong_type():
        calls["n"] += 1
        raise KeyError("boom")

    with pytest.raises(KeyError):
        await retry_async(
            wrong_type, attempts=3, initial_delay=0.001, retry_on=(ProviderError,)
        )
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_cancellation_is_never_swallowed():
    async def cancelled():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await retry_async(cancelled, attempts=3, initial_delay=0.001)


def test_backoff_grows_exponentially_and_is_capped():
    assert backoff_delay(1, initial_delay=0.5, jitter=0.0) == 0.5
    assert backoff_delay(2, initial_delay=0.5, jitter=0.0) == 1.0
    assert backoff_delay(3, initial_delay=0.5, jitter=0.0) == 2.0
    assert backoff_delay(9, initial_delay=0.5, max_delay=8.0, jitter=0.0) == 8.0


def test_backoff_jitter_stays_in_bounds():
    for _ in range(20):
        d = backoff_delay(2, initial_delay=1.0, jitter=0.2)
        assert 2.0 <= d <= 2.4


def test_is_permanent_detects_config_errors():
    assert is_permanent(ProviderError("ANTHROPIC_API_KEY is not set."))
    assert not is_permanent(ProviderError("connection reset by peer"))

"""Async Research Assistant — SE layer around the provided `ai/` module.

Layers
------
config        : typed, env-driven settings (pydantic)
models        : domain models (ResearchSession, SourceFetchOutcome, ...)
validation    : input validation + output sanitisation
storage       : cache backends (in-memory / filesystem JSON)
services      : cache service (TTL, canonical keys) + ai_service (retries, logging)
concurrency   : asyncio.gather orchestration with per-source timeouts
core          : business logic (Researcher)
cli           : `python -m researcher ask "..."`
"""

__version__ = "1.0.0"

__all__ = ["__version__"]

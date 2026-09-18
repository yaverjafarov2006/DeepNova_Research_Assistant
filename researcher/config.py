"""Typed, environment-driven configuration.

Everything the SE layer needs to know at runtime lives here. Nothing else in
the codebase reads `os.environ` directly — that keeps the app testable
(a test just builds a `Settings(...)` object) and makes the whole surface of
configurable behaviour visible in one file.

Usage
-----
    from researcher.config import get_settings
    settings = get_settings()          # cached singleton, read from env
    settings = Settings(cache_ttl_seconds=60)   # explicit, e.g. in tests
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv

load_dotenv()

from pydantic import BaseModel, ConfigDict, Field, field_validator

# The three source names the pipeline knows about.
SOURCE_NAMES: tuple[str, ...] = ("wikipedia", "arxiv", "web")

# Short aliases accepted on the CLI (`--sources wiki,arxiv`).
SOURCE_ALIASES: dict[str, str] = {
    "wiki": "wikipedia",
    "wikipedia": "wikipedia",
    "arxiv": "arxiv",
    "papers": "arxiv",
    "web": "web",
    "search": "web",
}


def _load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader (no external dependency).

    Existing environment variables always win — a real shell export must not
    be silently overridden by a stale file.
    """
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or not value.strip() else value.strip()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(float(raw.strip()))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class Settings(BaseModel):
    """All runtime settings, validated at construction time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # --- AI layer -------------------------------------------------------
    llm_provider: Literal["anthropic", "openai", "gemini", "google"] = "anthropic"
    llm_model: str = "claude-sonnet-4-6"
    web_search_provider: Literal["tavily", "serper", "duckduckgo", "ddg"] = "tavily"

    # --- logging --------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = False

    # --- caching --------------------------------------------------------
    cache_backend: Literal["memory", "file"] = "file"
    cache_dir: Path = Path("./.cache")
    cache_ttl_seconds: int = Field(default=86_400, ge=0)
    cache_enabled: bool = True

    # --- concurrency ----------------------------------------------------
    per_source_timeout_seconds: float = Field(default=10.0, gt=0)
    total_timeout_seconds: float = Field(default=45.0, gt=0)
    max_results_per_source: int = Field(default=3, ge=1, le=10)
    enabled_sources: tuple[str, ...] = SOURCE_NAMES

    # --- retries --------------------------------------------------------
    retry_attempts: int = Field(default=3, ge=1, le=10)
    retry_initial_delay: float = Field(default=0.5, gt=0)
    retry_max_delay: float = Field(default=8.0, gt=0)

    # --- validation -----------------------------------------------------
    min_question_length: int = Field(default=5, ge=1)
    max_question_length: int = Field(default=500, ge=10)

    @field_validator("enabled_sources")
    @classmethod
    def _known_sources(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError("enabled_sources must not be empty")
        unknown = [s for s in v if s not in SOURCE_NAMES]
        if unknown:
            raise ValueError(
                f"unknown source(s): {unknown}. Expected any of {list(SOURCE_NAMES)}"
            )
        # Preserve canonical ordering and drop duplicates.
        return tuple(s for s in SOURCE_NAMES if s in v)

    @field_validator("max_question_length")
    @classmethod
    def _max_gt_min(cls, v: int, info) -> int:
        minimum = info.data.get("min_question_length", 5)
        if v <= minimum:
            raise ValueError("max_question_length must be greater than min_question_length")
        return v

    @classmethod
    def from_env(cls, *, dotenv: str | Path | None = ".env") -> "Settings":
        """Build settings from environment variables (and an optional .env)."""
        if dotenv is not None:
            _load_dotenv(dotenv)

        raw_sources = _env_str("ENABLED_SOURCES", ",".join(SOURCE_NAMES))
        sources = parse_sources(raw_sources)

        return cls(
            llm_provider=_env_str("LLM_PROVIDER", "anthropic").lower(),
            llm_model=_env_str("LLM_MODEL", "claude-sonnet-4-6"),
            web_search_provider=_env_str("WEB_SEARCH_PROVIDER", "tavily").lower(),
            log_level=_env_str("LOG_LEVEL", "INFO").upper(),
            log_json=_env_bool("LOG_JSON", False),
            cache_backend=_env_str("CACHE_BACKEND", "file").lower(),
            cache_dir=Path(_env_str("CACHE_DIR", "./.cache")),
            cache_ttl_seconds=_env_int("CACHE_TTL_SECONDS", 86_400),
            cache_enabled=_env_bool("CACHE_ENABLED", True),
            per_source_timeout_seconds=_env_float("PER_SOURCE_TIMEOUT_SECONDS", 10.0),
            total_timeout_seconds=_env_float("TOTAL_TIMEOUT_SECONDS", 45.0),
            max_results_per_source=_env_int("MAX_SOURCES_PER_QUERY", 3),
            enabled_sources=sources,
            retry_attempts=_env_int("RETRY_ATTEMPTS", 3),
            retry_initial_delay=_env_float("RETRY_INITIAL_DELAY", 0.5),
            retry_max_delay=_env_float("RETRY_MAX_DELAY", 8.0),
            min_question_length=_env_int("MIN_QUESTION_LENGTH", 5),
            max_question_length=_env_int("MAX_QUESTION_LENGTH", 500),
        )


def parse_sources(raw: str) -> tuple[str, ...]:
    """Turn `"wiki,arxiv"` into `("wikipedia", "arxiv")`.

    Raises
    ------
    ValueError
        If any token is not a recognised source name or alias.
    """
    tokens = [t.strip().lower() for t in raw.split(",") if t.strip()]
    if not tokens:
        raise ValueError("no sources given")
    resolved: list[str] = []
    for token in tokens:
        if token not in SOURCE_ALIASES:
            raise ValueError(
                f"unknown source {token!r}. Expected any of: "
                f"{', '.join(sorted(set(SOURCE_ALIASES)))}"
            )
        canonical = SOURCE_ALIASES[token]
        if canonical not in resolved:
            resolved.append(canonical)
    return tuple(s for s in SOURCE_NAMES if s in resolved)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton built from the environment."""
    return Settings.from_env()


def reset_settings_cache() -> None:
    """Clear the cached singleton (used by tests)."""
    get_settings.cache_clear()

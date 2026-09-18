"""Tests for settings parsing and input validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from researcher.config import Settings, parse_sources, reset_settings_cache
from researcher.validation import (
    ValidationError,
    canonical_query,
    sanitise_output,
    validate_question,
)


# --- config ---------------------------------------------------------------

def test_parse_sources_expands_aliases():
    assert parse_sources("wiki,arxiv") == ("wikipedia", "arxiv")


def test_parse_sources_dedupes_and_orders():
    assert parse_sources("web,wiki,web") == ("wikipedia", "web")


def test_parse_sources_rejects_unknown():
    with pytest.raises(ValueError, match="unknown source"):
        parse_sources("reddit")


def test_settings_reject_unknown_source():
    with pytest.raises(PydanticValidationError):
        Settings(enabled_sources=("reddit",))


def test_settings_reject_negative_timeout():
    with pytest.raises(PydanticValidationError):
        Settings(per_source_timeout_seconds=0)


def test_settings_are_frozen():
    s = Settings()
    with pytest.raises(Exception):
        s.log_level = "DEBUG"  # type: ignore[misc]


def test_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "120")
    monkeypatch.setenv("ENABLED_SOURCES", "wiki,web")
    monkeypatch.setenv("CACHE_BACKEND", "memory")
    reset_settings_cache()
    s = Settings.from_env(dotenv=None)
    assert s.log_level == "DEBUG"
    assert s.cache_ttl_seconds == 120
    assert s.enabled_sources == ("wikipedia", "web")


def test_settings_from_env_rejects_bad_integer(monkeypatch):
    monkeypatch.setenv("CACHE_TTL_SECONDS", "abc")
    with pytest.raises(ValueError):
        Settings.from_env(dotenv=None)


# --- validation -----------------------------------------------------------

def test_validate_question_trims_and_normalises():
    assert validate_question("  What   is   photosynthesis? ") == "What is photosynthesis?"


def test_validate_question_rejects_empty():
    with pytest.raises(ValidationError):
        validate_question("    ")


def test_validate_question_rejects_too_short():
    with pytest.raises(ValidationError, match="too short"):
        validate_question("hi", min_length=5)


def test_validate_question_rejects_too_long():
    with pytest.raises(ValidationError, match="too long"):
        validate_question("a" * 600, max_length=500)


def test_validate_question_rejects_punctuation_only():
    with pytest.raises(ValidationError):
        validate_question("?!?!?!?!")


def test_validate_question_strips_control_characters():
    assert "\x00" not in validate_question("What is\x00 photosynthesis?")


def test_sanitise_output_strips_ansi():
    assert sanitise_output("\x1b[31mred\x1b[0m text") == "red text"


def test_sanitise_output_truncates():
    out = sanitise_output("x" * 100, max_length=20)
    assert out.endswith("[…truncated]")
    assert len(out) < 60


def test_canonical_query_collapses_case_and_punctuation():
    assert canonical_query("WHAT IS PHOTOSYNTHESIS?") == canonical_query(
        "  what is photosynthesis "
    )

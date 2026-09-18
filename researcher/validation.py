"""Input validation and output sanitisation.

Two jobs:

1. `validate_question` — reject junk before it costs us an LLM call:
   empty, too short, too long, control characters, or no letters/digits at all.
2. `sanitise_output` — strip ANSI escape sequences and control characters from
   model output before it hits a terminal, and collapse runaway whitespace.

Also exposes `canonical_query`, used as the cache key basis: the same question
in different casing/spacing/punctuation must produce one cache entry.
"""

from __future__ import annotations

import re
import unicodedata

# ANSI escape sequences — an LLM echoing terminal escapes into your shell is a
# real (if small) injection surface.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
# C0/C1 control characters, keeping \n and \t.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_WS_RE = re.compile(r"[ \t]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


class ValidationError(ValueError):
    """Raised when user input fails validation. The CLI turns it into exit code 2."""


def validate_question(
    question: str,
    *,
    min_length: int = 5,
    max_length: int = 500,
) -> str:
    """Return the cleaned question, or raise `ValidationError`."""
    if question is None:
        raise ValidationError("Question is missing.")

    cleaned = _CONTROL_RE.sub("", _ANSI_RE.sub("", str(question)))
    cleaned = unicodedata.normalize("NFC", cleaned)
    cleaned = _WS_RE.sub(" ", cleaned).strip()

    if not cleaned:
        raise ValidationError("Question must not be empty.")
    if len(cleaned) < min_length:
        raise ValidationError(
            f"Question is too short ({len(cleaned)} chars); minimum is {min_length}."
        )
    if len(cleaned) > max_length:
        raise ValidationError(
            f"Question is too long ({len(cleaned)} chars); maximum is {max_length}."
        )
    if not any(ch.isalnum() for ch in cleaned):
        raise ValidationError("Question must contain at least one letter or digit.")
    return cleaned


def sanitise_output(text: str, *, max_length: int = 20_000) -> str:
    """Make model output safe to print and bounded in size."""
    if not text:
        return ""
    cleaned = _CONTROL_RE.sub("", _ANSI_RE.sub("", text))
    cleaned = _WS_RE.sub(" ", cleaned)
    cleaned = _MULTI_NEWLINE_RE.sub("\n\n", cleaned).strip()
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip() + " […truncated]"
    return cleaned


def canonical_query(query: str) -> str:
    """Normalise a query so equivalent phrasings share one cache key.

    "WHAT IS PHOTOSYNTHESIS?" and "  what is photosynthesis " collapse to the
    same string.
    """
    text = unicodedata.normalize("NFKC", query or "").casefold().strip()
    text = _PUNCT_RE.sub(" ", text)
    return " ".join(text.split())

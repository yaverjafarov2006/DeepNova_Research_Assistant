"""CLI tests — the whole app driven through `click`, still offline."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from researcher import cli as cli_module
from researcher.cli import cli, render_result
from researcher.config import Settings, reset_settings_cache
from researcher.core.researcher import Researcher
from researcher.concurrency.orchestrator import SourceOrchestrator
from researcher.services.cache import ResearchCache
from researcher.storage.cache_store import InMemoryCacheStore

from conftest import StubAIService


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def patched_cli(monkeypatch, settings, fake_llm, wiki_sources, arxiv_sources):
    """Point the CLI at a scripted, offline Researcher."""
    script = {"wikipedia": wiki_sources, "arxiv": arxiv_sources, "web": []}

    def _build(cfg=None, **kwargs):
        cfg = cfg or settings
        cache = ResearchCache(InMemoryCacheStore(), ttl_seconds=60, enabled=False)
        ai = StubAIService(cfg, script, llm=fake_llm)
        return Researcher(ai, SourceOrchestrator(ai, cache, cfg), cache, cfg)

    monkeypatch.setattr(cli_module, "build_researcher", _build)
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    reset_settings_cache()
    return script


def test_ask_prints_answer_and_references(runner, patched_cli):
    result = runner.invoke(cli, ["ask", "What is photosynthesis?"])
    assert result.exit_code == 0, result.output
    assert "İstinadlar:" in result.output
    assert "en.wikipedia.org" in result.output


def test_ask_json_output_is_valid_json(runner, patched_cli):
    result = runner.invoke(cli, ["ask", "What is photosynthesis?", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["question"] == "What is photosynthesis?"
    assert payload["timings_ms"]["total"] >= 0


def test_ask_rejects_short_question(runner, patched_cli):
    result = runner.invoke(cli, ["ask", "hi"])
    assert result.exit_code == 2


def test_ask_rejects_unknown_source(runner, patched_cli):
    result = runner.invoke(cli, ["ask", "What is photosynthesis?", "--sources", "reddit"])
    assert result.exit_code == 2
    assert "unknown source" in result.output


def test_ask_accepts_source_subset(runner, patched_cli):
    result = runner.invoke(
        cli, ["ask", "What is photosynthesis?", "--sources", "wiki", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    statuses = {s["name"]: s["status"] for s in payload["sources"]}
    assert statuses["arxiv"] == "skipped"


def test_ask_no_cache_flag_runs(runner, patched_cli):
    result = runner.invoke(cli, ["ask", "What is photosynthesis?", "--no-cache"])
    assert result.exit_code == 0


def test_benchmark_command_prints_comparison(runner, patched_cli):
    result = runner.invoke(cli, ["benchmark", "What is photosynthesis?"])
    assert result.exit_code == 0, result.output
    assert "paralel" in result.output


def test_config_command_outputs_json(runner, patched_cli):
    result = runner.invoke(cli, ["config"])
    assert result.exit_code == 0
    assert json.loads(result.output)["cache_backend"] == "memory"


def test_cache_command_shows_info(runner, patched_cli):
    result = runner.invoke(cli, ["cache"])
    assert result.exit_code == 0
    assert "backend" in result.output


def test_cache_command_clear(runner, patched_cli):
    result = runner.invoke(cli, ["cache", "--clear"])
    assert result.exit_code == 0
    assert "silindi" in result.output


def test_help_lists_commands(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    for command in ("ask", "benchmark", "cache", "config"):
        assert command in result.output


@pytest.mark.asyncio
async def test_render_result_includes_degradation_notes(
    make_researcher, wiki_sources
):
    from ai.providers.base import ProviderError

    r = make_researcher({
        "wikipedia": wiki_sources, "arxiv": ProviderError("down"), "web": [],
    })
    result = await r.ask("What is photosynthesis?")
    text = render_result(result, show_timings=True)
    assert "Qeydlər" in text
    assert "Vaxtlar:" in text

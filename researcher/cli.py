"""Command-line interface.

    python -m researcher ask "What is photosynthesis?"
    python -m researcher ask "..." --sources wiki,arxiv --no-cache --json
    python -m researcher benchmark "..."
    python -m researcher cache --clear
    python -m researcher config

Exit codes: 0 success · 1 runtime failure · 2 invalid input · 130 interrupted.
Logs go to stderr, the answer goes to stdout — so `--json | jq` works.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace  # noqa: F401  (kept for future use)

import click

from researcher import __version__
from researcher.config import Settings, get_settings, parse_sources
from researcher.core.researcher import NoSourcesError, build_researcher
from researcher.logging_setup import get_logger, setup_logging
from researcher.models import FetchStatus, ResearchResult
from researcher.storage.cache_store import build_cache_store
from researcher.validation import ValidationError

logger = get_logger(__name__)

EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_INVALID = 2
EXIT_INTERRUPTED = 130


# --- rendering ------------------------------------------------------------

def render_result(result: ResearchResult, *, show_timings: bool) -> str:
    """Human-readable answer + numbered references."""
    lines: list[str] = []
    lines.append(click.style(f"Sual: {result.question}", bold=True))
    lines.append("")
    lines.append(result.answer)
    lines.append("")

    if result.citations:
        lines.append(click.style("İstinadlar:", bold=True))
        for c in result.citations:
            lines.append(f"  [{c['index']}] ({c['origin']}) {c['title']}")
            lines.append(f"      {c['url']}")
    else:
        lines.append(click.style("İstinadlar: yoxdur (model mənbəyə istinad etmədi)", fg="yellow"))

    if result.notes:
        lines.append("")
        lines.append(click.style("Qeydlər (degradasiya):", fg="yellow", bold=True))
        for note in result.notes:
            lines.append(f"  ! {note}")

    if show_timings:
        lines.append("")
        lines.append(click.style("Vaxtlar:", bold=True))
        for o in result.outcomes:
            if o.status is FetchStatus.SKIPPED:
                continue
            lines.append(f"  - {o.summary()}")
        lines.append(
            f"  fetch: {result.fetch_wall_ms:.0f} ms paralel / "
            f"{result.fetch_sequential_ms:.0f} ms ardıcıl ekvivalent "
            f"(×{result.speedup:.2f})"
        )
        lines.append(f"  sintez: {result.synth_ms:.0f} ms")
        lines.append(f"  cəmi:  {result.total_ms:.0f} ms")
        if result.answer_from_cache:
            lines.append("  (cavab keşdən qaytarıldı)")

    return "\n".join(lines)


def _settings_for(
    ctx_sources: str | None,
    no_cache: bool,
    timeout: float | None,
    max_results: int | None,
    log_level: str | None,
) -> Settings:
    """Base settings from env, overridden by CLI flags."""
    base = get_settings()
    overrides: dict = {}
    if ctx_sources:
        overrides["enabled_sources"] = parse_sources(ctx_sources)
    if no_cache:
        overrides["cache_enabled"] = False
    if timeout is not None:
        overrides["per_source_timeout_seconds"] = timeout
    if max_results is not None:
        overrides["max_results_per_source"] = max_results
    if log_level:
        overrides["log_level"] = log_level.upper()
    return base.model_copy(update=overrides) if overrides else base


# --- commands -------------------------------------------------------------

@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="researcher")
def cli() -> None:
    """Async Research Assistant — Wikipedia + arXiv + web, sintez edilmiş cavab."""


@cli.command()
@click.argument("question", required=True)
@click.option(
    "--sources", "-s", default=None,
    help="Yalnız seçilmiş mənbələr: wiki,arxiv,web (default: hamısı).",
)
@click.option("--no-cache", is_flag=True, help="Keşi tamamilə bypass et.")
@click.option(
    "--demo", is_flag=True,
    help="Oflayn demo: API açarı və şəbəkə tələb olunmur (hazır mənbələr + şablon LLM).",
)
@click.option("--json", "as_json", is_flag=True, help="Nəticəni JSON kimi çap et.")
@click.option("--timings/--no-timings", default=True, help="Vaxt ölçmələrini göstər.")
@click.option("--timeout", type=float, default=None, help="Mənbə başına timeout (san).")
@click.option("--max-results", type=int, default=None, help="Mənbə başına nəticə sayı.")
@click.option(
    "--log-level", type=click.Choice(
        ["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False
    ), default=None,
)
def ask(
    question: str,
    sources: str | None,
    no_cache: bool,
    demo: bool,
    as_json: bool,
    timings: bool,
    timeout: float | None,
    max_results: int | None,
    log_level: str | None,
) -> None:
    """Sual ver və istinadlı cavab al."""
    try:
        settings = _settings_for(sources, no_cache, timeout, max_results, log_level)
    except ValueError as exc:
        click.echo(click.style(f"Konfiqurasiya xətası: {exc}", fg="red"), err=True)
        sys.exit(EXIT_INVALID)

    setup_logging(settings.log_level, json_output=settings.log_json, force=True)

    async def _run() -> ResearchResult:
        researcher = build_researcher(
            settings, use_cache=not no_cache, demo=demo
        )
        return await researcher.ask(question)

    try:
        result = asyncio.run(_run())
    except ValidationError as exc:
        click.echo(click.style(f"Yanlış sual: {exc}", fg="red"), err=True)
        sys.exit(EXIT_INVALID)
    except NoSourcesError as exc:
        click.echo(click.style(f"Mənbə tapılmadı: {exc}", fg="red"), err=True)
        sys.exit(EXIT_RUNTIME)
    except KeyboardInterrupt:  # pragma: no cover
        click.echo("Dayandırıldı.", err=True)
        sys.exit(EXIT_INTERRUPTED)
    except Exception as exc:
        logger.exception("research failed")
        click.echo(click.style(f"Xəta: {exc}", fg="red"), err=True)
        sys.exit(EXIT_RUNTIME)

    if as_json:
        click.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        click.echo(render_result(result, show_timings=timings))


@cli.command()
@click.argument("question", required=True)
@click.option("--sources", "-s", default=None, help="Mənbələr: wiki,arxiv,web")
@click.option("--repeat", type=int, default=1, help="Neçə dəfə təkrarlansın.")
@click.option("--demo", is_flag=True, help="Oflayn demo mənbələri ilə işlət.")
def benchmark(question: str, sources: str | None, repeat: int, demo: bool) -> None:
    """Ardıcıl vs paralel mənbə yığımını müqayisə et (keş söndürülür)."""
    settings = _settings_for(sources, True, None, None, "WARNING")
    setup_logging(settings.log_level, force=True)

    async def _run() -> None:
        researcher = build_researcher(settings, use_cache=False, demo=demo)
        seq_total = par_total = 0.0
        for i in range(1, repeat + 1):
            reports = await researcher.benchmark(question)
            seq = reports["sequential"].wall_ms
            par = reports["parallel"].wall_ms
            seq_total += seq
            par_total += par
            click.echo(
                f"run {i}: ardıcıl {seq:8.0f} ms | paralel {par:8.0f} ms "
                f"| sürətlənmə ×{(seq / par if par else 1):.2f}"
            )
        n = max(repeat, 1)
        click.echo(
            click.style(
                f"orta:  ardıcıl {seq_total / n:8.0f} ms | paralel {par_total / n:8.0f} ms "
                f"| sürətlənmə ×{(seq_total / par_total if par_total else 1):.2f}",
                bold=True,
            )
        )

    try:
        asyncio.run(_run())
    except (ValidationError, ValueError) as exc:
        click.echo(click.style(f"Xəta: {exc}", fg="red"), err=True)
        sys.exit(EXIT_INVALID)


@cli.command("cache")
@click.option("--clear", "do_clear", is_flag=True, help="Bütün keşi sil.")
@click.option("--purge", "do_purge", is_flag=True, help="Yalnız vaxtı keçmişləri sil.")
def cache_cmd(do_clear: bool, do_purge: bool) -> None:
    """Keşi idarə et."""
    settings = get_settings()
    setup_logging(settings.log_level, force=True)
    store = build_cache_store(settings.cache_backend, settings.cache_dir)

    async def _run() -> None:
        if do_clear:
            n = await store.clear()
            click.echo(f"{n} keş qeydi silindi.")
        elif do_purge:
            n = await store.purge_expired()
            click.echo(f"{n} vaxtı keçmiş qeyd silindi.")
        else:
            click.echo(f"backend : {settings.cache_backend}")
            click.echo(f"qovluq  : {settings.cache_dir}")
            click.echo(f"TTL     : {settings.cache_ttl_seconds} san")
            click.echo(f"aktivdir: {settings.cache_enabled}")

    asyncio.run(_run())


@cli.command("config")
def config_cmd() -> None:
    """Aktiv konfiqurasiyanı göstər (açarlar göstərilmir)."""
    settings = get_settings()
    payload = settings.model_dump(mode="json")
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:  # pragma: no cover - entry point
    cli()


if __name__ == "__main__":  # pragma: no cover
    main()

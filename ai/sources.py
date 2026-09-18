"""Async source fetchers for the research pipeline.

Three coroutines, all returning `list[Source]`:

  fetch_wikipedia(query)  — Wikipedia REST API (no key)
  fetch_arxiv(query)      — arXiv public Atom API (no key)
  fetch_web(query)        — pluggable web search (Tavily / Serper / DuckDuckGo)

Design notes
------------
- We use `httpx.AsyncClient` because it gives us a single HTTP library that
  works async out of the box. The import is lazy so `import ai` works even
  if httpx is not installed (e.g. running smoke tests offline).

- All three coroutines accept an optional `client` parameter. In production,
  the SE layer should pass a single shared `httpx.AsyncClient` to amortize
  connection setup. In tests, students can pass a fake.

- The web search provider abstraction follows the same pattern as the LLM/VLM
  providers in `ai.providers`. Set `WEB_SEARCH_PROVIDER` env var to pick.
"""

from __future__ import annotations

import abc
import os
import re
import xml.etree.ElementTree as ET
from typing import Any

from ai.providers.base import ProviderError
from ai.schemas import Source


def _selected_sources() -> set[str]:
    raw = os.getenv(
        "DENO_SELECTED_SOURCES",
        "wikipedia,arxiv,web",
    )

    return {
        item.strip().lower()
        for item in raw.split(",")
        if item.strip()
    }


def _source_enabled(source: str) -> bool:
    return source.lower() in _selected_sources()


def _mode_result_limit(default: int) -> int:
    mode = os.getenv(
        "DENO_MODE",
        "auto",
    ).lower()

    if mode == "fast":
        return min(default, 1)

    if mode == "balanced":
        return min(default, 3)

    # auto
    return default

# ---------------------------------------------------------------------------
# httpx is imported lazily so the package stays importable without it.
# ---------------------------------------------------------------------------

def _require_httpx():
    try:
        import httpx  # type: ignore
    except ImportError as e:
        raise ProviderError(
            "The `httpx` package is required for live source fetching. "
            "Install with `pip install httpx`."
        ) from e
    return httpx


# ---------------------------------------------------------------------------
# Wikipedia
# ---------------------------------------------------------------------------

# ============================================================
# WIKIPEDIA
# ============================================================

_WIKI_API_URL = "https://en.wikipedia.org/w/api.php"


async def fetch_wikipedia(
    query: str,
    *,
    max_results: int = 3,
    client: Any = None,
    timeout: float = 10.0,
) -> list[Source]:

    if not _source_enabled("wikipedia"):
        return []

    max_results = _mode_result_limit(max_results)

    if not query.strip():
        return []

    httpx = _require_httpx()

    # Wikimedia requires an identifiable User-Agent.
    # Replace the email below with your own contact email.
    headers = {
        "User-Agent": (
            "DENO-ResearchAssistant/1.0 "
            "(contact: yaver.jafarov@gmail.com)"
        ),
        "Accept": "application/json",
    }

    own_client = client is None

    if own_client:
        client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=headers,
        )

    try:
        # ----------------------------------------------------
        # STEP 1 — Search Wikipedia
        # ----------------------------------------------------

        try:
            search_response = await client.get(
                _WIKI_API_URL,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srlimit": max_results,
                    "srnamespace": 0,
                    "format": "json",
                    "formatversion": 2,
                    "utf8": 1,
                    "maxlag": 5,
                },
                headers=headers,
            )

            search_response.raise_for_status()

        except Exception as e:
            raise ProviderError(
                f"Wikipedia search failed: {e}"
            ) from e

        search_data = search_response.json()

        search_results = (
            search_data
            .get("query", {})
            .get("search", [])
        )

        if not search_results:
            return []

        titles = [
            item["title"]
            for item in search_results
            if item.get("title")
        ]

        if not titles:
            return []

        # ----------------------------------------------------
        # STEP 2 — Fetch summaries for found articles
        # ----------------------------------------------------

        try:
            summary_response = await client.get(
                _WIKI_API_URL,
                params={
                    "action": "query",
                    "prop": "extracts|info",
                    "titles": "|".join(titles),

                    # Return introductory text only
                    "exintro": 1,

                    # Return plain text instead of HTML
                    "explaintext": 1,

                    # Maximum summary length
                    "exchars": 1000,

                    # Give us canonical page URLs
                    "inprop": "url",

                    # Follow redirects
                    "redirects": 1,

                    "format": "json",
                    "formatversion": 2,
                    "utf8": 1,
                    "maxlag": 5,
                },
                headers=headers,
            )

            summary_response.raise_for_status()

        except Exception as e:
            raise ProviderError(
                f"Wikipedia summary failed: {e}"
            ) from e

        summary_data = summary_response.json()

        pages = (
            summary_data
            .get("query", {})
            .get("pages", [])
        )

        sources: list[Source] = []

        for page in pages:
            title = page.get("title", "").strip()

            extract = (
                page.get("extract") or ""
            ).strip()

            if not title or not extract:
                continue

            url = page.get("fullurl")

            if not url:
                safe_title = title.replace(" ", "_")

                url = (
                    "https://en.wikipedia.org/wiki/"
                    + safe_title
                )

            sources.append(
                Source(
                    title=title,
                    url=url,
                    snippet=extract,
                    origin="wikipedia",
                )
            )

        return sources[:max_results]

    finally:
        if own_client:
            await client.aclose()

# ---------------------------------------------------------------------------
# arXiv
# ---------------------------------------------------------------------------

_ARXIV_URL = "http://export.arxiv.org/api/query"
_ATOM_NS = "{http://www.w3.org/2005/Atom}"


async def fetch_arxiv(
    query: str,
    *,
    max_results: int = 3,
    client: Any = None,
    timeout: float = 10.0,
) -> list[Source]:

    if not _source_enabled("arxiv"):
        return []

    max_results = _mode_result_limit(max_results)

    if not query.strip():
        return []
    # buradan aşağı köhnə arxiv kodun davam edir
    httpx = _require_httpx()

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=timeout)
    try:
        try:
            r = await client.get(
                _ARXIV_URL,
                params={
                    "search_query": f"all:{query}",
                    "start": 0,
                    "max_results": max_results,
                    "sortBy": "relevance",
                    "sortOrder": "descending",
                },
            )
            r.raise_for_status()
        except Exception as e:  # pragma: no cover - network path
            raise ProviderError(f"arXiv query failed: {e}") from e

        return _parse_arxiv_atom(r.text)
    finally:
        if own_client:
            await client.aclose()


def _parse_arxiv_atom(xml_text: str) -> list[Source]:
    """Parse arXiv's Atom-format response into `Source` objects."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ProviderError(f"arXiv: malformed XML response: {e}")
    out: list[Source] = []
    for entry in root.findall(f"{_ATOM_NS}entry"):
        title_el = entry.find(f"{_ATOM_NS}title")
        summary_el = entry.find(f"{_ATOM_NS}summary")
        id_el = entry.find(f"{_ATOM_NS}id")
        if title_el is None or summary_el is None or id_el is None:
            continue
        title = re.sub(r"\s+", " ", (title_el.text or "").strip())
        snippet = re.sub(r"\s+", " ", (summary_el.text or "").strip())
        url = (id_el.text or "").strip()
        if not (title and snippet and url):
            continue
        out.append(Source(title=title, url=url, snippet=snippet, origin="arxiv"))
    return out


# ---------------------------------------------------------------------------
# Web search — pluggable provider
# ---------------------------------------------------------------------------

class WebSearchProvider(abc.ABC):
    """Contract for web search providers used by `fetch_web`."""

    @abc.abstractmethod
    async def search(
        self,
        query: str,
        *,
        max_results: int = 3,
        client: Any = None,
    ) -> list[Source]:
        raise NotImplementedError


class TavilyProvider(WebSearchProvider):
    """Tavily search API. Free tier: 1000 req/month. Sign up: tavily.com"""

    URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str | None = None, *, timeout: float = 10.0) -> None:
        self._api_key = api_key or os.getenv("TAVILY_API_KEY")
        if not self._api_key:
            raise ProviderError("TAVILY_API_KEY is not set.")
        self._timeout = timeout

    async def search(
        self,
        query: str,
        *,
        max_results: int = 3,
        client: Any = None,
    ) -> list[Source]:
        httpx = _require_httpx()
        own = client is None
        if own:
            client = httpx.AsyncClient(timeout=self._timeout)
        try:
            try:
                r = await client.post(
                    self.URL,
                    json={
                        "api_key": self._api_key,
                        "query": query,
                        "max_results": max_results,
                    },
                )
                r.raise_for_status()
            except Exception as e:  # pragma: no cover - network path
                raise ProviderError(f"Tavily search failed: {e}") from e
            body = r.json()
            return [
                Source(
                    title=item.get("title", "(untitled)"),
                    url=item.get("url", ""),
                    snippet=item.get("content", "") or item.get("snippet", ""),
                    origin="web",
                )
                for item in (body.get("results") or [])
                if item.get("url")
            ]
        finally:
            if own:
                await client.aclose()


class SerperProvider(WebSearchProvider):
    """Serper.dev (Google search proxy). Free tier: 2500 queries. Sign up: serper.dev"""

    URL = "https://google.serper.dev/search"

    def __init__(self, api_key: str | None = None, *, timeout: float = 10.0) -> None:
        self._api_key = api_key or os.getenv("SERPER_API_KEY")
        if not self._api_key:
            raise ProviderError("SERPER_API_KEY is not set.")
        self._timeout = timeout

    async def search(
        self,
        query: str,
        *,
        max_results: int = 3,
        client: Any = None,
    ) -> list[Source]:
        httpx = _require_httpx()
        own = client is None
        if own:
            client = httpx.AsyncClient(timeout=self._timeout)
        try:
            try:
                r = await client.post(
                    self.URL,
                    headers={"X-API-KEY": self._api_key},
                    json={"q": query, "num": max_results},
                )
                r.raise_for_status()
            except Exception as e:  # pragma: no cover - network path
                raise ProviderError(f"Serper search failed: {e}") from e
            body = r.json()
            return [
                Source(
                    title=item.get("title", "(untitled)"),
                    url=item.get("link", ""),
                    snippet=item.get("snippet", ""),
                    origin="web",
                )
                for item in (body.get("organic") or [])[:max_results]
                if item.get("link")
            ]
        finally:
            if own:
                await client.aclose()


class DuckDuckGoProvider(WebSearchProvider):
    """DuckDuckGo search via the `duckduckgo-search` package. No API key.

    This provider runs the (sync) `duckduckgo-search` library inside a thread
    so it presents the same async interface as the others.
    """

    def __init__(self) -> None:
        try:
            import duckduckgo_search  # type: ignore  # noqa: F401
        except ImportError as e:
            raise ProviderError(
                "The `duckduckgo-search` package is required for DuckDuckGoProvider. "
                "Install with `pip install duckduckgo-search`."
            ) from e

    async def search(
        self,
        query: str,
        *,
        max_results: int = 3,
        client: Any = None,
    ) -> list[Source]:
        # `client` is unused — this provider doesn't speak HTTP directly.
        import asyncio
        from duckduckgo_search import DDGS  # type: ignore

        def _run() -> list[Source]:
            results: list[Source] = []
            with DDGS() as ddgs:
                for item in ddgs.text(query, max_results=max_results):
                    if not item.get("href"):
                        continue
                    results.append(Source(
                        title=item.get("title", "(untitled)"),
                        url=item["href"],
                        snippet=item.get("body", ""),
                        origin="web",
                    ))
            return results

        return await asyncio.to_thread(_run)


def get_web_search_provider() -> WebSearchProvider:
    """Factory: select the configured web-search provider.

    Reads `WEB_SEARCH_PROVIDER` env var. Default: tavily.
    """
    name = os.getenv("WEB_SEARCH_PROVIDER", "tavily").lower().strip()
    if name == "tavily":
        return TavilyProvider()
    if name == "serper":
        return SerperProvider()
    if name in ("duckduckgo", "ddg"):
        return DuckDuckGoProvider()
    raise ProviderError(
        f"Unknown WEB_SEARCH_PROVIDER={name!r}. "
        "Expected tavily | serper | duckduckgo."
    )


async def fetch_web(
    query: str,
    *,
    max_results: int = 3,
    provider: WebSearchProvider | None = None,
    client: Any = None,
) -> list[Source]:
    """Fetch web search results via the configured provider."""

    if not _source_enabled("web"):
        return []

    max_results = _mode_result_limit(max_results)

    if not query.strip():
        return []

    provider = provider or get_web_search_provider()

    return await provider.search(
        query,
        max_results=max_results,
        client=client,
    )

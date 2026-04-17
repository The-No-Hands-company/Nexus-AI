"""
src/agents/tools/web_search.py — Structured web search with citations (stub)

Planned backends: Brave Search API, SerpAPI, DuckDuckGo Instant Answer API.
Returns typed SearchResult objects with URL, title, snippet, and confidence.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str = ""
    confidence: float = 1.0
    published_date: str | None = None


def web_search(
    query: str,
    n_results: int = 5,
    safe_search: bool = True,
    backend: str = "brave",
) -> list[SearchResult]:
    """
    Perform a web search and return cited results.

    STUB: raises NotImplementedError.
    Implementation plan:
    - brave: GET https://api.search.brave.com/res/v1/web/search with API key
    - serpapi: GET https://serpapi.com/search
    - duckduckgo: use duckduckgo_search library (no API key required)
    Each result → SearchResult with url, title, snippet, confidence.
    """
    raise NotImplementedError(
        "web_search is not yet implemented. "
        "Planned: Brave / SerpAPI / DuckDuckGo backend with citation metadata."
    )


def web_search_format(results: list[SearchResult]) -> str:
    """Format a list of SearchResults as a markdown citation list."""
    if not results:
        return "No results found."
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. **{r.title}** — {r.url}")
        if r.snippet:
            lines.append(f"   > {r.snippet}")
    return "\n".join(lines)

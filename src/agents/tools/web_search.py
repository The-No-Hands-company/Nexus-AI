from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str = ""
    confidence: float = 1.0
    published_date: str | None = None


_VALID_BACKENDS = frozenset({"duckduckgo", "brave"})

def web_search(
    query: str,
    n_results: int = 5,
    safe_search: bool = True,
    backend: str = "duckduckgo",
) -> list[SearchResult]:
    if backend not in _VALID_BACKENDS:
        raise ValueError(f"Unsupported search backend: {backend!r} (must be one of {sorted(_VALID_BACKENDS)})")
    if backend == "duckduckgo":
        return _search_duckduckgo(query, n_results)
    return _search_brave(query, n_results)


def _search_duckduckgo(query: str, n_results: int = 5) -> list[SearchResult]:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        raise ImportError(
            "duckduckgo-search is required for web search. "
            "Install with: pip install duckduckgo-search"
        )

    results: list[SearchResult] = []
    try:
        with DDGS() as ddgs:
            for i, r in enumerate(ddgs.text(query, max_results=n_results)):
                results.append(SearchResult(
                    title=r.get("title", ""),
                    url=r.get("href", ""),
                    snippet=r.get("body", ""),
                    source="duckduckgo",
                    confidence=1.0 - (i * 0.05),
                ))
    except Exception:
        logger.warning("web_search.py: duckduckgo search failed: query=%r", query, exc_info=True)

    return results


def _search_brave(query: str, n_results: int = 5) -> list[SearchResult]:
    import os
    import httpx

    api_key = os.environ.get("BRAVE_SEARCH_API_KEY", "")
    if not api_key:
        raise ValueError(
            "BRAVE_SEARCH_API_KEY environment variable is required for Brave Search"
        )

    try:
        response = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": n_results},
            headers={"X-Subscription-Token": api_key},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        results: list[SearchResult] = []
        for i, item in enumerate(data.get("web", {}).get("results", [])):
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("description", ""),
                source="brave",
                confidence=1.0 - (i * 0.05),
            ))
        return results
    except Exception:
        logger.warning("web_search.py: brave search failed: query=%r", query, exc_info=True)
        return []


def web_search_format(results: list[SearchResult]) -> str:
    if not results:
        return "No results found."
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. **{r.title}** \u2014 {r.url}")
        if r.snippet:
            lines.append(f"   > {r.snippet}")
    return "\n".join(lines)

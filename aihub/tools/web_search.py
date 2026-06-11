"""
AIHub Tool: Web search via DuckDuckGo (v0.1.1).
Uses the DuckDuckGo HTML scrape interface — no API key required.
Results are extracted by parsing the HTML response.

Note: the public `duckduckgo.com/html/` host now serves an empty stub page,
so we hit the scrape host `html.duckduckgo.com/html/` and fall back to the
lite host `lite.duckduckgo.com/lite/` if that returns nothing.
"""
import re
import requests
from html import unescape

_DDG_URL = "https://html.duckduckgo.com/html/"
_DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def search_web(query: str, num_results: int = 5) -> str:
    """
    Search the web using DuckDuckGo Lite and return formatted results.

    Args:
        query:       Search query string.
        num_results: Number of results to return (default 5, max 10).

    Returns:
        Formatted string of search results (title, URL, snippet),
        or an error message if the search fails.
    """
    num_results = min(max(1, num_results), 10)

    # Primary: scrape host (returns class="result__a" blocks). If it yields
    # nothing (DDG occasionally serves a stub page), retry the lite host.
    try:
        html = _fetch(_DDG_URL, query)
        results = _parse_ddg_html(html, num_results)
        if not results:
            html = _fetch(_DDG_LITE_URL, query)
            results = _parse_ddg_lite(html, num_results)
    except requests.exceptions.ConnectionError:
        return "[Search Error] No internet connection or DuckDuckGo unavailable."
    except requests.exceptions.Timeout:
        return "[Search Error] Search request timed out."
    except Exception as e:
        return f"[Search Error] Request failed: {e}"

    if not results:
        return f"[Search] No results found for: '{query}'"

    lines = [f"🔍 Web search results for: \"{query}\"\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. **{r['title']}**")
        lines.append(f"   {r['url']}")
        if r["snippet"]:
            lines.append(f"   {r['snippet']}")
        lines.append("")

    return "\n".join(lines).strip()


def _fetch(url: str, query: str) -> str:
    """POST a query to a DuckDuckGo host and return the response body."""
    response = requests.post(
        url,
        data={"q": query, "b": "", "kl": ""},
        headers=_HEADERS,
        timeout=10,
    )
    response.raise_for_status()
    return response.text


def _parse_ddg_html(html: str, limit: int) -> list:
    """
    Parse DuckDuckGo Lite HTML to extract result titles, URLs, and snippets.
    Returns a list of dicts with keys: title, url, snippet.
    """
    from urllib.parse import unquote

    results = []

    # Match individual result blocks. The scrape host uses
    # <a ... class="result__a" href="...">title</a>; hrefs are now direct URLs
    # (older versions wrapped them in a uddg= redirect, still handled below).
    title_pattern  = re.compile(r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL)
    snippet_pattern = re.compile(r'class="result__snippet"[^>]*>(.*?)</(?:span|a)>', re.DOTALL)

    titles   = title_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for i, (url, title) in enumerate(titles):
        if len(results) >= limit:
            break
        snippet = snippets[i] if i < len(snippets) else ""

        # Skip sponsored/ad redirects (duckduckgo.com/y.js?ad_domain=…).
        if "/y.js" in url or "ad_provider=" in url or "ad_domain=" in url:
            continue

        # Extract the real URL from a uddg= redirect if present.
        uddg_match = re.search(r"uddg=([^&]+)", url)
        if uddg_match:
            url = unquote(uddg_match.group(1))

        if not url.startswith("http"):
            continue

        clean_title   = _strip_tags(unescape(title)).strip()
        clean_snippet = _strip_tags(unescape(snippet)).strip()
        if clean_title:
            results.append({
                "title":   clean_title,
                "url":     url,
                "snippet": clean_snippet,
            })

    return results


def _parse_ddg_lite(html: str, limit: int) -> list:
    """
    Parse the DuckDuckGo Lite host, whose markup differs from the scrape host:
    links are `href="..." class='result-link'>title</a>` and snippets live in
    `<td class='result-snippet'>...</td>`. Returns the same list-of-dicts shape.
    """
    results = []
    link_pattern = re.compile(
        r'href="([^"]*)"\s+class=[\'"]result-link[\'"][^>]*>(.*?)</a>', re.DOTALL)
    snippet_pattern = re.compile(
        r'class=[\'"]result-snippet[\'"][^>]*>(.*?)</td>', re.DOTALL)

    links    = link_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for i, (url, title) in enumerate(links[:limit]):
        snippet = snippets[i] if i < len(snippets) else ""
        clean_title   = _strip_tags(unescape(title)).strip()
        clean_snippet = _strip_tags(unescape(snippet)).strip()
        if not url.startswith("http"):
            continue
        if clean_title:
            results.append({
                "title":   clean_title,
                "url":     url,
                "snippet": clean_snippet,
            })
    return results


def _strip_tags(text: str) -> str:
    """Remove HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", text)

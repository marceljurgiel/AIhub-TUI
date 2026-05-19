"""
AIHub Tool: Web search via DuckDuckGo (v0.1.0).
Uses the DuckDuckGo Lite HTML interface — no API key required.
Results are extracted by parsing the HTML response.
"""
import re
import requests
from html import unescape

_DDG_URL = "https://duckduckgo.com/html/"
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

    try:
        response = requests.post(
            _DDG_URL,
            data={"q": query, "b": "", "kl": ""},
            headers=_HEADERS,
            timeout=10,
        )
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        return "[Search Error] No internet connection or DuckDuckGo unavailable."
    except requests.exceptions.Timeout:
        return "[Search Error] Search request timed out."
    except Exception as e:
        return f"[Search Error] Request failed: {e}"

    html = response.text

    # Extract result blocks using regex on DuckDuckGo Lite HTML structure
    # Each result has: class="result__title", class="result__url", class="result__snippet"
    results = _parse_ddg_html(html, num_results)

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


def _parse_ddg_html(html: str, limit: int) -> list:
    """
    Parse DuckDuckGo Lite HTML to extract result titles, URLs, and snippets.
    Returns a list of dicts with keys: title, url, snippet.
    """
    results = []

    # Match individual result blocks
    # DuckDuckGo Lite uses <a class="result__a" href="...">title</a>
    title_pattern  = re.compile(r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL)
    snippet_pattern = re.compile(r'class="result__snippet"[^>]*>(.*?)</(?:span|a)>', re.DOTALL)

    titles   = title_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for i, (url, title) in enumerate(titles[:limit]):
        snippet = snippets[i] if i < len(snippets) else ""

        # Clean up HTML tags and entities
        clean_title   = _strip_tags(unescape(title)).strip()
        clean_snippet = _strip_tags(unescape(snippet)).strip()

        # Skip DDG internal analytics URLs
        if not url or url.startswith("//duckduckgo.com") or "uddg=" not in url:
            # Try to use as-is if it looks like a real URL
            if not url.startswith("http"):
                continue

        # Extract actual URL from DuckDuckGo redirect if present
        uddg_match = re.search(r"uddg=([^&]+)", url)
        if uddg_match:
            from urllib.parse import unquote
            url = unquote(uddg_match.group(1))

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

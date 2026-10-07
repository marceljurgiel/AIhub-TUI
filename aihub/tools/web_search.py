"""
AIHub Tool: web search — no API key required.

1. The `ddgs` metasearch library: rotates across many engines and uses a
   browser-like TLS fingerprint, so it is blocked far less often.
2. Our own scrapers as fallback: DuckDuckGo's html/lite hosts (they answer
   with a bot check after a burst of queries), then Bing, then Brave.
Results are cached for 10 minutes so repeated queries don't hit engines.
"""
import base64
import re
import time

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
    Search the web (ddgs metasearch, then DuckDuckGo / Bing / Brave) and
    return formatted results.

    Args:
        query:       Search query string.
        num_results: Number of results to return (default 5, max 10).

    Returns:
        Formatted string of search results (title, URL, snippet),
        or an error message if the search fails.
    """
    num_results = min(max(1, num_results), 10)
    key = (query.strip().lower(), num_results)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _CACHE_SECS:
        return hit[1]
    out = _search(query, num_results)
    if not out.startswith("[Search Error]"):
        _CACHE[key] = (time.time(), out)
    return out


def _search(query: str, num_results: int) -> str:
    results, source, failures = find(query, num_results)
    if not results:
        if failures:
            return ("[Search Error] Web search is unavailable right now ("
                    + "; ".join(failures) + "). Tell the user the search failed; "
                    "don't answer as if you had searched.")
        return f"[Search] No results found for: '{query}'"

    lines = [f"🔍 Web search results for: \"{query}\" (via {source})\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. **{r['title']}**")
        lines.append(f"   {r['url']}")
        if r["snippet"]:
            lines.append(f"   {r['snippet']}")
        lines.append("")

    return "\n".join(lines).strip()


def find(query: str, num_results: int = 5):
    """(results, source, failures). The ddgs metasearch library first — it
    rotates across many engines and looks like a real browser, so it is
    blocked far less than plain requests. Then our own scrapers: DuckDuckGo
    (answers with a bot check after a burst of queries), Bing, Brave. One
    engine failing never ends the search."""
    failures = []
    try:
        rows = _search_ddgs(query, num_results)
        if rows:
            return rows, "ddgs", failures
        failures.append("ddgs: no results")
    except ImportError:
        failures.append("ddgs not installed")
    except Exception as e:
        failures.append(f"ddgs: {e}")
    try:
        html = _fetch(_DDG_URL, query)
        if _is_challenge(html):
            failures.append("DuckDuckGo: bot check")
        else:
            rows = _parse_ddg_html(html, num_results)
            if not rows:
                html = _fetch(_DDG_LITE_URL, query)
                rows = [] if _is_challenge(html) else _parse_ddg_lite(html, num_results)
            if rows:
                return rows, "DuckDuckGo", failures
            failures.append("DuckDuckGo: no results")
    except requests.exceptions.ConnectionError:
        failures.append("DuckDuckGo: no connection")
    except Exception as e:
        failures.append(f"DuckDuckGo: {e}")
    for name, engine in (("Bing", _search_bing), ("Brave", _search_brave)):
        try:
            rows = engine(query, num_results)
            if rows:
                return rows, name, failures
            failures.append(f"{name}: no results")
        except Exception as e:
            failures.append(f"{name}: {e}")
    return [], "", failures


def _search_ddgs(query: str, limit: int) -> list:
    from ddgs import DDGS          # optional dependency, imported on use
    rows = DDGS(timeout=10).text(query, max_results=limit, backend="auto",
                                 region="wt-wt", safesearch="moderate") or []
    return [{"title": (r.get("title") or "").strip(), "url": r.get("href") or "",
             "snippet": " ".join((r.get("body") or "").split())[:400]}
            for r in rows if r.get("href")][:limit]


_BRAVE_URL = "https://search.brave.com/search"
_BING_URL = "https://www.bing.com/search"
_CACHE: dict = {}
_CACHE_SECS = 600


def _search_bing(query: str, limit: int) -> list:
    r = requests.get(_BING_URL, params={"q": query}, headers=_HEADERS, timeout=15)
    r.raise_for_status()
    return _parse_bing(r.text, limit)


def _bing_target(href: str) -> str:
    """Bing wraps links as /ck/a?…&u=a1<base64url of the target>."""
    href = unescape(href)
    m = re.search(r"[?&]u=a1([\w-]+)", href)
    if not m:
        return href
    raw = m.group(1)
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
    except Exception:
        return href


def _parse_bing(html: str, limit: int) -> list:
    results = []
    for block in html.split('<li class="b_algo"')[1:]:
        block = block[:block.find("</li>")] if "</li>" in block else block[:8000]
        link = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
        if not link:
            continue
        snippet = re.search(r'<div class="b_caption"[^>]*>.*?<p[^>]*>(.*?)</p>', block, re.DOTALL)
        results.append({
            "title": unescape(_strip_tags(link.group(2))).strip(),
            "url": _bing_target(link.group(1)),
            "snippet": unescape(_strip_tags(snippet.group(1))).strip()[:400] if snippet else "",
        })
        if len(results) >= limit:
            break
    return results


def _is_challenge(html: str) -> bool:
    low = html.lower()
    return "bots use duckduckgo too" in low or ("challenge" in low and "result__a" not in low)


def _search_brave(query: str, limit: int) -> list:
    """Brave Search's HTML results page (no API key)."""
    r = requests.get(_BRAVE_URL, params={"q": query, "source": "web"}, headers=_HEADERS, timeout=15)
    r.raise_for_status()
    return _parse_brave(r.text, limit)


def _parse_brave(html: str, limit: int) -> list:
    results = []
    for block in re.split(r'<div class="snippet[^"]*"[^>]*data-type="web"', html)[1:]:
        block = block[:8000]
        link = re.search(r'<a href="(https?://[^"]+)"', block)
        title = re.search(r'class="title[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL)
        snippet = re.search(r'class="(?:content|snippet-description)[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL)
        if not (link and title):
            continue
        text = unescape(_strip_tags(snippet.group(1))).strip() if snippet else ""
        results.append({
            "title": unescape(_strip_tags(title.group(1))).strip(),
            "url": unescape(link.group(1)),
            # Brave prefixes a date ("January 22, 2026 - "); keep it, it helps.
            "snippet": text[:400],
        })
        if len(results) >= limit:
            break
    return results


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

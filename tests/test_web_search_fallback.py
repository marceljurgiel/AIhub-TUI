"""search_web: DuckDuckGo's bot challenge is reported, Brave is the fallback."""
import os

import pytest

from aihub.tools import web_search

REAL_DDGS = web_search._search_ddgs

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "brave_search.html")
BING = os.path.join(os.path.dirname(__file__), "fixtures", "bing_search.html")
CHALLENGE = "<html>Unfortunately, bots use DuckDuckGo too. Please complete the following challenge</html>"


def test_parse_brave_fixture():
    rows = web_search._parse_brave(open(FIX, encoding="utf-8").read(), 5)
    assert len(rows) == 3
    assert rows[0]["url"] == "https://sarahseeksadventure.com/the-ultimate-lisbon-travel-guide/"
    assert "Lisbon Travel Guide" in rows[0]["title"] and rows[0]["snippet"]


@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
    web_search._CACHE.clear()
    # The scraper tests below exercise the fallback chain: ddgs "fails".
    def no_ddgs(q, n):
        raise RuntimeError("offline in tests")
    monkeypatch.setattr(web_search, "_search_ddgs", no_ddgs)


def test_parse_bing_fixture():
    rows = web_search._parse_bing(open(BING, encoding="utf-8").read(), 5)
    assert len(rows) == 3 and rows[0]["url"] == "https://www.lisbon.pl/"
    assert "Lisbon" in rows[0]["title"] and rows[0]["snippet"]


def test_challenge_falls_back_to_bing_then_brave(monkeypatch):
    monkeypatch.setattr(web_search, "_fetch", lambda url, q: CHALLENGE)
    monkeypatch.setattr(web_search, "_search_bing", lambda q, n: web_search._parse_bing(open(BING, encoding="utf-8").read(), n))
    assert "lisbon.pl" in web_search.search_web("lisbon", 2)
    web_search._CACHE.clear()

    def bing_429(q, n):
        raise RuntimeError("429 Too Many Requests")
    monkeypatch.setattr(web_search, "_search_bing", bing_429)
    monkeypatch.setattr(web_search, "_search_brave", lambda q, n: web_search._parse_brave(open(FIX, encoding="utf-8").read(), n))
    out = web_search.search_web("lisbon", 2)
    assert "sarahseeksadventure.com" in out and out.count("\n1. ") + out.count("\n2. ") == 2


def test_challenge_and_no_fallback_is_an_error_not_no_results(monkeypatch):
    monkeypatch.setattr(web_search, "_fetch", lambda url, q: CHALLENGE)
    monkeypatch.setattr(web_search, "_search_bing", lambda q, n: [])
    monkeypatch.setattr(web_search, "_search_brave", lambda q, n: [])
    out = web_search.search_web("lisbon")
    assert out.startswith("[Search Error]") and "bot check" in out and "ddgs" in out


def test_results_are_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(web_search, "_search", lambda q, n: calls.append(q) or "ok results")
    web_search.search_web("Lisbon", 3)
    web_search.search_web("lisbon ", 3)
    assert calls == ["Lisbon"]


def test_ddgs_first(monkeypatch):
    class FakeDDGS:
        def __init__(self, timeout=None):
            pass

        def text(self, query, **kw):
            assert kw["backend"] == "auto" and kw["max_results"] == 2
            return [{"title": "AccuWeather Lisbon", "href": "https://accuweather.com/t", "body": "Sunny  tomorrow"}]

    import sys, types
    monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=FakeDDGS))
    monkeypatch.setattr(web_search, "_search_ddgs", REAL_DDGS)
    monkeypatch.setattr(web_search, "_fetch", lambda *a: pytest.fail("scrapers must not run"))
    out = web_search.search_web("lisbon weather", 2)
    assert "(via ddgs)" in out and "https://accuweather.com/t" in out and "Sunny tomorrow" in out


def test_ddgs_missing_falls_back(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "ddgs", None)            # import → ImportError
    monkeypatch.setattr(web_search, "_search_ddgs", REAL_DDGS)
    monkeypatch.setattr(web_search, "_fetch", lambda url, q: CHALLENGE)
    monkeypatch.setattr(web_search, "_search_bing", lambda q, n: web_search._parse_bing(open(BING, encoding="utf-8").read(), n))
    out = web_search.search_web("lisbon", 2)
    assert "(via Bing)" in out


def test_search_check(monkeypatch):
    from aihub import bridge
    monkeypatch.setattr(web_search, "find", lambda q, n: ([{"title": "t", "url": "u", "snippet": ""}], "ddgs", []))
    out = bridge._h_search_check({"query": "x"})
    assert out["ok"] and out["source"] == "ddgs" and out["count"] == 1

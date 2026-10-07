"""Ollama Cloud models: tags, free/paid/retired status, friendly errors."""
import json
import os
import shutil

import pytest

from aihub import bridge, ollama_cloud as oc
from aihub.chat import Error, run_chat_turn

from .conftest import FakeBackend


@pytest.fixture(autouse=True)
def clean_cache():
    for f in ("cloud_access.json", "cloud_tags.json"):
        try:
            os.remove(oc._cache_path(f))
        except FileNotFoundError:
            pass
    yield


def test_is_cloud():
    assert oc.is_cloud("kimi-k2.6:cloud") and oc.is_cloud("gpt-oss:120b-cloud")
    assert not oc.is_cloud("qwen3:8b") and not oc.is_cloud("cloud") and not oc.is_cloud("cloudy:7b")


@pytest.mark.parametrize("err,status,words", [
    ("this model is not included in your free usage, add usage credits", "paid", "free cloud plan"),
    ("glm-4.7 was retired at 2026-07-15 00:00:00 -0700 PDT", "retired", "retired glm-4.7:cloud on 2026-07-15"),
    ("429 Too Many Requests: usage limit reached", "limit", "usage limit"),
    ("401 unauthorized", "signin", "ollama signin"),
])
def test_classify_and_explain(err, status, words):
    assert oc.classify(err) == status
    assert words in oc.explain(err, "glm-4.7:cloud")


def test_parse_cloud_tags():
    page = "gpt-oss:20b-cloud ... gpt-oss:120b-cloud ... gpt-oss:20b ... gpt-oss:120b-cloud"
    assert oc.parse_cloud_tags(page, "gpt-oss") == ["gpt-oss:120b-cloud", "gpt-oss:20b-cloud"]


class Resp:
    def __init__(self, data, text=""):
        self.data, self.text = data, text or json.dumps(data)
        self.content = self.text.encode()

    def json(self):
        return self.data


def test_probe_records_status_and_listing_orders_free_first(monkeypatch):
    replies = {"gpt-oss:20b-cloud": {"message": {"content": "o"}},
               "kimi-k2.6:cloud": {"error": "this model is not included in your free usage"},
               "glm-4.7:cloud": {"error": "glm-4.7 was retired at 2026-07-15"}}
    monkeypatch.setattr(oc.requests, "post", lambda url, json=None, timeout=None: Resp(replies[json["model"]]))
    monkeypatch.setattr(oc, "cloud_tags", lambda force=False: [
        {"name": "kimi-k2.6:cloud", "family": "kimi-k2.6", "description": "", "capabilities": [], "updated": "", "pulls": 0},
        {"name": "gpt-oss:20b-cloud", "family": "gpt-oss", "description": "", "capabilities": ["tools"], "updated": "", "pulls": 0},
        {"name": "minimax-m3:cloud", "family": "minimax-m3", "description": "", "capabilities": [], "updated": "", "pulls": 0}])
    assert [oc.probe(t)["status"] for t in replies] == ["free", "paid", "retired"]
    rows = oc.listing(installed=["glm-4.7:cloud", "qwen3:8b"])
    assert [(r["name"], r["status"]) for r in rows] == [
        ("gpt-oss:20b-cloud", "free"), ("minimax-m3:cloud", ""), ("kimi-k2.6:cloud", "paid"), ("glm-4.7:cloud", "retired")]
    assert next(r for r in rows if r["name"] == "glm-4.7:cloud")["installed"]


def test_a_usage_limit_does_not_overwrite_a_known_status(monkeypatch):
    seq = iter([{"message": {}}, {"error": "429 usage limit"}])
    monkeypatch.setattr(oc.requests, "post", lambda url, json=None, timeout=None: Resp(next(seq)))
    oc.probe("gpt-oss:20b-cloud")
    assert oc.probe("gpt-oss:20b-cloud")["status"] == "limit"
    assert oc.statuses()["gpt-oss:20b-cloud"]["status"] == "free"


def test_chat_error_is_explained_and_remembered():
    backend = FakeBackend([[{"error": "403: this model is not included in your free usage, add usage credits"}]])
    events = list(run_chat_turn("kimi-k2.6:cloud", [{"role": "user", "content": "hi"}], stream_fn=backend))
    err = next(e for e in events if isinstance(e, Error))
    assert "isn't in Ollama's free cloud plan" in err.message
    assert oc.statuses()["kimi-k2.6:cloud"]["status"] == "paid"


def test_local_errors_untouched():
    backend = FakeBackend([[{"error": "model 'x' not found"}]])
    events = list(run_chat_turn("x:7b", [{"role": "user", "content": "hi"}], stream_fn=backend))
    assert next(e for e in events if isinstance(e, Error)).message == "API error: model 'x' not found"


def test_cloud_context_and_no_speed_sample(monkeypatch):
    from aihub.hardware import recommend_context
    assert recommend_context("gpt-oss:120b-cloud", hard_cap=131072) == 65536
    monkeypatch.setattr("aihub.ollama_client.get_running_models", lambda: pytest.fail("must not look"))
    bridge._record_speed("gpt-oss:120b-cloud", 50.0)


def test_bridge_handlers(monkeypatch):
    monkeypatch.setattr("aihub.ollama_client.get_local_models", lambda: ["kimi-k2.5:cloud", "qwen3:8b"])
    monkeypatch.setattr("aihub.ollama_client.get_local_model_sizes", lambda: {"qwen3:8b": 4.9})
    monkeypatch.setattr(oc, "cloud_tags", lambda force=False: [])
    inst = bridge._h_models_installed({})["models"]
    assert [m["cloud"] for m in inst] == [True, False]
    assert bridge._h_cloud_models({})["models"][0]["name"] == "kimi-k2.5:cloud"
    monkeypatch.setattr(oc, "probe", lambda t: {"name": t, "status": "free", "detail": ""})
    assert bridge._h_cloud_probe({"names": ["a:cloud"]})["results"][0]["status"] == "free"


def test_model_card_and_params(monkeypatch):
    from aihub import ollama_client as oc2
    oc2._CARD_CACHE.clear()

    class R:
        def raise_for_status(self):
            pass
        def json(self):
            return {"capabilities": ["completion", "vision", "tools"], "details": {"parameter_size": "550000000000", "quantization_level": ""},
                    "model_info": {"x.context_length": 262144}}
    monkeypatch.setattr(oc2.requests, "post", lambda *a, **k: R())
    card = oc2.model_card("m:cloud")
    assert card == {"capabilities": ["vision", "tools"], "max_context": 262144, "params": "550B", "quant": ""}
    assert [oc2._human_params(x) for x in ("8.2B", "999.89M", "11.9B", "")] == ["8.2B", "1B", "12B", ""]

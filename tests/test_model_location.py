"""Where the current model runs, as Ollama's /api/ps reports it — on this
computer or on a server elsewhere on the network."""
import pytest

from aihub import bridge, ollama_client as oc

GIB = 1024 ** 3


class Resp:
    def __init__(self, models):
        self._models = models

    def raise_for_status(self):
        pass

    def json(self):
        return {"models": self._models}


def serve(monkeypatch, models):
    seen = []

    def get(url, timeout=None):
        seen.append(url)
        return Resp(models)

    monkeypatch.setattr(oc.requests, "get", get)
    return seen


def loaded(name, size_gb, vram_gb):
    return {"name": name, "model": name, "size": int(size_gb * GIB), "size_vram": int(vram_gb * GIB)}


def test_whole_model_on_the_gpu(monkeypatch):
    seen = serve(monkeypatch, [loaded("qwen3.5:9b", 6.0, 6.0)])
    loc = oc.model_location("qwen3.5:9b")
    assert loc["state"] == "gpu"
    assert loc["gpu_fraction"] == 1.0
    assert loc["vram_gb"] == pytest.approx(6.0)
    assert seen and seen[0].endswith("/api/ps")


def test_split_between_gpu_and_cpu(monkeypatch):
    serve(monkeypatch, [loaded("gemma-4-12b:latest", 10.0, 6.2)])
    loc = oc.model_location("gemma-4-12b:latest")
    assert loc["state"] == "split"
    assert loc["gpu_fraction"] == pytest.approx(0.62)


def test_all_on_the_cpu(monkeypatch):
    serve(monkeypatch, [loaded("llama3.2:3b", 2.0, 0)])
    assert oc.model_location("llama3.2:3b")["state"] == "cpu"


def test_not_loaded_right_now(monkeypatch):
    serve(monkeypatch, [])
    assert oc.model_location("llama3.2:3b") == {"state": "unloaded"}


def test_another_tag_of_the_same_family_is_not_this_model(monkeypatch):
    serve(monkeypatch, [loaded("qwen3:8b", 5.0, 5.0)])
    assert oc.model_location("qwen3:4b") == {"state": "unloaded"}
    assert oc.model_placement("qwen3:4b") == {}


def test_a_bare_name_means_latest(monkeypatch):
    serve(monkeypatch, [loaded("embeddinggemma:latest", 0.6, 0.6)])
    assert oc.model_location("embeddinggemma")["state"] == "gpu"


def test_unreachable_server_is_not_unloaded(monkeypatch):
    def down(url, timeout=None):
        raise oc.requests.ConnectionError("no route to host")

    monkeypatch.setattr(oc.requests, "get", down)
    assert oc.model_location("llama3.2:3b") == {"state": "offline"}


def test_cloud_models_run_on_ollama_com_without_asking_the_server(monkeypatch):
    seen = serve(monkeypatch, [])
    assert oc.model_location("nemotron-3-ultra:cloud") == {"state": "cloud"}
    assert oc.model_location("gpt-oss:120b-cloud") == {"state": "cloud"}
    assert seen == []


def test_bridge_handler(monkeypatch):
    serve(monkeypatch, [loaded("llama3.2:3b", 2.0, 2.0)])
    assert bridge._ONESHOT["models.location"]({"model": "llama3.2:3b"})["state"] == "gpu"
    assert bridge._ONESHOT["models.location"]({"model": ""}) == {"state": "unknown"}

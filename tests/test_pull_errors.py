"""Pulling a model: Ollama's errors, said so a person knows what to do.
412 is the registry refusing an Ollama too old for the model."""
import requests

from aihub import ollama_client as oc
from aihub.config import config

OLD_OLLAMA = ("pull model manifest: 412: \n\nThe model you are attempting to pull requires a newer "
              "version of Ollama.\n\nPlease download the latest version at:\n\n\thttps://ollama.com/download\n\n")


class Stream:
    def __init__(self, lines, status=200):
        self.lines, self.status_code = lines, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error: Precondition Failed for url: x", response=self)

    def iter_lines(self):
        yield from self.lines


class Version:
    def __init__(self, v):
        self.v = v

    def raise_for_status(self):
        pass

    def json(self):
        return {"version": self.v}


def serve(monkeypatch, stream):
    monkeypatch.setattr(config, "ollama_api_url", "http://gpu-box.lan:11434")
    monkeypatch.setattr(oc.requests, "post", lambda *a, **k: stream)
    monkeypatch.setattr(oc.requests, "get", lambda url, **k: Version("0.30.7"))


def test_a_model_too_new_for_the_server_says_update_ollama(monkeypatch):
    serve(monkeypatch, Stream([b'{"status":"pulling manifest"}', ('{"error": %s}' % repr(OLD_OLLAMA).replace("'", '"')).encode()]))
    events = list(oc.pull_model_stream("granite4.1:8b"))
    err = events[-1]["error"]
    assert "granite4.1:8b needs a newer Ollama" in err
    assert "0.30.7" in err and "gpu-box.lan" in err
    assert "412" not in err and "\n" not in err


def test_the_same_when_ollama_answers_412_as_a_status(monkeypatch):
    serve(monkeypatch, Stream([], status=412))
    err = list(oc.pull_model_stream("granite4.1:8b"))[-1]["error"]
    assert "needs a newer Ollama" in err and "0.30.7" in err


def test_other_errors_are_whole_but_one_line(monkeypatch):
    serve(monkeypatch, Stream([b'{"error":"pull model manifest: file does not exist\\n\\nCheck the name."}']))
    err = list(oc.pull_model_stream("nosuch:1b"))[-1]["error"]
    assert err == "pull model manifest: file does not exist Check the name."

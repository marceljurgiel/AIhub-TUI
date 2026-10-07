"""Image attachments: normalising, clipboard, paste detection, per-backend
formats, the vision gate, and that the UI/history only ever see ids."""
import base64
import io
import json
import os
import shutil
import sys

import pytest
from PIL import Image

from aihub import attachments as att, bridge
from aihub.api_client import _google_stream
from aihub.ollama_client import _ollama_messages
from aihub.openai_format import to_openai_messages

from .conftest import FakeBackend, text


@pytest.fixture(autouse=True)
def clean():
    shutil.rmtree(att.att_dir(), ignore_errors=True)
    att._VISION_CACHE.clear()
    yield
    shutil.rmtree(att.att_dir(), ignore_errors=True)


def png_bytes(w=40, h=30, mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, (w, h), (200, 30, 30, 128) if mode == "RGBA" else (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def test_add_bytes_normalises_and_dedupes():
    a = att.add_bytes(png_bytes(4000, 2000), "big.png")
    assert (a["width"], a["height"]) == (1568, 784) and a["id"].endswith(".jpg")
    assert att.add_bytes(png_bytes(4000, 2000), "again.png")["id"] == a["id"]   # content-addressed
    t = att.add_bytes(png_bytes(10, 10, "RGBA"), "alpha.png")
    assert t["id"].endswith(".png")                                       # keeps transparency
    with pytest.raises(ValueError, match="isn't an image"):
        att.add_bytes(b"not an image", "x.png")


def test_add_file_accepts_drag_and_drop_forms(tmp_path):
    p = tmp_path / "my photo.png"
    p.write_bytes(png_bytes())
    forms = [str(p), f"'{p}'", p.as_uri()]
    if os.name != "nt":
        forms.append(str(p).replace(" ", "\\ "))          # shell-escaped (POSIX terminals)
    for form in forms:
        assert att.add_file(form)["name"] == "my photo.png"
    assert att.looks_like_image_path(p.as_uri())
    assert not att.looks_like_image_path(str(tmp_path / "nope.png"))
    assert not att.looks_like_image_path("just some text.png please")


@pytest.mark.skipif(sys.platform == "win32", reason="Linux clipboard tools")
def test_clipboard_image(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(att.shutil, "which", lambda c: "/usr/bin/" + c)
    calls = []

    def run(cmd):
        calls.append(cmd)
        return b"text/plain\nimage/png\n" if "--list-types" in cmd else png_bytes()
    monkeypatch.setattr(att, "_run", run)
    a = att.add_clipboard()
    assert a["name"] == "clipboard.png" and ["wl-paste", "--type", "image/png"] in calls
    monkeypatch.setattr(att, "_run", lambda cmd: b"text/plain\n")
    with pytest.raises(ValueError, match="no image"):
        att.add_clipboard()


def test_expand_and_restore_keep_ids_outside_the_request():
    a = att.add_bytes(png_bytes(), "a.png")
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "what is it?", "images": [a["id"]]}]
    wire, orig = att.expand(msgs)
    img = wire[1]["images"][0]
    assert img["mime"] == "image/jpeg" and base64.b64decode(img["data"])[:2] == b"\xff\xd8"
    assert wire[0] is msgs[0]
    back = att.restore(wire + [{"role": "assistant", "content": "a red box"}], orig)
    assert back[1] is msgs[1] and back[1]["images"] == [a["id"]] and back[-1]["content"] == "a red box"


def test_missing_attachment_is_said_not_sent():
    wire, _ = att.expand([{"role": "user", "content": "look", "images": ["0123456789ab.jpg"]}])
    assert "images" not in wire[0] and "[image no longer available]" in wire[0]["content"]


def _expanded():
    a = att.add_bytes(png_bytes(), "a.png")
    return att.expand([{"role": "user", "content": "describe", "images": [a["id"]]}])[0][0]


def test_backend_formats():
    m = _expanded()
    data = m["images"][0]["data"]
    assert _ollama_messages([m])[0]["images"] == [data]
    oa = to_openai_messages([m])[0]["content"]
    assert oa[0] == {"type": "text", "text": "describe"}
    assert oa[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_anthropic_and_google_blocks(monkeypatch):
    m = _expanded()
    sent = {}
    from aihub import api_client
    monkeypatch.setattr(api_client.config, "google_api_key", "k")

    class R:
        ok = True
        status_code = 200
        def iter_lines(self, decode_unicode=True):
            return iter([])
        def close(self):
            pass
    monkeypatch.setattr(api_client.requests, "post", lambda url, **kw: sent.update(kw["json"]) or R())
    list(_google_stream("gemini-x", [m], 0.5))
    parts = sent["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "image/jpeg" and parts[1] == {"text": "describe"}


def test_api_registry_marks_vision():
    from aihub.api_models import _sees_images
    assert _sees_images("anthropic", "claude-haiku-4-5") and _sees_images("openai", "gpt-4o")
    assert not _sees_images("openai", "o1-mini")


def _turn(monkeypatch, messages, vision):
    monkeypatch.setattr(att, "supports_vision", lambda m, b="ollama": vision)
    monkeypatch.setattr("aihub.ollama_client.get_local_models", lambda: ["gemma4:cloud", "lfm2.5:8b"])
    seen, events = {}, []

    def stream(model, msgs, temperature, context_length=None, tools=None):
        seen["msgs"] = msgs
        return FakeBackend([[text("a red box")]])(model, msgs, temperature)
    monkeypatch.setattr(bridge, "_resolve_stream_fn", lambda m, b: stream)
    monkeypatch.setattr(bridge, "_emit", lambda rid, e, d=None: events.append((e, d)))
    done = {}
    monkeypatch.setattr(bridge, "_done", lambda rid, d=None: done.update(d or {}))
    bridge._stream_chat_turn(1, {"model": "m", "messages": messages, "tools_enabled": False})
    return seen, events, done


def test_turn_sends_image_data_but_returns_ids(monkeypatch):
    a = att.add_bytes(png_bytes(), "a.png")
    seen, events, done = _turn(monkeypatch, [{"role": "user", "content": "what?", "images": [a["id"]]}], True)
    sent_user = next(m for m in seen["msgs"] if m["role"] == "user")
    assert isinstance(sent_user["images"][0], dict)
    assert done["messages"][-2]["images"] == [a["id"]]                     # ids back to the UI
    convo = [m for m in done["messages"] if m["role"] != "system"]
    assert "base64" not in json.dumps(convo) and len(json.dumps(convo)) < 500


def test_non_vision_model_is_refused_with_alternatives(monkeypatch):
    a = att.add_bytes(png_bytes(), "a.png")
    monkeypatch.setattr(att, "vision_models", lambda installed: ["gemma4:cloud"])
    seen, events, done = _turn(monkeypatch, [{"role": "user", "content": "what?", "images": [a["id"]]}], False)
    assert "msgs" not in seen                                                # nothing sent
    err = next(d["message"] for e, d in events if e == "chat_error")
    assert "can't read images" in err and "gemma4:cloud" in err


def test_paste_handler(tmp_path):
    p1, p2 = tmp_path / "a.png", tmp_path / "b.jpg"
    p1.write_bytes(png_bytes()); p2.write_bytes(png_bytes())
    assert len(bridge._h_attach_paste({"text": f"'{p1}' '{p2}'"})["attachments"]) == 2
    assert bridge._h_attach_paste({"text": f"look at {p1}"})["attachments"] == []
    assert bridge._h_attach_paste({"text": "hello"})["attachments"] == []

"""Knowledge bases, review fixes: one commit point for the index, a lock
shared with other AIhub windows, files outside the chosen folder, work kept
when a build stops halfway, excerpts framed as data, and file encodings."""
import json
import os
import subprocess
import sys
import threading
import time
import zipfile

import numpy as np
import pytest

from aihub import knowledge as kb
from tests.test_knowledge import fake_embed


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(kb, "CONFIG_DIR", str(tmp_path / "aihub"))
    monkeypatch.setattr(kb, "embed", fake_embed)
    kb._cache.clear()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("alpha alpha alpha: the boiler pressure is 1.5 bar.")
    (docs / "b.md").write_text("bravo bravo bravo: the tomatoes need water in July.")
    kb.create("home")
    kb.add("home", [str(docs)])
    return docs


def top(query):
    return kb.search("home", query, 1)[0]["text"]


def test_vectors_and_text_are_one_file(base):
    files = set(os.listdir(kb.base_dir("home")))
    assert "index.npz" in files and not {"vectors.npy", "chunks.jsonl"} & files


def test_a_failed_write_leaves_the_old_index_whole(base, monkeypatch):
    (base / "a.md").write_text("alpha changed: the boiler pressure is now 1.7 bar, and more words here.")
    real = os.replace

    def fail(src, dst):
        if dst.endswith("index.npz"):
            raise OSError("disk full")
        return real(src, dst)

    monkeypatch.setattr(kb.os, "replace", fail)
    with pytest.raises(OSError):
        kb.sync("home")
    monkeypatch.setattr(kb.os, "replace", real)
    kb._cache.clear()
    assert top("bravo tomatoes").startswith("bravo")      # text and vectors still belong together
    assert top("alpha boiler").startswith("alpha alpha")
    kb.sync("home")
    assert top("alpha boiler").startswith("alpha changed")


def _to_legacy(name, drop_vector=False):
    """Rewrite a base in the 1.3.0 layout (vectors.npy + chunks.jsonl)."""
    vecs, chunks = kb._load(name)
    d = kb.base_dir(name)
    np.save(os.path.join(d, "vectors.npy"), vecs[:-1] if drop_vector else vecs)
    with open(os.path.join(d, "chunks.jsonl"), "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c) + "\n")
    os.remove(os.path.join(d, "index.npz"))
    kb._cache.clear()


def test_a_base_from_1_3_0_still_works_and_moves_to_the_new_file(base):
    _to_legacy("home")
    assert top("bravo tomatoes").startswith("bravo")
    kb.sync("home")
    files = set(os.listdir(kb.base_dir("home")))
    assert "index.npz" in files and not {"vectors.npy", "chunks.jsonl"} & files
    assert top("bravo tomatoes").startswith("bravo")


def test_a_damaged_old_index_is_rebuilt_never_misread(base):
    _to_legacy("home", drop_vector=True)
    with pytest.raises(RuntimeError, match="sync"):
        kb.search("home", "alpha", 1)
    out = kb.sync("home")
    assert out["changed"] == 2
    assert top("alpha boiler").startswith("alpha") and top("bravo tomatoes").startswith("bravo")


def test_another_window_holding_the_base_makes_delete_wait(base, tmp_path):
    hold = (
        "import sys, time\n"
        "from aihub import knowledge as kb\n"
        f"kb.CONFIG_DIR = {str(tmp_path / 'aihub')!r}\n"
        "with kb._base_lock('home'):\n"
        "    print('held', flush=True)\n"
        "    time.sleep(1.5)\n"
    )
    root = os.path.dirname(os.path.dirname(__file__))
    p = subprocess.Popen([sys.executable, "-c", hold], stdout=subprocess.PIPE, text=True, cwd=root,
                         env={**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)})
    try:
        assert p.stdout.readline().strip() == "held"
        start = time.time()
        kb.delete("home")
        assert time.time() - start > 0.8
        assert not os.path.exists(kb.base_dir("home"))
    finally:
        p.wait(timeout=10)


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_links_to_files_outside_the_folder_are_not_indexed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "creds.ini").write_text("password = hunter2")
    docs = tmp_path / "linked"
    docs.mkdir()
    (docs / "notes.md").write_text("ordinary notes")
    (docs / "inner.md").write_text("inner")
    os.symlink(outside / "creds.ini", docs / "link.ini")
    os.symlink(docs / "inner.md", docs / "alias.md")          # inside the folder: fine
    files, _ = kb.discover([str(docs)])
    names = {os.path.basename(f) for f in files}
    assert "link.ini" not in names and {"notes.md", "inner.md", "alias.md"} <= names


def test_a_build_that_stops_halfway_keeps_the_finished_files(base, monkeypatch):
    (base / "c.md").write_text("charlie charlie: the cellar light switch is behind the door.")
    (base / "d.md").write_text("delta delta: the attic key hangs in the kitchen.")
    calls = []

    def flaky(texts, model=None):
        calls.append(texts)
        if len(calls) == 2:
            raise RuntimeError("Ollama went away")
        return fake_embed(texts, model)

    monkeypatch.setattr(kb, "embed", flaky)
    out = kb.sync("home")
    assert out["added"] == 1 and any("Ollama went away" in p["error"] for p in out["problems"])
    monkeypatch.setattr(kb, "embed", fake_embed)
    assert kb.sync("home")["changed"] == 1                   # only the file that didn't make it


def test_cancel_stops_inside_a_big_file(base, monkeypatch):
    (base / "big.md").write_text("\n\n".join(f"paragraph {i} " + "word " * 200 for i in range(400)))
    cancel = threading.Event()
    calls = []

    def slow(texts, model=None):
        calls.append(1)
        cancel.set()
        return fake_embed(texts, model)

    monkeypatch.setattr(kb, "embed", slow)
    out = kb.sync("home", cancel=cancel)
    assert out["cancelled"] and len(calls) == 1
    monkeypatch.setattr(kb, "embed", fake_embed)
    assert kb.sync("home")["changed"] == 1                   # the half-done file comes back next time


def test_excerpts_are_framed_as_data_not_instructions(base):
    hits = kb.search("home", "boiler", 2)
    note = kb.format_context(["home"], hits)
    assert "not instructions" in note and "<documents>" in note and note.rstrip().endswith("</documents>")
    kb.set_allowed(["home"])
    try:
        assert "not instructions" in kb.search_knowledge("boiler")
    finally:
        kb.set_allowed([])


def test_text_in_other_encodings_reads_right(tmp_path):
    u16 = tmp_path / "notes-utf16.txt"
    u16.write_bytes("Zażółć gęślą jaźń".encode("utf-16"))
    cp = tmp_path / "notes-cp1250.txt"
    cp.write_bytes("Zażółć gęślą jaźń".encode("cp1250"))
    assert kb.read_document(str(u16))[0][1].strip() == "Zażółć gęślą jaźń"
    assert kb.read_document(str(cp))[0][1].strip() == "Zażółć gęślą jaźń"


def test_a_huge_docx_is_refused_before_it_is_unpacked(tmp_path, monkeypatch):
    monkeypatch.setattr(kb, "MAX_FILE_BYTES", 1000)
    p = tmp_path / "big.docx"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "<w:p>" + "a" * 5000 + "</w:p>")
    with pytest.raises(ValueError, match="larger than"):
        kb.read_document(str(p))


def test_an_embedding_answer_with_too_few_rows_is_an_error(monkeypatch):
    class R:
        status_code = 200
        ok = True
        text = ""

        def json(self):
            return {"embeddings": [[0.1, 0.2]]}

    monkeypatch.setattr(kb.requests, "post", lambda *a, **k: R())
    monkeypatch.setattr(kb, "embed", kb.__dict__["embed"])
    with pytest.raises(RuntimeError, match="2 texts"):
        kb.embed(["one", "two"], "embeddinggemma")


def test_a_file_changed_while_it_was_read_is_read_again(base, monkeypatch):
    real = kb.read_document

    def edit_during_read(path):
        out = real(path)
        if path.endswith("a.md"):
            time.sleep(0.01)
            (base / "a.md").write_text("alpha edited while being read, a longer text now.")
        return out

    (base / "a.md").write_text("alpha first version, changed so it is read again.")
    monkeypatch.setattr(kb, "read_document", edit_during_read)
    kb.sync("home")
    monkeypatch.setattr(kb, "read_document", real)
    assert kb.sync("home")["changed"] == 1


def test_names_do_not_load_every_index(base, monkeypatch):
    monkeypatch.setattr(kb, "_load", lambda name: (_ for _ in ()).throw(AssertionError("loaded")))
    assert kb.names() == ["home"]

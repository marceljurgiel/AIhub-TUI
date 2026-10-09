"""Knowledge bases: reading files (text, PDF, .docx), chunking, incremental
indexing, search, the automatic context and the search_knowledge tool. The
embedder is a deterministic stand-in (a bag of words) — no Ollama needed."""
import json
import os
import re
import zipfile

import numpy as np
import pytest

from aihub import knowledge as kb

DIM = 256


def fake_embed(texts, model=None):
    rows = []
    for t in texts:
        t = t.split("text: ", 1)[-1].split("query: ", 1)[-1]
        v = np.zeros(DIM, dtype=np.float32)
        for w in re.findall(r"\w+", t.lower()):
            v[hash(w) % DIM] += 1
        rows.append(v / (np.linalg.norm(v) or 1))
    return np.vstack(rows)


@pytest.fixture
def kbroot(tmp_path, monkeypatch):
    monkeypatch.setattr(kb, "CONFIG_DIR", str(tmp_path / "aihub"))
    monkeypatch.setattr(kb, "embed", fake_embed)
    kb._cache.clear()
    docs = tmp_path / "docs"
    (docs / "sub").mkdir(parents=True)
    (docs / "boiler.md").write_text("# Boiler\n\nThe boiler pressure should stay between 1.2 and 1.8 bar.\n\n"
                                    "# Garden\n\nWater the tomatoes every second day in July.")
    (docs / "sub" / "wifi.txt").write_text("The guest wifi password is printed under the router.")
    (docs / "node_modules").mkdir()
    (docs / "node_modules" / "skip.md").write_text("should never be indexed")
    (docs / "photo.png").write_bytes(b"\x89PNG\0\0")
    return docs


def make_pdf(path, pages):
    """A minimal PDF with one line of text per page (Helvetica)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>")
    font = 3 + 2 * len(pages)
    for i, text in enumerate(pages):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
                    f"/Resources << /Font << /F1 {font} 0 R >> >> >>")
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = b"%PDF-1.4\n"
    offsets = []
    for n, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)


def make_docx(path, paragraphs):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="x"><w:body>{body}</w:body></w:document>')


def test_readers_handle_pdf_pages_and_docx(tmp_path):
    pdf = tmp_path / "manual.pdf"
    make_pdf(pdf, ["Reset the router by holding the button", "Warranty lasts two years"])
    pages = kb.read_document(str(pdf))
    assert [p for p, _ in pages] == [1, 2] and "Warranty" in pages[1][1]
    doc = tmp_path / "notes.docx"
    make_docx(doc, ["First &amp; foremost", "Second paragraph"])
    text = kb.read_document(str(doc))[0][1]
    assert "First & foremost" in text and "Second paragraph" in text
    empty = tmp_path / "scan.pdf"
    make_pdf(empty, [""])
    with pytest.raises(ValueError, match="OCR"):
        kb.read_document(str(empty))


def test_chunks_overlap_and_keep_headings():
    text = "# Intro\n\n" + "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(12))
    parts = kb.chunk([(None, text)], size=600, overlap=100)
    assert len(parts) > 3 and all(len(p["text"]) <= 900 for p in parts)
    assert parts[0]["heading"] == "Intro"
    assert parts[1]["text"][:40] in parts[0]["text"]          # overlap carries context over


def test_add_search_and_sources(kbroot):
    kb.create("home", "House notes")
    out = kb.add("home", [str(kbroot)])
    assert out["files"] == 2 and out["chunks"] >= 2 and not out["problems"]
    hits = kb.search("home", "what pressure for the boiler?")
    assert hits[0]["source"] == "docs/boiler.md" and "1.2" in hits[0]["text"]
    assert kb.search("home", "wifi password")[0]["source"] == "docs/sub/wifi.txt"   # / on every system
    assert all("node_modules" not in h["source"] for h in kb.search("home", "indexed", 10))
    info = kb.list_bases()[0]
    assert info["name"] == "home" and info["description"] == "House notes" and info["files"] == 2


def test_sync_reembeds_only_changed_files_and_drops_deleted(kbroot, monkeypatch):
    kb.create("home")
    kb.add("home", [str(kbroot)])
    seen = []
    monkeypatch.setattr(kb, "embed", lambda texts, model=None: (seen.extend(texts), fake_embed(texts))[1])
    (kbroot / "sub" / "wifi.txt").write_text("The guest wifi password changed: ask Alex.")
    os.utime(kbroot / "sub" / "wifi.txt", (1, 1))
    out = kb.sync("home")
    assert out["changed"] == 1 and all("wifi" in t for t in seen)
    (kbroot / "boiler.md").unlink()
    out = kb.sync("home")
    assert out["removed"] == 1 and out["files"] == 1
    assert all(h["source"] != "docs/boiler.md" for h in kb.search("home", "boiler pressure", 10))


def test_problems_are_reported_not_hidden(kbroot):
    make_pdf(kbroot / "scan.pdf", [""])
    kb.create("home")
    out = kb.add("home", [str(kbroot), str(kbroot / "missing")])
    errors = {p["path"]: p["error"] for p in out["problems"]}
    assert "OCR" in errors["docs/scan.pdf"] and any("not found" in e for e in errors.values())


def test_a_changed_embedding_model_is_refused(kbroot, monkeypatch):
    kb.create("home")
    kb.add("home", [str(kbroot)])
    monkeypatch.setattr(kb, "embed_model", lambda: "other-embedder")
    with pytest.raises(ValueError, match="rebuild"):
        kb.sync("home")


def test_context_block_numbers_and_cites(kbroot):
    kb.create("home")
    kb.add("home", [str(kbroot)])
    block = kb.context_for(["home"], "boiler pressure", k=2)
    assert block.startswith("Excerpts from the user's knowledge base (home)")
    assert "[1] docs/boiler.md · Boiler" in block and "cite them like [1]" in block
    assert kb.context_for(["home"], "   ") == "" and kb.context_for([], "x") == ""


def test_tool_searches_only_attached_bases(kbroot):
    kb.create("home")
    kb.add("home", [str(kbroot)])
    kb.create("work")
    kb.set_allowed([])
    assert "No knowledge base" in kb.search_knowledge("boiler")
    kb.set_allowed(["home"])
    assert "[1] docs/boiler.md" in kb.search_knowledge("boiler pressure")
    assert "isn't attached" in kb.search_knowledge("x", base="work")
    schema = kb.tool_schema(["home"])
    assert schema["function"]["parameters"]["properties"]["base"]["enum"] == ["home"]


def test_names_are_checked_and_delete_removes_everything(kbroot):
    with pytest.raises(ValueError, match="lowercase"):
        kb.create("My Notes")
    kb.create("notes")
    with pytest.raises(ValueError, match="already exists"):
        kb.create("notes")
    assert kb.delete("notes") and kb.list_bases() == []
    with pytest.raises(KeyError):
        kb.info("notes")


def test_embed_reports_a_missing_model(monkeypatch):
    class R:
        status_code, ok, text = 404, False, '{"error":"model \\"embeddinggemma\\" not found, try pulling it first"}'
    monkeypatch.setattr(kb.requests, "post", lambda *a, **k: R())
    with pytest.raises(kb.EmbedderMissing):
        kb.embed(["x"])

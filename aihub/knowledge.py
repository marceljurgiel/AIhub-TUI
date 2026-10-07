"""
AIhub — knowledge bases: search your own documents by meaning (local RAG).

A knowledge base is a folder `~/.aihub/knowledge/<name>/` holding:
- `meta.json`: name, description, embedding model, sources, and per-file
  mtime/size;
- `chunks.jsonl`: one line per fragment — source file, page, title, text;
- `vectors.npy`: one normalized float32 row per chunk.

Files are read (text and code, PDF via pypdf, .docx from its XML), cut into
overlapping fragments and embedded by Ollama — EmbeddingGemma by default,
with its task prompts. Search is a cosine over all rows (milliseconds for
tens of thousands of chunks), with a small boost for exact words such as
names and numbers.

Agents get bases as `kb:<name>` in their tools: the best fragments are added
to every turn (see `context_for`), and the `search_knowledge` tool digs
deeper. In plain chat, `/kb <name>` does the same for the session.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import shutil
import threading
import time
import zipfile
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import numpy as np
import requests

from .config import CONFIG_DIR, config

log = logging.getLogger(__name__)

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
CHUNK_CHARS = 1200
OVERLAP_CHARS = 200
BATCH = 32
MAX_FILE_BYTES = 30 * 1024 * 1024

TEXT_EXT = {".md", ".markdown", ".txt", ".rst", ".org", ".tex", ".csv", ".tsv", ".json", ".yaml", ".yml",
            ".toml", ".ini", ".cfg", ".xml", ".html", ".htm", ".py", ".js", ".ts", ".tsx", ".jsx", ".java",
            ".go", ".rs", ".c", ".h", ".cpp", ".hpp", ".cs", ".rb", ".php", ".sh", ".ps1", ".sql", ".swift",
            ".kt", ".lua", ".r", ".m", ".scala", ".vue", ".svelte", ".css", ".scss"}
DOC_EXT = {".pdf", ".docx"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".cache", ".idea",
             ".vscode", "target", ".next"}


class EmbedderMissing(RuntimeError):
    """The embedding model isn't on the Ollama server (yet)."""


# ── where things live ────────────────────────────────────────────────────────

def root() -> str:
    return os.path.join(CONFIG_DIR, "knowledge")


def base_dir(name: str) -> str:
    return os.path.join(root(), name)


def embed_url() -> str:
    return (getattr(config, "embed_ollama_url", "") or config.ollama_api_url).rstrip("/")


def embed_model() -> str:
    return getattr(config, "embed_model", "") or "embeddinggemma"


# ── reading documents ────────────────────────────────────────────────────────

def _read_text(path: str) -> List[Tuple[Optional[int], str]]:
    with open(path, "rb") as f:
        raw = f.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("larger than 30 MB")
    if b"\0" in raw[:4096]:
        raise ValueError("binary file")
    text = raw.decode("utf-8", errors="replace")
    if os.path.splitext(path)[1].lower() in (".html", ".htm", ".xml"):
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return [(None, text)]


def _read_pdf(path: str) -> List[Tuple[Optional[int], str]]:
    from pypdf import PdfReader
    reader = PdfReader(path)
    pages = []
    for i, page in enumerate(reader.pages, 1):
        try:
            t = page.extract_text() or ""
        except Exception as exc:   # one bad page shouldn't lose the rest
            log.info("pdf page %d of %s: %s", i, path, exc)
            t = ""
        if t.strip():
            pages.append((i, t))
    if not pages:
        raise ValueError("no text in this PDF (a scan? it needs OCR first)")
    return pages


def _read_docx(path: str) -> List[Tuple[Optional[int], str]]:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"</w:p>", "\n\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    xml = re.sub(r"<w:br/>", "\n", xml)
    text = html.unescape(re.sub(r"<[^>]+>", "", xml))
    if not text.strip():
        raise ValueError("no text in this document")
    return [(None, text)]


def read_document(path: str) -> List[Tuple[Optional[int], str]]:
    """[(page or None, text)] for a supported file."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return _read_pdf(path)
    if ext == ".docx":
        return _read_docx(path)
    return _read_text(path)


def supported(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in TEXT_EXT | DOC_EXT


def discover(paths: Iterable[str]) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Files under the given files/folders, and the paths that don't exist."""
    files, missing = [], []
    for p in paths:
        p = os.path.abspath(os.path.expanduser(p))
        if os.path.isfile(p):
            files.append(p)
        elif os.path.isdir(p):
            for dirpath, dirs, names in os.walk(p):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
                files += [os.path.join(dirpath, n) for n in sorted(names) if supported(n) and not n.startswith(".")]
        else:
            missing.append((p, "not found"))
    return list(dict.fromkeys(files)), missing


# ── chunking ────────────────────────────────────────────────────────────────

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")


def chunk(segments: List[Tuple[Optional[int], str]], size: int = CHUNK_CHARS,
          overlap: int = OVERLAP_CHARS) -> List[Dict[str, Any]]:
    """Overlapping fragments of about `size` characters, cut at paragraph
    boundaries when possible; each knows its page and nearest heading."""
    out: List[Dict[str, Any]] = []
    for page, text in segments:
        heading = ""
        blocks: List[Tuple[str, str]] = []
        for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
            block = block.strip()
            if not block:
                continue
            m = _HEADING.match(block.splitlines()[0])
            if m:
                heading = m.group(1)[:80]
            # Over-long blocks (a PDF page without blank lines) are cut on
            # sentence ends, then hard.
            while len(block) > size:
                cut = max(block.rfind(". ", 0, size), block.rfind("\n", 0, size))
                cut = cut + 1 if cut > size // 2 else size
                blocks.append((heading, block[:cut].strip()))
                block = block[cut:].strip()
            if block:
                blocks.append((heading, block))
        cur, cur_heading = "", ""
        for h, b in blocks:
            if cur and len(cur) + len(b) + 2 > size:
                out.append({"page": page, "heading": cur_heading, "text": cur})
                tail = cur[-overlap:]
                cur = tail[tail.find(" ") + 1:] if " " in tail else tail
            if not cur:
                cur_heading = h
            cur = f"{cur}\n\n{b}" if cur else b
        if cur.strip():
            out.append({"page": page, "heading": cur_heading, "text": cur})
    return out


# ── embeddings ──────────────────────────────────────────────────────────────

def _doc_prompt(title: str, text: str) -> str:
    return f"title: {title or 'none'} | text: {text}"


def _query_prompt(q: str) -> str:
    return f"task: search result | query: {q}"


def embed(texts: List[str], model: Optional[str] = None) -> np.ndarray:
    """Normalized embeddings from Ollama's /api/embed."""
    model = model or embed_model()
    try:
        r = requests.post(f"{embed_url()}/api/embed", json={"model": model, "input": texts}, timeout=300)
    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError(f"can't reach Ollama at {embed_url()} for embeddings") from exc
    if r.status_code == 404 or "not found" in r.text[:300].lower():
        raise EmbedderMissing(f"{model} isn't on {embed_url()} yet")
    if not r.ok:
        raise RuntimeError(f"embedding failed: {r.text[:200]}")
    vecs = np.asarray(r.json()["embeddings"], dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.where(norms == 0, 1, norms)


def embedder_status() -> Dict[str, Any]:
    """Is the embedding model ready on its Ollama server?"""
    url, model = embed_url(), embed_model()
    try:
        names = [m["name"] for m in requests.get(f"{url}/api/tags", timeout=5).json().get("models", [])]
    except Exception:
        return {"reachable": False, "ready": False, "url": url, "model": model}
    ready = model in names or f"{model}:latest" in names
    return {"reachable": True, "ready": ready, "url": url, "model": model}


def pull_embedder(emit: Callable[[str, Dict[str, Any]], None],
                  cancel: Optional[threading.Event] = None) -> Dict[str, Any]:
    """Download the embedding model onto the embedding server, with progress."""
    url, model = embed_url(), embed_model()
    with requests.post(f"{url}/api/pull", json={"model": model}, stream=True, timeout=None) as r:
        if not r.ok:
            raise RuntimeError(f"downloading {model} failed: {r.text[:200]}")
        for line in r.iter_lines():
            if cancel is not None and cancel.is_set():
                return {"cancelled": True}
            d = json.loads(line or "{}")
            if d.get("error"):
                raise RuntimeError(d["error"])
            emit("progress", {"status": d.get("status", ""), "completed": d.get("completed", 0),
                              "total": d.get("total", 0)})
    return {"model": model, "url": url, "ready": embedder_status()["ready"]}


# ── storage ─────────────────────────────────────────────────────────────────

_locks: Dict[str, threading.Lock] = {}
_cache: Dict[str, Tuple[float, np.ndarray, List[Dict[str, Any]]]] = {}


def _lock(name: str) -> threading.Lock:
    return _locks.setdefault(name, threading.Lock())


def _meta_path(name: str) -> str:
    return os.path.join(base_dir(name), "meta.json")


def _load_meta(name: str) -> Dict[str, Any]:
    try:
        with open(_meta_path(name), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise KeyError(f"no knowledge base called {name!r}") from None


def _write_json(path: str, data: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _load(name: str) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    vpath = os.path.join(base_dir(name), "vectors.npy")
    cpath = os.path.join(base_dir(name), "chunks.jsonl")
    if not os.path.exists(vpath):
        return np.zeros((0, 0), dtype=np.float32), []
    mtime = os.path.getmtime(vpath)
    hit = _cache.get(name)
    if hit and hit[0] == mtime:
        return hit[1], hit[2]
    vecs = np.load(vpath)
    with open(cpath, encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f if line.strip()]
    _cache[name] = (mtime, vecs, chunks)
    return vecs, chunks


def _save(name: str, vecs: np.ndarray, chunks: List[Dict[str, Any]]) -> None:
    d = base_dir(name)
    with open(os.path.join(d, "chunks.jsonl.tmp"), "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with open(os.path.join(d, "vectors.npy.tmp"), "wb") as f:
        np.save(f, vecs.astype(np.float32))
    os.replace(os.path.join(d, "chunks.jsonl.tmp"), os.path.join(d, "chunks.jsonl"))
    os.replace(os.path.join(d, "vectors.npy.tmp"), os.path.join(d, "vectors.npy"))
    _cache.pop(name, None)


# ── bases ───────────────────────────────────────────────────────────────────

def create(name: str, description: str = "") -> Dict[str, Any]:
    name = name.strip().lower()
    if not NAME.match(name):
        raise ValueError("name: lowercase letters, digits, - or _ (up to 32)")
    if os.path.exists(_meta_path(name)):
        raise ValueError(f"a knowledge base called {name!r} already exists")
    os.makedirs(base_dir(name), exist_ok=True)
    meta = {"name": name, "description": description.strip(), "model": embed_model(), "dim": 0,
            "created": int(time.time()), "updated": 0, "sources": [], "files": {}}
    _write_json(_meta_path(name), meta)
    return info(name)


def info(name: str) -> Dict[str, Any]:
    meta = _load_meta(name)
    vecs, chunks = _load(name)
    size = sum(os.path.getsize(os.path.join(base_dir(name), f)) for f in os.listdir(base_dir(name)))
    return {"name": meta["name"], "description": meta.get("description", ""), "model": meta.get("model", ""),
            "sources": meta.get("sources", []), "files": len(meta.get("files", {})), "chunks": len(chunks),
            "bytes": size, "updated": meta.get("updated", 0)}


def list_bases() -> List[Dict[str, Any]]:
    if not os.path.isdir(root()):
        return []
    out = []
    for n in sorted(os.listdir(root())):
        if os.path.exists(_meta_path(n)):
            try:
                out.append(info(n))
            except Exception as exc:
                log.warning("knowledge base %s: %s", n, exc)
    return out


def names() -> List[str]:
    return [b["name"] for b in list_bases()]


def delete(name: str) -> bool:
    _load_meta(name)
    shutil.rmtree(base_dir(name))
    _cache.pop(name, None)
    return True


def _display(path: str, sources: List[str]) -> str:
    """A short name for a file: relative to the folder it was added from."""
    for s in sorted(sources, key=len, reverse=True):
        if os.path.isdir(s) and path.startswith(s.rstrip(os.sep) + os.sep):
            return os.path.relpath(path, os.path.dirname(s.rstrip(os.sep)))
    return os.path.basename(path)


def _index(name: str, emit: Callable[[str, Dict[str, Any]], None],
           cancel: Optional[threading.Event], new_sources: List[str]) -> Dict[str, Any]:
    """Bring the base up to date with its sources: embed new or changed
    files, drop chunks of changed or vanished ones."""
    with _lock(name):
        meta = _load_meta(name)
        if meta.get("model") and meta["model"] != embed_model() and meta.get("dim"):
            raise ValueError(f"{name} was built with {meta['model']}; the embedding model is now "
                             f"{embed_model()} — delete and rebuild the base, or switch back")
        meta["sources"] = list(dict.fromkeys(meta.get("sources", []) +
                                             [os.path.abspath(os.path.expanduser(s)) for s in new_sources]))
        files, missing = discover(meta["sources"])
        problems = [{"path": p, "error": e} for p, e in missing]
        emit("scan", {"files": len(files)})
        known = meta.get("files", {})
        vecs, chunks = _load(name)
        todo = []
        for f in files:
            st = os.stat(f)
            if known.get(f, {}).get("mtime") == st.st_mtime and known[f].get("size") == st.st_size:
                continue
            todo.append(f)
        gone = (set(known) - set(files)) | set(todo)
        keep = [i for i, c in enumerate(chunks) if c["file"] not in gone]
        vecs = vecs[keep] if len(vecs) else vecs
        chunks = [chunks[i] for i in keep]
        for f in gone:
            known.pop(f, None)

        new_vecs, added = [], 0
        for i, f in enumerate(todo, 1):
            if cancel is not None and cancel.is_set():
                break
            disp = _display(f, meta["sources"])
            try:
                parts = chunk(read_document(f))
            except Exception as exc:
                problems.append({"path": disp, "error": str(exc)})
                emit("problem", {"path": disp, "error": str(exc)})
                continue
            emit("file", {"i": i, "n": len(todo), "path": disp, "chunks": len(parts)})
            pieces = []
            for p in parts:
                title = disp + (f" · p.{p['page']}" if p["page"] else "") + (f" · {p['heading']}" if p["heading"] else "")
                pieces.append({"file": f, "source": disp, "page": p["page"], "title": title, "text": p["text"]})
            file_vecs = []
            for b in range(0, len(pieces), BATCH):
                batch = pieces[b:b + BATCH]
                file_vecs.append(embed([_doc_prompt(c["title"], c["text"]) for c in batch]))
                emit("embed", {"path": disp, "done": min(b + BATCH, len(pieces)), "total": len(pieces)})
            if file_vecs:
                new_vecs.append(np.vstack(file_vecs))
            chunks += pieces
            added += len(pieces)
            st = os.stat(f)
            known[f] = {"mtime": st.st_mtime, "size": st.st_size, "chunks": len(pieces)}

        if new_vecs:
            add = np.vstack(new_vecs)
            vecs = add if not len(vecs) else np.vstack([vecs, add])
            meta["dim"] = int(vecs.shape[1])
        for i, c in enumerate(chunks):
            c["id"] = i
        meta["files"] = known
        meta["model"] = embed_model()
        meta["updated"] = int(time.time())
        _save(name, vecs if len(vecs) else np.zeros((0, meta.get("dim") or 0), dtype=np.float32), chunks)
        _write_json(_meta_path(name), meta)
        cancelled = cancel is not None and cancel.is_set()
        return {"files": len(known), "changed": len(todo), "chunks": len(chunks), "added": added,
                "removed": len(gone - set(todo)), "problems": problems, "cancelled": cancelled}


def add(name: str, paths: List[str], emit: Callable[[str, Dict[str, Any]], None] = lambda e, d: None,
        cancel: Optional[threading.Event] = None) -> Dict[str, Any]:
    return _index(name, emit, cancel, paths)


def sync(name: str, emit: Callable[[str, Dict[str, Any]], None] = lambda e, d: None,
         cancel: Optional[threading.Event] = None) -> Dict[str, Any]:
    return _index(name, emit, cancel, [])


def remove_source(name: str, source: str) -> Dict[str, Any]:
    with _lock(name):
        meta = _load_meta(name)
        meta["sources"] = [s for s in meta.get("sources", []) if s != source]
        _write_json(_meta_path(name), meta)
    return sync(name)


# ── search ──────────────────────────────────────────────────────────────────

_WORD = re.compile(r"[\w-]{3,}|\d+", re.UNICODE)


def search(bases: List[str] | str, query: str, k: int = 6) -> List[Dict[str, Any]]:
    """The k best fragments across the bases, best first."""
    bases = [bases] if isinstance(bases, str) else list(bases)
    words = {w.lower() for w in _WORD.findall(query)}
    by_model: Dict[str, np.ndarray] = {}
    hits: List[Dict[str, Any]] = []
    for b in bases:
        meta = _load_meta(b)
        vecs, chunks = _load(b)
        if not len(chunks):
            continue
        model = meta.get("model") or embed_model()
        if model not in by_model:
            by_model[model] = embed([_query_prompt(query)], model)[0]
        scores = vecs @ by_model[model]
        # Exact words (names, numbers, codes) count a little extra.
        if words:
            for i, c in enumerate(chunks):
                low = c["text"].lower()
                n = sum(1 for w in words if w in low)
                if n:
                    scores[i] += min(0.1, 0.03 * n)
        top = np.argsort(-scores)[:k]
        for i in top:
            c = chunks[int(i)]
            hits.append({"base": b, "source": c["source"], "page": c.get("page"), "title": c["title"],
                         "text": c["text"], "score": round(float(scores[int(i)]), 3)})
    hits.sort(key=lambda h: -h["score"])
    return hits[:k]


def context_for(bases: List[str], query: str, k: int = 5, budget_chars: int = 6000) -> str:
    """The note added to a turn: the best fragments, numbered for citing."""
    if not bases or not query.strip():
        return ""
    try:
        hits = search(bases, query, k)
    except Exception as exc:
        log.info("knowledge context failed: %s", exc)
        return ""
    return format_context(bases, hits, budget_chars)


def format_context(bases: List[str], hits: List[Dict[str, Any]], budget_chars: int = 6000) -> str:
    if not hits:
        return ""
    parts, used = [], 0
    for n, h in enumerate(hits, 1):
        block = f"[{n}] {h['title']}\n{h['text'].strip()}"
        if used + len(block) > budget_chars and parts:
            break
        parts.append(block[: max(200, budget_chars - used)])
        used += len(block)
    return ("Excerpts from the user's knowledge base (" + ", ".join(bases) + "), most relevant first. "
            "Answer from them when they cover the question and cite them like [1]; say so when they don't, "
            "and don't invent sources.\n\n" + "\n\n".join(parts))


# ── the search_knowledge tool ───────────────────────────────────────────────

_turn = threading.local()


def set_allowed(bases: List[str]) -> None:
    """The bases the current turn may search (the agent's, or /kb's)."""
    _turn.allowed = list(bases or [])


def allowed() -> List[str]:
    return list(getattr(_turn, "allowed", []) or [])


def search_knowledge(query: str, base: str = "") -> str:
    """Tool: search the knowledge bases allowed in this conversation."""
    ok = allowed()
    if not ok:
        return "[Tool Error] No knowledge base is attached to this conversation."
    targets = [base] if base else ok
    if base and base not in ok:
        return f"[Tool Error] '{base}' isn't attached here. Attached: {', '.join(ok)}."
    try:
        hits = search(targets, query, 6)
    except EmbedderMissing as exc:
        return f"[Tool Error] {exc}. Ask the user to open Knowledge and download it."
    if not hits:
        return f"No matches in {', '.join(targets)}."
    return "\n\n".join(f"[{n}] {h['title']} (score {h['score']})\n{h['text'].strip()}"
                       for n, h in enumerate(hits, 1))


def tool_schema(bases: List[str]) -> Dict[str, Any]:
    descs = {b["name"]: b["description"] for b in list_bases()}
    listed = "; ".join(f"{b}: {descs.get(b) or 'no description'}" for b in bases)
    return {"type": "function", "function": {
        "name": "search_knowledge",
        "description": ("Search the user's knowledge base(s) by meaning and get the most relevant passages "
                        f"with their sources. Bases: {listed}. Use it when the answer may be in the "
                        "user's own documents; cite results like [1]."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "What to look for, as a question or keywords"},
            "base": {"type": "string", "enum": bases, "description": "One base to search (default: all attached)"},
        }, "required": ["query"]},
    }}

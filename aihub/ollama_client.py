"""
AIHub - Ollama API client (v0.1.0).
Handles all communication with the local Ollama REST API.
v0.1.0: Added 'tools' parameter support to chat_stream() for tool-calling models.
"""
import json
import logging
import re

import requests
from typing import List, Dict, Any, Optional, Generator, Tuple

from .config import config

log = logging.getLogger(__name__)


def is_ollama_running() -> bool:
    """Return True if the Ollama server is reachable."""
    try:
        response = requests.get(config.ollama_api_url, timeout=2)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def _ollama_binary() -> Optional[str]:
    import os
    import shutil
    found = shutil.which("ollama")
    if found:
        return found
    for path in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
                 "/Applications/Ollama.app/Contents/Resources/ollama",
                 "/usr/local/bin/ollama"):
        if path and os.path.isfile(path):
            return path
    return None


def start_local_ollama(wait_s: float = 10.0) -> bool:
    """Start `ollama serve` in the background when AIhub uses a local Ollama
    that is installed but not running (no service after a reboot, WSL,
    containers). True when Ollama answers afterwards."""
    import os
    import subprocess
    import sys
    import time
    from .target import is_local
    if is_ollama_running():
        return True
    binary = _ollama_binary()
    if not binary or not is_local(config.ollama_api_url):
        return False
    from .config import CONFIG_DIR
    os.makedirs(CONFIG_DIR, exist_ok=True)
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                                   | subprocess.CREATE_NO_WINDOW)
    else:
        kwargs["start_new_session"] = True   # outlives AIhub, like a service
    try:
        with open(os.path.join(CONFIG_DIR, "ollama-serve.log"), "ab") as logf:
            # From the home folder: a server started inside AIhub's folder
            # would lock it on Windows and block `aihub update`.
            subprocess.Popen([binary, "serve"], stdin=subprocess.DEVNULL, stdout=logf, stderr=logf,
                             cwd=os.path.expanduser("~"), **kwargs)
    except OSError as exc:
        log.info("starting ollama serve failed: %s", exc)
        return False
    log.info("started %s serve", binary)
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if is_ollama_running():
            return True
        time.sleep(0.5)
    return False


def get_local_models() -> list:
    """Return a list of model name strings currently installed in Ollama."""
    try:
        response = requests.get(f"{config.ollama_api_url}/api/tags", timeout=3)
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", [])]
    except Exception as exc:
        log.info("listing Ollama models failed: %s", exc)
        return []


def import_gguf_model(path: str, model_name: str) -> tuple:
    """Import a local .gguf file into Ollama as `model_name`, making it a
    regular installed model (shows up in /api/tags like any pulled model).

    Modern servers: upload the file as a blob (sha256), then /api/create with
    a files map. Older servers: fall back to a Modelfile 'FROM <path>' create
    (works when the server runs on this machine). Returns (ok, error).
    """
    import hashlib
    import os as _os
    try:
        # 0. Chat template: a bare import leaves Ollama's raw '{{ .Prompt }}'
        # (no chat wrapping, no stop tokens) — models then answer 'hi' with
        # gibberish. Detect the format from the GGUF's own metadata.
        template = ""
        stops: list = []
        try:
            from .gguf import CHAT_TEMPLATES, detect_chat_format
            fmt = detect_chat_format(path)
            if fmt:
                template, stops = CHAT_TEMPLATES[fmt]
        except Exception:
            template, stops = "", []

        # 1. Digest of the file (Ollama addresses blobs by sha256).
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        digest = f"sha256:{h.hexdigest()}"

        # 2. Ensure the blob exists server-side (HEAD then upload).
        blob_url = f"{config.ollama_api_url}/api/blobs/{digest}"
        try:
            have = requests.head(blob_url, timeout=10).status_code == 200
        except Exception:
            have = False
        if not have:
            with open(path, "rb") as fh:
                up = requests.post(blob_url, data=fh, timeout=3600)
            if up.status_code not in (200, 201):
                return False, f"blob upload failed: HTTP {up.status_code}"

        # 3. Create the model from the blob.
        payload: Dict[str, Any] = {
            "model": model_name,
            "files": {_os.path.basename(path): digest},
            "stream": False,
        }
        if template:
            payload["template"] = template
            payload["parameters"] = {"stop": stops}
        resp = requests.post(
            f"{config.ollama_api_url}/api/create", json=payload, timeout=600,
        )
        if resp.ok and '"error"' not in resp.text:
            return True, ""

        # 4. Legacy fallback (pre-0.6 servers; same-machine path).
        modelfile = f"FROM {path}"
        if template:
            modelfile += f'\nTEMPLATE """{template}"""'
            for s in stops:
                modelfile += f"\nPARAMETER stop {s}"
        legacy = requests.post(
            f"{config.ollama_api_url}/api/create",
            json={"name": model_name, "modelfile": modelfile,
                  "stream": False},
            timeout=600,
        )
        if legacy.ok and '"error"' not in legacy.text:
            return True, ""
        try:
            reason = resp.json().get("error") or resp.text
        except Exception:
            reason = resp.text
        return False, str(reason)[:300]
    except Exception as exc:
        return False, str(exc)


def model_template(model_name: str) -> str:
    """The chat template of an installed model ('' when unavailable)."""
    try:
        resp = requests.post(
            f"{config.ollama_api_url}/api/show",
            json={"name": model_name}, timeout=5,
        )
        if resp.ok:
            return (resp.json().get("template") or "").strip()
    except Exception as exc:
        log.info("reading chat template of %s failed: %s", model_name, exc)
    return ""


def get_local_model_sizes() -> dict:
    """
    Return a dict mapping model name → size in GB for installed models.
    Falls back to an empty dict if Ollama is offline.
    """
    try:
        response = requests.get(f"{config.ollama_api_url}/api/tags", timeout=3)
        response.raise_for_status()
        result = {}
        for m in response.json().get("models", []):
            size_bytes = m.get("size", 0)
            result[m["name"]] = round(size_bytes / (1024 ** 3), 2)
        return result
    except Exception as exc:
        log.info("listing Ollama model sizes failed: %s", exc)
        return {}


def server_version(base_url: Optional[str] = None) -> str:
    """The Ollama server's version, or "" when it doesn't say."""
    try:
        r = requests.get(f"{base_url or config.ollama_api_url}/api/version", timeout=5)
        r.raise_for_status()
        return str(r.json().get("version") or "")
    except Exception:
        return ""


def pull_error(model_name: str, text: str, status: int = 0, base_url: Optional[str] = None) -> str:
    """Ollama's pull error, said so a person knows what to do — and on one
    line: Ollama's messages run over several, and the window shows one.
    412 is the registry refusing an Ollama too old for the model."""
    if status == 412 or re.search(r"\b412\b|requires a newer version of Ollama", text):
        from urllib.parse import urlparse
        host = urlparse(base_url or config.ollama_api_url).hostname or "the server"
        ver = server_version(base_url)
        has = f" (it has {ver})" if ver else ""
        return (f"{model_name} needs a newer Ollama than the one on {host}{has} — "
                "update Ollama there, then pull again.")
    return " ".join(str(text).split())


def pull_model_stream(model_name: str):
    """
    Pull (download) a model from Ollama and yield progress dicts.

    Each yielded dict may contain keys: 'status', 'completed', 'total', 'error'.
    """
    url     = f"{config.ollama_api_url}/api/pull"
    payload = {"name": model_name}
    try:
        response = requests.post(url, json=payload, stream=True, timeout=600)
        response.raise_for_status()
        for line in response.iter_lines():
            if line:
                d = json.loads(line)
                if d.get("error"):
                    d["error"] = pull_error(model_name, d["error"])
                yield d
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", 0) or 0
        yield {"error": pull_error(model_name, str(exc), status)}
    except Exception as exc:
        yield {"error": pull_error(model_name, str(exc))}


def _ollama_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attached images (expanded to {mime, data}) → Ollama's `images: [base64]`."""
    out = []
    for m in messages:
        imgs = m.get("images")
        if imgs and isinstance(imgs[0], dict):
            m = {**m, "images": [i["data"] for i in imgs if i.get("data")]}
        out.append(m)
    return out


# A context too big for the server's memory fails the whole request; these
# are the messages Ollama (llama.cpp, CUDA, ROCm, Metal) gives for it.
_OOM = re.compile(r"out of memory|failed to allocate|cudaMalloc failed|unable to allocate"
                  r"|insufficient memory|requires more system memory", re.I)
_MIN_CTX = 2048
_ctx_cap: Dict[Tuple[str, str], int] = {}


def chat_stream(model_name: str, messages: List[Dict[str, Any]], temperature: float = 0.7, tools: Optional[List[Dict[str, Any]]] = None, context_length: Optional[int] = None) -> Generator[Dict[str, Any], None, None]:
    """
    Send messages to Ollama and yield streamed response chunks.

    Args:
        model_name:     Ollama model identifier.
        messages:       List of message dicts (role/content).
        temperature:    Sampling temperature.
        tools:          Optional list of tool schemas.
        context_length: Optional context window size override.
    """
    url     = f"{config.ollama_api_url}/api/chat"
    options = {
        "temperature": temperature,
        "num_ctx":     context_length or config.default_context_length
    }
    # Force GPU layer offload when configured. Only send when > 0 — num_gpu=0
    # would force Ollama to run on CPU.
    if getattr(config, "ollama_num_gpu", 0) and config.ollama_num_gpu > 0:
        options["num_gpu"] = config.ollama_num_gpu
    payload = {
        "model":    model_name,
        "messages": _ollama_messages(messages),
        "stream":   True,
        "options":  options
    }
    if tools:
        payload["tools"] = tools

    cap_key = (config.ollama_api_url, model_name)
    if cap_key in _ctx_cap:
        options["num_ctx"] = min(options["num_ctx"], _ctx_cap[cap_key])

    response = None
    try:
        while True:
            response = requests.post(url, json=payload, stream=True, timeout=120)
            if response.ok:
                break
            # Surface the Ollama error body so callers get a useful message.
            try:
                body = response.json()
                reason = body.get("error") or body.get("message") or response.text
            except Exception:
                reason = response.text or response.reason
            # The context didn't fit the server's memory: retry with half of
            # it, and remember what fit for the next turns.
            if _OOM.search(str(reason)) and options["num_ctx"] > _MIN_CTX:
                response.close()
                options["num_ctx"] = max(_MIN_CTX, options["num_ctx"] // 2)
                _ctx_cap[cap_key] = options["num_ctx"]
                log.info("%s ran out of memory; retrying with num_ctx=%d", model_name, options["num_ctx"])
                continue
            yield {"error": f"{response.status_code}: {reason}"}
            return
        for line in response.iter_lines():
            if line:
                yield json.loads(line)
    except Exception as exc:
        yield {"error": str(exc)}
    finally:
        # Also runs when the consumer closes this generator early (cancel):
        # dropping the connection makes Ollama stop generating.
        if response is not None:
            response.close()


def chat_sync(model_name: str, messages: List[Dict[str, Any]], temperature: float = 0.7, context_length: Optional[int] = None) -> str:
    """Send messages to Ollama and return the full response string (non-streaming)."""
    url     = f"{config.ollama_api_url}/api/chat"
    options = {
        "temperature": temperature,
        "num_ctx":     context_length or config.default_context_length
    }
    payload = {
        "model":    model_name,
        "messages": messages,
        "stream":   False,
        "options":  options
    }
    try:
        response = requests.post(url, json=payload, timeout=120)
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "")
    except Exception as exc:
        log.warning("Ollama chat_sync with %s failed", model_name, exc_info=True)
        return f"Error: Could not generate a response ({exc})."


def chat_json(model_name: str, messages: List[Dict[str, Any]], schema: Dict[str, Any],
              base_url: Optional[str] = None, timeout: float = 90,
              keep_alive: Optional[Any] = None, max_tokens: int = 400) -> Any:
    """One non-streaming reply constrained to `schema` (Ollama structured
    output), parsed. Thinking is off and temperature 0: this is for small
    extraction jobs, not conversation. Raises on HTTP errors or bad JSON."""
    url = f"{(base_url or config.ollama_api_url).rstrip('/')}/api/chat"
    payload = {
        "model": model_name,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": schema,
        # num_predict caps runaway generation: without it a model that never
        # closes the JSON (small ones, qwen3 in JSON mode) runs until timeout.
        "options": {"temperature": 0, "num_ctx": 4096, "num_predict": max_tokens},
    }
    if keep_alive is not None:
        # 0 = unload right after: a background job shouldn't hold VRAM that
        # the chat model needs.
        payload["keep_alive"] = keep_alive
    response = requests.post(url, json=payload, timeout=timeout)
    if not response.ok:
        try:
            reason = response.json().get("error") or response.text
        except ValueError:
            reason = response.text
        raise RuntimeError(f"{model_name}: {response.status_code} {reason}")
    return json.loads(response.json().get("message", {}).get("content", "") or "{}")


_CARD_CACHE: Dict[str, Dict[str, Any]] = {}


def _human_params(value: Any) -> str:
    """'8.2B' stays; cloud models report a bare count (550000000000 → '550B');
    '999.89M' → '1B'."""
    s = str(value or "").strip()
    try:
        n = float(s) if re.fullmatch(r"\d+(\.\d+)?", s) else None
    except ValueError:
        n = None
    if n is None:
        m = re.fullmatch(r"([\d.]+)\s*([MBT])", s, re.I)
        if not m:
            return s
        n = float(m.group(1)) * {"M": 1e6, "B": 1e9, "T": 1e12}[m.group(2).upper()]
    if n >= 1e12:
        return f"{n / 1e12:.1f}T".replace(".0T", "T")
    if n >= 9.95e8:
        b = n / 1e9
        return f"{b:.0f}B" if b >= 10 else f"{b:.1f}B".replace(".0B", "B")
    return f"{n / 1e6:.0f}M"


def model_card(model_name: str) -> Dict[str, Any]:
    """What a model can do, for the picker: capabilities (tools, thinking,
    vision, audio…, without the implied "completion"), max context, parameter
    size and quantization. Cached per session; {} when Ollama can't say (e.g.
    a retired cloud tag)."""
    if model_name in _CARD_CACHE:
        return _CARD_CACHE[model_name]
    try:
        r = requests.post(f"{config.ollama_api_url}/api/show", json={"name": model_name}, timeout=5)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        log.info("model card for %s failed: %s", model_name, exc)
        # 4xx (unknown or retired model) won't change this session; timeouts may.
        resp = getattr(exc, "response", None)
        if resp is not None and 400 <= resp.status_code < 500:
            _CARD_CACHE[model_name] = {}
        return {}
    info = data.get("model_info") or {}
    max_ctx = next((int(v) for k, v in info.items() if k.endswith("context_length") and isinstance(v, (int, float))), 0)
    details = data.get("details") or {}
    card = {
        "capabilities": [c for c in (data.get("capabilities") or []) if c != "completion"],
        "max_context": max_ctx,
        "params": _human_params(details.get("parameter_size", "")),
        "quant": details.get("quantization_level", ""),
    }
    _CARD_CACHE[model_name] = card
    return card


_kv_cache: Dict[Tuple[str, str], Optional[int]] = {}
_kv_down: Dict[str, float] = {}   # server → when it last failed to answer


def kv_bytes_per_token(model_name: str) -> Optional[int]:
    """KV-cache bytes one token of context takes on the GPU (f16 cache), from
    the model's own dimensions in /api/show. None when they're unknown."""
    import time
    key = (config.ollama_api_url, model_name)
    if key in _kv_cache:
        return _kv_cache[key]
    # A server that's down is asked again only after a while: context sizing
    # calls this once per step, and a refused connection on Windows takes ~4 s.
    if time.time() - _kv_down.get(config.ollama_api_url, 0) < 30:
        return None
    result = None
    try:
        r = requests.post(f"{config.ollama_api_url}/api/show", json={"name": model_name}, timeout=5)
        r.raise_for_status()
        info = r.json().get("model_info") or {}
        arch = info.get("general.architecture", "")

        def num(field):
            v = info.get(f"{arch}.{field}")
            if isinstance(v, list):  # per-layer values: the largest is safe
                v = max((x for x in v if isinstance(x, (int, float))), default=None)
            return int(v) if isinstance(v, (int, float)) and v > 0 else None

        layers = num("block_count")
        kv_heads = num("attention.head_count_kv") or num("attention.head_count")
        head_dim = None
        if num("embedding_length") and num("attention.head_count"):
            head_dim = num("embedding_length") // num("attention.head_count")
        k_len = num("attention.key_length") or head_dim
        v_len = num("attention.value_length") or head_dim
        # Hybrid models (e.g. Qwen3.5) keep a KV cache in every n-th layer only.
        if layers and num("full_attention_interval"):
            layers = -(-layers // num("full_attention_interval"))
        if layers and kv_heads and k_len and v_len:
            result = layers * kv_heads * (k_len + v_len) * 2
    except Exception as exc:
        log.info("reading model dimensions for %s failed: %s", model_name, exc)
        if isinstance(exc, requests.exceptions.ConnectionError):
            _kv_down[config.ollama_api_url] = time.time()
        return None  # not cached: the model may be pulled or the server back soon
    _kv_cache[key] = result
    return result


def get_model_info(model_name: str) -> dict:
    """
    Fetch model details from Ollama `/api/show`.

    Returns a dict with:
      context_length:  configured num_ctx if set, else the model's max
      max_context:     the model's true maximum context window (from model_info)
      capabilities:    list, e.g. ["completion", "tools", "vision"]
      supports_tools:  bool — whether tool calling is supported
    """
    url     = f"{config.ollama_api_url}/api/show"
    payload = {"name": model_name}
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        data = response.json()

        capabilities = data.get("capabilities") or []

        # True max context from model_info: "<arch>.context_length"
        max_context = 0
        model_info = data.get("model_info") or {}
        for k, v in model_info.items():
            if k.endswith(".context_length"):
                try:
                    max_context = int(v)
                except (TypeError, ValueError):
                    pass
                break

        # Configured num_ctx, if pinned in the modelfile parameters
        params = data.get("parameters", "")
        ctx_match = re.search(r"num_ctx\s+(\d+)", params)
        configured = int(ctx_match.group(1)) if ctx_match else 0

        context_length = configured or max_context or config.default_context_length
        return {
            "context_length": context_length,
            "max_context":    max_context or context_length,
            "capabilities":   capabilities,
            "supports_tools": "tools" in capabilities,
        }
    except Exception as exc:
        # Callers gate agent mode on supports_tools — record why it's False.
        log.info("reading model info for %s failed: %s", model_name, exc)
        return {
            "context_length": config.default_context_length,
            "max_context":    config.default_context_length,
            "capabilities":   [],
            "supports_tools": False,
        }


def unload_model(model_name: str):
    """
    Tell Ollama to immediately unload a model from RAM/VRAM.
    Uses keep_alive=0 via /api/chat to trigger de-loading.
    """
    url     = f"{config.ollama_api_url}/api/chat"
    payload = {
        "model":      model_name,
        "messages":   [],
        "keep_alive": 0
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as exc:
        log.info("unloading %s failed: %s", model_name, exc)


def get_running_models() -> list:
    """Return Ollama's currently-loaded models (GET /api/ps). Each entry has
    'name', 'size' (total bytes) and 'size_vram' (bytes resident on GPU)."""
    try:
        response = requests.get(f"{config.ollama_api_url}/api/ps", timeout=3)
        response.raise_for_status()
        return response.json().get("models", []) or []
    except Exception as exc:
        # Polled for the hardware view; debug level keeps an offline Ollama quiet.
        log.debug("listing running models failed: %s", exc)
        return []


def _same_model(a: str, b: str) -> bool:
    """One Ollama model under two spellings: a bare name means ':latest'.
    Only the tag may be implied — qwen3:4b is not qwen3:8b."""
    full = lambda n: n if ":" in n else f"{n}:latest"
    return full(a) == full(b)


def _placement_in(models: list, model_name: str) -> dict:
    for m in models:
        if _same_model(m.get("name") or m.get("model") or "", model_name):
            size = float(m.get("size", 0) or 0)
            vram = float(m.get("size_vram", 0) or 0)
            frac = (vram / size) if size else 0.0
            return {"size": size, "size_vram": vram, "gpu_fraction": frac}
    return {}


def model_placement(model_name: str) -> dict:
    """Where is `model_name` running? Returns
        {"size", "size_vram", "gpu_fraction"}  (gpu_fraction in 0..1)
    or {} when the model isn't currently loaded."""
    return _placement_in(get_running_models(), model_name)


def model_location(model_name: str) -> dict:
    """Where the model runs, for the header — read from the Ollama server
    itself (/api/ps), so it is right when Ollama runs on another machine.

    state: "gpu" | "split" | "cpu" (+ gpu_fraction, vram_gb, size_gb),
           "unloaded" (Ollama answers, the model isn't in memory now),
           "cloud" (runs on ollama.com), "offline" (Ollama didn't answer).
    """
    from .ollama_cloud import is_cloud
    if is_cloud(model_name):
        return {"state": "cloud"}
    try:
        response = requests.get(f"{config.ollama_api_url}/api/ps", timeout=3)
        response.raise_for_status()
        models = response.json().get("models", []) or []
    except Exception as exc:
        log.debug("listing running models failed: %s", exc)
        return {"state": "offline"}
    p = _placement_in(models, model_name)
    if not p:
        return {"state": "unloaded"}
    frac = p["gpu_fraction"]
    # Ollama rounds layer sizes; a sliver short of 100% is still "all on GPU".
    state = "gpu" if frac >= 0.99 else "split" if frac > 0.01 else "cpu"
    return {
        "state": state,
        "gpu_fraction": 1.0 if state == "gpu" else 0.0 if state == "cpu" else round(frac, 2),
        "vram_gb": round(p["size_vram"] / 1024 ** 3, 1),
        "size_gb": round(p["size"] / 1024 ** 3, 1),
    }

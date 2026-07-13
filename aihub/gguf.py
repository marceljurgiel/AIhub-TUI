"""
AIHub — minimal GGUF header reader + chat-format detection.

Reads just the metadata key/value section of a .gguf file (never the tensor
data) to recover `tokenizer.chat_template` and `general.architecture`. Used
when importing a GGUF into Ollama: a bare import gets the raw '{{ .Prompt }}'
template — no chat wrapping, no stop tokens — which makes models babble.
We detect the model's chat format and install a matching Ollama Go template.
"""
from __future__ import annotations

import struct
from typing import Dict, Set, Tuple

# GGUF value type → byte size (fixed-size scalars).
_SIMPLE = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
_STRING = 8
_ARRAY = 9


def read_metadata(path: str, wanted: Set[str], max_kv: int = 1024) -> Dict[str, str]:
    """Return {key: string_value} for the wanted string keys in a GGUF header.
    Silently returns what it found (possibly {}) on any parse problem."""
    out: Dict[str, str] = {}
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"GGUF":
                return out
            version = struct.unpack("<I", f.read(4))[0]
            if version < 2:            # v1 used 32-bit counts; not worth supporting
                return out
            f.seek(8, 1)               # tensor count
            n_kv = struct.unpack("<Q", f.read(8))[0]

            def read_str() -> bytes:
                n = struct.unpack("<Q", f.read(8))[0]
                return f.read(n)

            def skip_value(vtype: int) -> None:
                if vtype in _SIMPLE:
                    f.seek(_SIMPLE[vtype], 1)
                elif vtype == _STRING:
                    n = struct.unpack("<Q", f.read(8))[0]
                    f.seek(n, 1)
                elif vtype == _ARRAY:
                    etype = struct.unpack("<I", f.read(4))[0]
                    count = struct.unpack("<Q", f.read(8))[0]
                    if etype in _SIMPLE:
                        f.seek(_SIMPLE[etype] * count, 1)
                    elif etype == _STRING:
                        for _ in range(count):
                            n = struct.unpack("<Q", f.read(8))[0]
                            f.seek(n, 1)
                    else:
                        raise ValueError("nested arrays unsupported")
                else:
                    raise ValueError(f"unknown GGUF value type {vtype}")

            for _ in range(min(n_kv, max_kv)):
                key = read_str().decode("utf-8", "replace")
                vtype = struct.unpack("<I", f.read(4))[0]
                if key in wanted and vtype == _STRING:
                    out[key] = read_str().decode("utf-8", "replace")
                else:
                    skip_value(vtype)
                if len(out) == len(wanted):
                    break
    except Exception:
        pass
    return out


# ── Chat-format detection ─────────────────────────────────────────────────────

# family → (Ollama Go template, stop tokens)
CHAT_TEMPLATES: Dict[str, Tuple[str, list]] = {
    "chatml": (
        "{{- range .Messages }}<|im_start|>{{ .Role }}\n"
        "{{ .Content }}<|im_end|>\n"
        "{{ end }}<|im_start|>assistant\n",
        ["<|im_end|>"],
    ),
    "llama3": (
        "{{- range .Messages }}<|start_header_id|>{{ .Role }}<|end_header_id|>\n\n"
        "{{ .Content }}<|eot_id|>{{ end }}"
        "<|start_header_id|>assistant<|end_header_id|>\n\n",
        ["<|eot_id|>"],
    ),
    "gemma": (
        "{{- range .Messages }}<start_of_turn>"
        "{{ if eq .Role \"assistant\" }}model{{ else }}user{{ end }}\n"
        "{{ .Content }}<end_of_turn>\n"
        "{{ end }}<start_of_turn>model\n",
        ["<end_of_turn>"],
    ),
    "mistral": (
        "{{- range .Messages }}"
        "{{ if eq .Role \"assistant\" }}{{ .Content }}</s>"
        "{{ else }}[INST] {{ .Content }} [/INST]{{ end }}"
        "{{ end }}",
        ["</s>"],
    ),
    "phi": (
        "{{- range .Messages }}<|{{ .Role }}|>\n"
        "{{ .Content }}<|end|>\n"
        "{{ end }}<|assistant|>\n",
        ["<|end|>"],
    ),
}


def detect_chat_format(path: str) -> str:
    """Best-effort chat format of a GGUF ('chatml', 'llama3', …, or '').
    Prefers the embedded Jinja chat template's control tokens; falls back to
    the architecture name."""
    meta = read_metadata(path, {"tokenizer.chat_template", "general.architecture"})
    tpl = meta.get("tokenizer.chat_template", "")
    arch = (meta.get("general.architecture") or "").lower()

    if "<|im_start|>" in tpl:
        return "chatml"
    if "<|start_header_id|>" in tpl:
        return "llama3"
    if "<start_of_turn>" in tpl:
        return "gemma"
    if "<|user|>" in tpl and "<|end|>" in tpl:
        return "phi"
    if "[INST]" in tpl:
        return "mistral"

    if arch.startswith(("qwen", "lfm", "deepseek")):
        return "chatml"
    if arch.startswith("gemma"):
        return "gemma"
    if arch.startswith("phi"):
        return "phi"
    if arch.startswith("mistral"):
        return "mistral"
    return ""

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
#
# The chatml / llama3 / gemma templates include .Tools / .ToolCalls sections
# (modelled on Ollama's official qwen2.5 / llama3.1 library templates) —
# Ollama derives the "tools" capability from the template, so without these
# an imported model is reported as not supporting tool calling at all.
_CHATML_TOOLS = (
    "{{- if or .System .Tools }}<|im_start|>system\n"
    "{{- if .System }}\n{{ .System }}\n{{- end }}\n"
    "{{- if .Tools }}\n"
    "# Tools\n\n"
    "You may call one or more functions to assist with the user query.\n\n"
    "You are provided with function signatures within <tools></tools> "
    "XML tags:\n<tools>\n"
    "{{- range .Tools }}\n{\"type\": \"function\", \"function\": {{ .Function }}}\n"
    "{{- end }}\n</tools>\n\n"
    "For each function call, return a json object with function name and "
    "arguments within <tool_call></tool_call> XML tags:\n"
    "<tool_call>\n{\"name\": <function-name>, \"arguments\": <args-json-object>}\n"
    "</tool_call>\n"
    "{{- end }}<|im_end|>\n"
    "{{ end }}"
    "{{- range $i, $_ := .Messages }}"
    "{{- $last := eq (len (slice $.Messages $i)) 1 -}}"
    "{{- if eq .Role \"user\" }}<|im_start|>user\n"
    "{{ .Content }}<|im_end|>\n"
    "{{ else if eq .Role \"assistant\" }}<|im_start|>assistant\n"
    "{{ if .Content }}{{ .Content }}"
    "{{- else if .ToolCalls }}<tool_call>\n"
    "{{ range .ToolCalls }}{\"name\": \"{{ .Function.Name }}\", "
    "\"arguments\": {{ .Function.Arguments }}}\n{{ end }}</tool_call>"
    "{{- end }}{{ if not $last }}<|im_end|>\n{{ end }}"
    "{{- else if eq .Role \"tool\" }}<|im_start|>user\n"
    "<tool_response>\n{{ .Content }}\n</tool_response><|im_end|>\n"
    "{{ end }}"
    "{{- if and (ne .Role \"assistant\") $last }}<|im_start|>assistant\n"
    "{{ end }}"
    "{{- end }}"
)

_LLAMA3_TOOLS = (
    "{{- if or .System .Tools }}<|start_header_id|>system<|end_header_id|>\n"
    "{{- if .System }}\n\n{{ .System }}\n{{- end }}\n"
    "{{- if .Tools }}\n"
    "You are a helpful assistant with tool calling capabilities. When you "
    "receive a tool call response, use the output to format an answer to "
    "the original user question.\n{{- end }}<|eot_id|>\n"
    "{{- end }}"
    "{{- range $i, $_ := .Messages }}"
    "{{- $last := eq (len (slice $.Messages $i)) 1 }}"
    "{{- if eq .Role \"user\" }}<|start_header_id|>user<|end_header_id|>\n"
    "{{- if and $.Tools $last }}\n\n"
    "Given the following functions, please respond with a JSON for a "
    "function call with its proper arguments that best answers the given "
    "prompt.\n\nRespond in the format "
    "{\"name\": function name, \"parameters\": dictionary of argument name "
    "and its value}. Do not use variables.\n\n"
    "{{ range $.Tools }}{{- . }}\n{{ end }}\n{{ .Content }}<|eot_id|>"
    "{{- else }}\n\n{{ .Content }}<|eot_id|>{{- end }}"
    "{{ if $last }}<|start_header_id|>assistant<|end_header_id|>\n\n{{ end }}"
    "{{- else if eq .Role \"assistant\" }}"
    "<|start_header_id|>assistant<|end_header_id|>\n"
    "{{- if .ToolCalls }}\n"
    "{{ range .ToolCalls }}{\"name\": \"{{ .Function.Name }}\", "
    "\"parameters\": {{ .Function.Arguments }}}{{ end }}"
    "{{- else }}\n\n{{ .Content }}{{- end }}"
    "{{ if not $last }}<|eot_id|>{{ end }}"
    "{{- else if eq .Role \"tool\" }}<|start_header_id|>ipython<|end_header_id|>\n\n"
    "{{ .Content }}<|eot_id|>"
    "{{ if $last }}<|start_header_id|>assistant<|end_header_id|>\n\n{{ end }}"
    "{{- end }}"
    "{{- end }}"
)

_GEMMA_TOOLS = (
    "{{- if .Tools }}<start_of_turn>user\n"
    "You can call functions. To call one, reply ONLY with a JSON object "
    "inside <tool_call></tool_call> tags:\n"
    "<tool_call>{\"name\": <function-name>, \"arguments\": "
    "<args-json-object>}</tool_call>\n\nAvailable functions:\n"
    "{{- range .Tools }}\n{\"type\": \"function\", \"function\": {{ .Function }}}"
    "{{- end }}<end_of_turn>\n{{ end }}"
    "{{- range $i, $_ := .Messages }}"
    "{{- $last := eq (len (slice $.Messages $i)) 1 }}"
    "{{- if or (eq .Role \"user\") (eq .Role \"system\") }}<start_of_turn>user\n"
    "{{ .Content }}<end_of_turn>\n"
    "{{ if $last }}<start_of_turn>model\n{{ end }}"
    "{{- else if eq .Role \"tool\" }}<start_of_turn>user\n"
    "<tool_response>\n{{ .Content }}\n</tool_response><end_of_turn>\n"
    "{{ if $last }}<start_of_turn>model\n{{ end }}"
    "{{- else if eq .Role \"assistant\" }}<start_of_turn>model\n"
    "{{- if .ToolCalls }}\n"
    "{{ range .ToolCalls }}<tool_call>{\"name\": \"{{ .Function.Name }}\", "
    "\"arguments\": {{ .Function.Arguments }}}</tool_call>{{ end }}"
    "{{- else }}\n{{ .Content }}{{- end }}"
    "{{ if not $last }}<end_of_turn>\n{{ end }}"
    "{{- end }}"
    "{{- end }}"
)

CHAT_TEMPLATES: Dict[str, Tuple[str, list]] = {
    "chatml": (_CHATML_TOOLS, ["<|im_end|>"]),
    "llama3": (_LLAMA3_TOOLS, ["<|eot_id|>"]),
    "gemma":  (_GEMMA_TOOLS, ["<end_of_turn>"]),
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

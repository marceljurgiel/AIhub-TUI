# Changelog

## [1.1.1] - 2026-10-07
### Fixed
- Light theme: the logo gradient faded to near-white and disappeared; on a
  light canvas it now runs from dark to the accent.

### Added
- A screenshot of four themes in the README (`docs/media/themes.png`).

## [1.1.0] - 2026-10-07
### Added
- Themes: AIhub, Tokyo Night, Catppuccin, Dracula, Nord, Gruvbox and Light,
  plus an accent colour over any of them (purple, blue, cyan, green, amber,
  orange, pink, red). Menu → Theme (`T`, `F2`): ↑↓ theme, ←→ accent, the
  whole app previews live, Enter keeps it (saved in config.yaml as `theme` /
  `accent`), Esc restores. The saved theme is applied before the first frame.

### Fixed
- Very short terminals: the model card shrinks to one line before any menu
  item is cut off; at 24 rows the boxed card stays.

## [1.0.0] - 2026-10-07
The first public release of the new AIhub: the OpenTUI terminal app (`app/`)
on top of the Python engine (`aihub/`), in one repository with one version.

### Added
- One-line installers for Linux/macOS (`install.sh`) and Windows
  (`install.ps1`). No admin rights needed. They bring uv + Python 3.12, Bun and the `aihub`
  command, and offer to install Ollama, use an Ollama server or skip it,
  plus a starter model sized to the machine's RAM. Re-running = update.
- MCP: client for stdio and HTTP servers, a manager window and a one-click
  catalog (GitHub, Gmail, Google Calendar/Drive, Notion, Obsidian, Fetch,
  Git, Playwright, Context7, Home Assistant), import from Claude's config.
- Image attachments for vision models (Ctrl+V, drag and drop a file).
- Ollama Cloud models; capability badges (tools, vision, thinking, cloud).
- Temperature editor (Ctrl+T); slimmer footer.
- Demo GIFs and screenshots in the README, recorded with VHS from scripts in
  `docs/media/` (re-record with `docs/media/record.sh`).
- Windows support: PowerShell for `run_terminal`, Windows venv paths, MCP
  `.exe`/`.cmd` resolution, clipboard images, `C:\` and `file:///C:/` paths.

### Changed
- Context size is computed from the model's real dimensions (layers, KV
  heads, head size; hybrid models count attention layers only) instead of
  guessing from the name, which underestimated e.g. llama3.2:3b by 2×.
- A request that runs out of GPU memory is retried with half the context,
  and the size that fit is remembered.
- Model fit is a relative score; lists are sorted best fit first.
- Memory appends instead of replacing and guards against mass "forget".
- A local Ollama that is installed but not running is started in the
  background when AIhub opens (and by the installer).
- Without a GPU the context is sized from RAM (up to 8K) instead of a fixed 2K.
- Windows: `run_terminal` output is UTF-8 and no longer cut at 120 columns;
  `aihub cli` prints on cp1252 consoles; real VRAM from the driver registry
  (WMI caps it at 4 GB). Tests never touch the real profile (USERPROFILE).
- Windows console: characters the default font lacks (↵ ▎ ✓ ⌘ braille
  spinner…) are swapped for ones it has (`enter`, ▌, √, »,  | / - \) in one
  place, the JSX runtime (`app/src/jsx`); `AIHUB_GLYPHS=unicode` opts out.
- Updates never half-delete: the old install is moved aside first, and if
  something holds it open the installer stops with "nothing was changed".
  Ollama started by AIhub runs from the home folder so it can't lock it.
- The sidebar says CONNECTED (yellow dot) when Ollama is up but no model is
  picked yet, and CONNECTING before the first check, instead of OFFLINE.
- Replies are styled again: the Markdown styles used names the parser never
  emits, so bold, headings, lists and code were plain text. They now use the
  grammar's `markup.*` captures (tested).
- The model picker says "loading your models…" instead of "no matches"
  while the list loads; retired cloud models aren't asked about again.
- "1 message", not "1 messages".
- The Memory window uses the terminal's height: in a fixed 20-row window
  freshly learned facts sat below the fold and looked unsaved.

### Removed
- GPUtil (broken on Python 3.12: needs distutils); nvidia-smi is read directly.

- The Textual TUI (`aihub/tui`); the OpenTUI app replaces it. The command
  line tools remain as `aihub cli` / `aihub-cli`.

## [0.3.29] - 2026-10-02
### Fixed
- GPU detection invented hardware: with the `rocm-smi` package installed but
  no AMD GPU (an Intel-only laptop) it reported "AMD Radeon, 8192 MB", and
  any AMD/NVIDIA line in `lspci` also became 8 GB. Unknown VRAM is now 0, and
  only display controllers count.
- Model fit described the wrong machine: it used this PC's (made-up) GPU
  while Ollama runs on a server. New `aihub/target.py` profiles the machine
  behind the configured Ollama: local → real hardware; remote → learned from
  chats (each turn records tok/s and how much of the model sat in GPU memory
  via /api/ps → effective bandwidth and VRAM bounds), overridable with the
  new `ollama_gpu_memory_gb` setting. `recommend_context` uses it too.
- Speed estimates were ~4× too high (assumed 180 GB/s for "AMD"); they now
  come from measured bandwidth (tok/s ≈ bandwidth / model size; MoE uses
  active params). On a Radeon 680M iGPU test server: qwen3:8b ≈ 6.7 tok/s
  estimated vs 6.5–8 measured.
- The fit score saturated (most models 100, 0.6B tied with 8B, always q8_0).
  New score: capability (log size) × speed × placement × popularity ×
  tool support × freshness, with real q4_K_M sizes.
### Added
- `aihub/catalog.py`: live catalogs cached in ~/.aihub/cache — the official
  ollama.com library (240 models, capabilities, size variants, pulls,
  updated; per-variant download sizes from /tags pages) and the most
  downloaded GGUF chat models from trusted Hugging Face publishers.
  Bridge `catalog.refresh` (run at startup), `target.info`;
  `models.recommend`, `ollama.library` and `hf.gguf` serve the cache with
  fit + estimated tok/s per row.

## [0.3.28] - 2026-10-02
### Changed
- The memory learner is built for a small model: a code pre-filter only
  passes messages where the user talks about themself; quoted passages,
  pasted code and sentences about other people are cut out first; the model
  only lists {topic, fact, still_true}; code decides add / update / forget,
  turns a misfiled "I don't have X any more" into forget (or replace when the
  user names a successor), drops facts the user never said and questions
  posing as facts, and treats inflected restatements as already known.
- Default `memory_model` is `llama3.2:3b`, chosen with `scripts/memory_eval.py`
  (tuning + held-out sets): 28/32 on the GPU server at ~4.5 s, with only
  misses and no wrong writes. gemma3:4b 27/32, gemma3:1b 25/32 (wrote a
  question as the user's name), phi4-mini 18/32, Liquid LFM2 1.2B 55% /
  40%; qwen3 hangs in JSON mode with thinking off and wedged the server.
- `chat_json` caps generation (`num_predict`) and the memory model unloads
  right after (`keep_alive: 0`); `memory_ollama_url` can point it at another
  Ollama (e.g. this PC's CPU).

## [0.3.27] - 2026-09-29
### Added
- Automatic memory (`aihub/memory_learn.py`): learns durable facts about the
  user from chats with a dedicated small memory model (Ollama structured
  output, thinking off), whatever backend the chat used. Only the user's own
  messages are read — never tool results, files or web pages — so quoted text
  can't inject facts. Bridge `memory.learn {messages, cursor}` examines each
  message once; background learning requires an explicit `memory_model`
  (it never falls back to a thinking chat model, which hangs in JSON mode).
- `aihub/memory_ops.py`: every memory write (auto-learning, the `remember`
  tool, `/memory save`) goes through one deterministic layer — add / update /
  forget on "## Topic" entries, case-insensitive topic match, dedupe (also
  across topics), op and length caps, and a secret filter (passwords, PINs,
  API keys, tokens) for anything the model proposes. Changes are logged to
  `changes.jsonl`; bridge `memory.undo` reverts the last batch (or given ids)
  unless the user edited the topic since.
- Config: `memory_auto`, `memory_model`, `history_autosave`; `chat.finalize`
  with `auto` honours autosave (Ctrl+S always saves).
- `scripts/memory_eval.py`: 20-case benchmark for choosing the memory model.
### Changed
- `/memoryadd` uses the learner: updates topics instead of appending another
  "Facts Extracted on …" block, and works for API / llama.cpp chats.

## [0.3.26] - 2026-09-28
### Added
- `remember` tool: the model saves a lasting fact about the user to memory
  when asked ("zapamiętaj…", "remember…") or when the user states a durable
  preference; an existing topic is updated. Before, a model asked to remember
  something answered "saved to memory" while nothing was stored. It refuses
  with a clear message when memory is off. The chat tool gate recognises
  memory requests (Polish and English).
### Fixed
- Memory only reached the model if it was on when the chat started, and
  edits made during a chat were invisible until a new one. The bridge now
  rebuilds the system prompt (instructions + environment + memory) on every
  turn — agent turns included, which never saw memory before.
- The memory instructions ask the model to use facts when relevant rather
  than "personalise every response" (which made models recite them).
  Live check with qwen3:8b: answers name/OS and the GPU server address from
  memory, leaves memory out of "12×12", saves and later recalls a new fact.

## [0.3.25] - 2026-09-28
### Added
- Reasoning streams: thinking models (qwen3, deepseek-r1…) send their
  reasoning separately (Ollama `message.thinking`, OpenAI-compatible
  `reasoning_content`). The engine ignored it, so a thinking model looked
  frozen — qwen3:8b on a test GPU thought for 100+ s before its first
  word. It is now emitted as `ThinkingChunk` (bridge event `thinking`) for the
  UI to show; it is never added to the history.

## [0.3.24] - 2026-09-28
### Added
- Bridge `ollama.check {url}`: is there an Ollama server at this address?
  Returns its version, or a plain-language reason (timeout, connection
  refused, not Ollama). Used by the OpenTUI settings before saving.
- Bridge `workdir.set {path}` (OpenTUI `/cd`): a session-only working
  directory for tools, taking precedence over `project_dir`; relative paths
  resolve from the current one; "" drops the override.
- Chat turns refresh the environment block of the system prompt, so the
  model sees the current working directory after `/cd` or a settings change.
### Changed
- `config.set` validates before writing: `ollama_api_url` is normalised
  (`192.0.2.10` → `http://192.0.2.10:11434`), `project_dir` must be an
  existing directory (or empty); a bad field rejects the whole patch instead
  of leaving it half-applied. It returns the effective `workdir` too.
### Fixed
- The test suite wrote to the user's real `~/.aihub/config.yaml` (a Textual
  test added "odd[/]name" to recent models). Tests now run with a throwaway
  HOME.

## [0.3.23] - 2026-09-28
### Fixed
- "Save it on my desktop" wrote the file somewhere else: the model didn't
  know where the desktop was and used a relative path, which resolved against
  the engine process's cwd — under OpenTUI that is the engine checkout
  (`~/AIhub-TUI`), not where the user launched `aihub`. Tools now resolve
  relative paths against one working directory (`aihub/tools/workdir.py`):
  `project_dir` if set, else the launch directory (AIHUB_WORKDIR from the
  front-end), else the cwd; `run_terminal` runs there too. File tools report
  the absolute path they touched.
- The system prompt now includes the environment: OS, home, Desktop /
  Documents / Downloads (from XDG user-dirs, so localised folders like
  `~/Pulpit` are right), working directory and date. Replaying "save test.txt
  on the desktop" with qwen3:8b: 3/3 files on the (localised) desktop.
- `project_dir` in config was never used by the engine; it now sets the
  tools' working directory. `config.get` reports the effective `workdir`.
- Agent turns over the bridge ran under the plain chat prompt — the plan/build
  agent prompt was never applied. The bridge now uses it (plus the
  environment) for agent turns, without changing the front-end's history.
### Added
- The bridge logs every tool call (name, arguments, outcome) to stderr, i.e.
  to OpenTUI's `~/.aihub/opentui-bridge.err.log`.

## [0.3.22] - 2026-09-27
### Fixed
- Asking a small model (llama3.2:3b) to save a file failed 5/5 times: it
  picked edit_file, which can't create files, and then told the user the file
  was saved (or "blocked by system security"). The write_file/edit_file
  descriptions no longer push models to edit_file ("ALWAYS prefer edit_file"),
  edit_file on a missing file tells the model to use write_file, and the
  system prompt requires reporting tool results truthfully. Same prompt
  after the fix: 5/5 files written; with the user declining, 5/5 replies say
  it wasn't done because the user declined.
- Tool failures were reported as successes: tools signal failure in-band
  ("[Edit Error] …", "[Exit: 1]") so `ToolCallResult.error` stayed None.
  `chat.tool_failure()` now detects them; denials set the new
  `ToolCallResult.denied` (forwarded by the bridge) and give the model an
  explicit "was NOT run — the user declined" result.

## [0.3.21] - 2026-09-27
### Fixed
- `/memory save` and memory extraction could wipe the whole memory file: when
  reading it failed (bad encoding, permissions) `load_memory()` returned ""
  and the write replaced everything with the one new entry. Writers now read
  strictly and fail instead; display paths still degrade to "no memory".
- A config.yaml with one invalid value was silently replaced by all
  defaults, and the next settings save overwrote the user's file, API keys
  included. Invalid fields now fall back one at a time; an unparseable file is
  copied to `config.yaml.broken-<timestamp>` first.
- A failed session save was reported to the front-end as "Nothing to save."
  The bridge now returns an error; a failed prune after a successful save no
  longer marks the save as failed. Loading a corrupt session file is an error
  instead of an empty session.
- The plain-chat tool gate matched substrings ("run" in "running", "/" in
  "2/3", "list" in "a list of"), offering tools to ~28–48% of ordinary
  messages while missing Polish requests and commands like `git status`. It
  now matches whole words and concrete shapes (paths, file names, URLs,
  commands), covers Polish, and keeps tools for a follow-up right after a
  tool was used. On a held-out set: 8% false offers (was 28%), 5% missed
  requests (was 45%).
### Changed
- Engine modules log failures to `aihub.*` loggers instead of swallowing
  them. The bridge sends these to stderr, which OpenTUI appends to
  `~/.aihub/opentui-bridge.err.log`. Ollama `chat_sync` errors now include
  the cause.

## [0.3.20] - 2026-09-27
### Fixed
- llama.cpp: the second round of any tool-using turn failed. The history went
  out in Ollama's shape — tool-call arguments as an object, results with no
  `tool_call_id` — and OpenAI-compatible servers reject that ("cannot
  unmarshal object into … arguments of type string"). Messages are now
  converted to the chat-completions format (`aihub/openai_format.py`); old
  saved sessions without ids are paired up in order.
- The engine stores every tool call with an `id` and `type`, and each tool
  result with `tool_call_id` + `tool_name`, so calls and results stay linked.
- Any HTTP 400 while tools were on was read as "model does not support
  tools": the turn was silently retried without tools and the real error
  (bad request, context too long…) was hidden. Only explicit messages ("does
  not support tools", llama-server's "--jinja") trigger the retry now.
- llama.cpp: `context_length` was sent as `max_tokens`, which caps the reply
  length, not the context. It is no longer sent (llama-server's context is
  set by `--ctx-size`).
- Textual TUI: an offline Ollama blocked chatting through the API and
  llama.cpp backends too.
### Added
- OpenAI API models now pass tools and parse tool calls (shared SSE parser
  with llama.cpp), and report token usage.
### Changed
- Agent mode is refused for Anthropic and Google API models with a clear
  reason. Their clients stream text only, so an agent on them could never
  call a tool — it used to be allowed anyway.

## [0.3.19] - 2026-09-27
### Fixed
- Bridge `chat.cancel` closed the engine generator at the next event, which
  could leave an assistant `tool_calls` entry without its tool results (the
  next request was then malformed) and dropped the partial reply from the
  returned history. The bridge now passes `cancel_check` to `run_chat_turn`,
  lets it end with `Done(cancelled=True)`, and stops emitting events once
  cancelled. The `final` event carries `cancelled`.

## [0.3.18] - 2026-09-27
### Fixed
- Typing a message containing an unmatched closing tag such as `a[/] b`
  crashed the whole TUI (`MarkupError: auto closing tag ('[/]') has nothing
  to close`); a model reply with the same text did too. Other brackets like
  `[b]` or `[red]` silently restyled or hid the text. User and assistant
  bubbles now render their text literally.
- The same crash could come from the session title (the first user message)
  in the top bar, the model name in the top/bottom bars and the sidebar, and
  outside text in system notices — backend errors, memory contents,
  memory-extraction output, resumed tool results, unknown slash commands,
  save paths. All of it is now markup-escaped.

## [0.3.17] - 2026-09-27
### Security
- Plain chat ran `run_terminal` (`shell=True`), `write_file` and `edit_file`
  with no confirmation. Tools are offered on a loose keyword match (a "/" or
  "run" in the message is enough), so any loaded model could run a shell
  command during ordinary conversation. Mutating tools now always ask outside
  agent Build mode: the TUI shows the permission modal, `aihub chat` asks
  `Allow …? [y/N]` (EOF/Ctrl+C denies), and the bridge sends
  `permission_request` for chat turns too — front-ends must answer it with
  `chat.permission` (or `chat.cancel`) outside agent mode as well.
- The permission modal and the CLI tool panel rendered model-supplied
  arguments as Rich markup, so a model could restyle or hide part of the
  command the user was approving. Both now show it literally.

## [0.3.16] - 2026-09-27
### Fixed
- Esc did not actually stop a reply. The worker thread kept reading the
  stream, the backend kept generating, and tool calls — including
  `run_terminal` — still ran after "Stream cancelled." `run_chat_turn` now
  takes a `cancel_check` polled between stream chunks, before each tool and
  after an approval prompt; on cancel it closes the backend stream (every
  client now closes its HTTP response, so Ollama / llama.cpp stop generating)
  and ends with `Done(cancelled=True)`. Partial text is kept; tool calls that
  never ran get a "[Cancelled by user]" result so the history stays valid.
- A cancelled turn's worker could keep appending to the live message list
  while a new turn ran on it, and its trailing `Done` flipped the new turn's
  streaming flag off. Each turn now has an id and runs on its own copy of the
  messages, handed back in a single `TurnFinished`; events from superseded
  turns are dropped. Clearing the chat, starting a new chat or switching
  model mid-reply abandons the running turn instead of being overwritten.
- The stream worker posted `Done` twice per turn (its `finally` ran after
  the early `return`). Exactly one `Done` is posted now.
### Added
- First test suite (`pytest`, `pip install -e .[dev]`): chat engine
  cancellation, worker termination, and ChatScreen turn bookkeeping.

## [0.3.15] - 2026-08-21
### Changed
- TUI visual refresh. Same layout, same navigation, same ASCII logo — the pass
  is styling only:
  - Surfaces now form a four-step ramp (canvas → chrome → raised → selected)
    instead of three, so inputs, tool panels and selected rows separate without
    extra borders. Separator dots and bar troughs moved from `#2a2a30` to
    `#33333e`, which was too dim to read on the chrome colour.
  - Every border is `round`. The heavy `tall` borders on inputs, text areas and
    option lists are gone — they were the most dated element on screen.
  - Focus is signalled by an accent border plus a lifted surface, and never by
    a change in geometry, so nothing shifts when focus moves.
  - Modal titles moved into the border (`border_title`), with the key hints as
    a right-aligned `border_subtitle`. Each modal gets a content row back.
  - Buttons, tabs, checkboxes, selects, option lists, data tables, progress
    bars, scrollbars and tooltips are themed from the palette; stock Textual
    styling no longer shows through.
  - Message bodies are indented under their role header; the slash popup
    highlights a full-width band and keeps one command per row.
  - Sidebar nav rows highlight as a band on hover and when active.
### Fixed
- The Help modal listed two contradictory keybinding tables. The stale one
  (advertising Ctrl+M / Ctrl+H / Ctrl+I) is gone; help now renders only
  `slash.HELP_TEXT`, plus the single-key nav shortcuts, which were undocumented.
- The sidebar advertised "⌘K palette"; the binding is Ctrl+P.
- `aihub --help` and the model registry table reported a hard-coded "AIHub
  0.2.0" — both now read `__version__`.
- Memory modal buttons stacked vertically on the left instead of sitting in a
  right-aligned row.

## [0.3.14] - 2026-08-04
### Added
- `aihub/bridge.py`: an NDJSON-over-stdio bridge that exposes the engine to an
  external front-end (the new OpenTUI/TypeScript UI). Thin adapter — every
  method delegates to existing functions (chat streaming, model management,
  hardware, fit, history, memory, tools). Threaded dispatch with a single
  write lock, per-request cancellation, and a permission round-trip for agent
  plan mode. Run via `python -m aihub.bridge` or the new `aihub-bridge` script.
- `aihub/downloads.py`: reusable Xet-aware HuggingFace GGUF download
  (`hf_download`) with a plain progress callback, extracted from the Textual
  GGUF picker so any front-end can reuse it.

## [0.3.13] - 2026-07-14
### Fixed
- Imported GGUFs were flagged "does not support tool calling" (agent mode
  blocked). aihub checks Ollama's `/api/show` capabilities — which Ollama
  derives from the chat template — and the templates injected at import had
  no tool sections. ChatML / Llama 3 / Gemma templates now carry
  `.Tools`/`.ToolCalls` blocks (modelled on Ollama's official qwen2.5 /
  llama3.1 library templates); imports now report `['completion','tools']`.
- Existing imports self-heal: picking a model whose installed template
  differs from the current one triggers a one-time re-import.
### Added
- Client-side fallback tool-call parser in the chat engine: recovers calls
  emitted as bare JSON, ```json fences, or <tool_call> tags with a known
  tool name (Ollama 0.20's template parser only extracts exact-prefix
  matches). Unknown tool names are rejected.

## [0.3.12] - 2026-07-14
### Fixed
- HuggingFace GGUF downloads returned 403 AccessDenied: HF's CAS bridge
  (plain `resolve/…` HTTP) rejects large files (huggingface/xet-core#592),
  while small files still work. Downloads now use `huggingface_hub` (Xet
  protocol) with a size-poller feeding the in-app progress bar; hf_hub's
  own tqdm bars are disabled so they can't corrupt the TUI. Raw HTTP kept
  as fallback with a friendlier 401/403 message (suggests adding a free HF
  token in Settings).
- Post-download dialog no longer shows stale llama-server instructions —
  it now points at the auto-import-and-run flow.
### Added
- Dependency: `huggingface_hub[hf_xet]`.

## [0.3.11] - 2026-07-13
### Fixed
- GGUFs imported into Ollama replied with gibberish (raw numbers/code on
  "hi"): the import installed no chat template, leaving Ollama's raw
  `{{ .Prompt }}` — no role wrapping, no stop tokens.
### Added
- `aihub/gguf.py`: minimal GGUF header reader (metadata only, never tensor
  data) + chat-format detection from the embedded `tokenizer.chat_template`
  / architecture. Import now sets the matching Ollama Go template and stop
  tokens (ChatML, Llama 3, Gemma, Mistral, Phi families).
- Self-heal: picking a previously-imported model that still has the raw
  template triggers a one-time re-import with the proper template.

## [0.3.10] - 2026-07-13
### Changed
- Downloaded GGUFs now run touchlessly: first pick auto-imports into Ollama
  (no confirm dialog; progress in the status line; double-trigger guarded),
  then opens the context modal to chat. Already-imported files are detected
  (row shows "✓ imported · Enter to run") and start instantly without
  re-importing. Incomplete downloads (<50 MB) are blocked with a warning
  instead of failing mid-import.

## [0.3.9] - 2026-07-13
### Fixed
- HuggingFace GGUF tab showed `?GB` for every model and quantisation: the HF
  search API returns no per-file sizes (and now often no file lists at all),
  and the detail endpoint omits sizes without `?blobs=true`. Detail info is
  now fetched with `blobs=true` concurrently (8 workers) for all search
  results, size parsing falls back to `lfs.size`, and the quant picker
  re-fetches when it was handed a sizeless file list.

## [0.3.8] - 2026-07-13
### Fixed
- Sidebar clicks were dead: `NavItem.Pressed` had no handler anywhere, so
  clicking New Chat (or Models, Settings, …) silently did nothing — the old
  conversation kept feeding the model, which made small models answer "hi"
  with off-topic nonsense. ChatScreen now routes sidebar clicks through the
  same dispatcher as the command palette.
- New Chat now also resets session token counters, ctx fill, tok/s, and
  agent mode (previously carried over into the "fresh" session).

## [0.3.7] - 2026-07-13
### Fixed
- Models downloaded through the Recommended / HuggingFace GGUF tabs were
  invisible afterwards: files landed in `models_download_dir` but the
  Installed tab only listed Ollama models and the currently-loaded
  llama-server model.
### Added
- Installed tab lists all downloaded `.gguf` files (size shown; suspected
  partial downloads flagged red). Enter offers importing the file into
  Ollama (`ollama_client.import_gguf_model`: sha256 blob upload +
  /api/create, with legacy Modelfile fallback) so it becomes a regular
  installed model; `X` deletes the file. Post-download flow routes into the
  same import/use path.

## [0.3.6] - 2026-07-09
### Changed
- Header device counter now follows where the model actually runs: shows a CPU
  counter when Ollama reports the model is CPU-resident, GPU stats otherwise
  (polled from /api/ps every 4 s alongside usage).
- Settings modal redesigned into four tabs (General · Performance · Connections ·
  API Keys) with a detected-GPU info line on the Performance tab. Widget ids and
  save logic unchanged.

## [0.3.5] - 2026-07-09
### Changed
- Removed the duplicate context counter from the bottom footer bar; the top
  header already shows it. Footer right side is now `tok/s · clock`.

## [0.3.4] - 2026-06-12
### Fixed
- AMD GPU detection called `rocm-smi --showvram`, unsupported on newer ROCm; the
  resulting error/usage output leaked to the terminal and corrupted the TUI.
  Switched to `rocm-smi --showmeminfo vram --json` with version-tolerant key
  matching, and silenced stderr on all hardware subprocess calls.
### Added
- Real AMD VRAM size, card model name, and live GPU utilization from rocm-smi
  JSON (previously hardcoded 8 GB with unknown utilization) — feeds the header
  GPU readout, VRAM-fit context, and hardware scan.

## [0.3.3] - 2026-06-12
### Fixed
- Web search: `duckduckgo.com/html/` now returns an empty stub page, so queries
  silently returned no results. Switched to the `html.duckduckgo.com/html/` scrape
  host with a `lite.duckduckgo.com/lite/` fallback, handled the new direct-href
  format (dropped `uddg=` redirect), and filtered sponsored/ad results.

## [0.3.2] - 2026-06-11
### Added
- Tokens/sec counter in the header and footer, colour-coded (green = fast/GPU,
  red = slow/CPU); uses Ollama's `eval_duration` when available, else wall-clock.
### Changed
- Agent sessions auto-fit their context to free VRAM so they stay on the GPU
  instead of forcing a large window that spills to CPU.

## [0.3.1] - 2026-06-11
### Added
- Auto-fit chat context to detected VRAM, with a red warning when a chosen value
  would spill the KV cache to CPU.
- `ollama_num_gpu` force lever in Settings (0 = auto, 999 = force all layers on GPU).
- GPU placement check after the first response (GPU / partial / CPU) via `/api/ps`.

## [0.3.0] - 2026-06-11
### Added
- Reference UI redesign: top header bar, vim-style footer, sidebar with model pill
  and single-key navigation, markdown rendering in the chat log.
- Live token counter, GPU/CPU usage, `CONNECTED`/`OFFLINE` indicator, llmfit-style
  hardware-fit table in the model picker.
- App version shown in the sidebar; global `aihub` command via `install.sh`;
  self-healing `update.sh` for one-command updates.

## [0.2.0] - 2026-06-07
### Added
- Chat-first TUI rebuild on Textual — full-screen chat replaces the menu CLI.
- Cloud API models (Anthropic, OpenAI, Google) alongside local Ollama; optional
  llama.cpp backend.
- Agent mode (plan/build) ported from OpenCode; llmfit-based hardware-fit engine;
  7-tool calling system (terminal, read/write/edit/list files, web search, file search).

## [0.1.4] - 2026-04-12
### Added
- Browse & Manage Models redesigned: chat/agentic models only (image/video removed)
- Hardware-based filtering: models sorted by best-fit for available RAM/VRAM
- Installed models shown first with green highlight
- Capability badges (🔧 Tool Calling, 💻 Code, 🧠 Reasoning, etc.) on model cards
- Expanded model registry: 55+ models across all major families
- Category filter: Small / Medium / Large / XLarge
- Inline search by name or capability
- Memory system: per-model and global memory with auto-extraction
- Tool-calling agentic system with 6 built-in tools (terminal, file ops, web search, file search)

### Changed
- Full English UI (all commands, help strings, labels)
- OpenCode-inspired purple/violet TUI colour scheme (`#7c3aed`)

## [0.1.3] - 2026-03-26
### Added
- Configurable context length (num_ctx) for models via CLI and config.
- Automated model unloading (keep_alive=0) upon application exit or session end.
- Background threaded workers for TUI chat streaming (no more UI freezing).

### Fixed
- Critical UI-blocking bug in Textual TUI.
- History selection bug when browsing past sessions.
- Consolidated technical debt and improved type hints across all core modules.

All notable changes to this project are documented here.
This project follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] – 2025-03-13

### Added
- Persistent interactive TUI shell with arrow-key navigation (powered by `questionary` + `rich`)
- Hardware scanner: GPU (NVIDIA via `nvidia-smi`, AMD via `rocm-smi` / `lspci`, Windows via `wmic`), CPU, RAM, Disk
- Heuristic tokens/sec estimator per model based on detected VRAM
- Live Ollama model list merged with built-in registry at startup
- `get_local_model_sizes()` — model file size displayed in GB for all models (downloaded and not yet downloaded)
- Streaming chat sessions with configurable temperature
- API model stubs: `gpt-4o`, `claude-3-5-sonnet`
- Hardware-aware image generation pipeline (SD v1.5, FLUX-schnell)
- Hardware-aware video generation: LTX Video 2.3 (primary) → SVD (fallback)
- `install.sh` — automated one-shot installer for Linux (detects distro, installs Ollama + deps)
- Built-in model registry with 15 entries covering chat, image, and video models
- `~/.aihub/config.yaml` for persistent user settings (Ollama URL, default model, API keys)
- Windows GPU detection via `wmic` fallback
- Cross-platform file paths via `os.path.join`
- MIT license

### Changed
- Full English UI (all commands, help strings, labels)
- OpenCode-inspired purple/violet TUI colour scheme (`#7c3aed`)

---

## [Unreleased]

- Real OpenAI / Anthropic API integration
- Model search / filtering in TUI browser
- Profile-based configs (work / home)
- Plugin system for custom model backends

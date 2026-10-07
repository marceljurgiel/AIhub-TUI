import { useEffect, useRef, useState } from "react";
import { singleLinePaste } from "../clipboard.ts";
import { theme, fit } from "../theme.ts";
import { useBridge } from "../state/BridgeContext.tsx";
import { useModals } from "../state/ModalContext.tsx";
import { ModalShell } from "../ui/ModalShell.tsx";
import { SectionLabel } from "../ui/primitives.tsx";
import { useModalKeys } from "./modalKit.ts";
import type { SessionState } from "../state/SessionContext.tsx";

function ToggleRow({
  label,
  value,
  onToggle,
}: {
  label: string;
  value: boolean;
  onToggle: () => void;
}) {
  return (
    <box onMouseDown={onToggle}>
      <text>
        <span fg={theme.fg2}>{`  ${label.padEnd(19)}`}</span>
        <span fg={value ? theme.success : theme.fg2}>{value ? "[✓] on " : "[ ] off"}</span>
      </text>
    </box>
  );
}

/** One-line labelled text field. Click or Tab to focus. */
function FieldRow({
  label,
  value,
  placeholder,
  focused,
  onFocus,
  onInput,
  onSubmit,
}: {
  label: string;
  value: string;
  placeholder: string;
  focused: boolean;
  onFocus: () => void;
  onInput: (v: string) => void;
  /** Enter: receives the field's current text straight from the input. */
  onSubmit: (value: string) => void;
}) {
  // Updated on every keystroke, so Enter right after a paste sees the text
  // even before the parent's state has re-rendered.
  const latest = useRef(value);
  latest.current = value;
  return (
    // Fixed-size row: a long value must scroll inside the field, not widen it
    // (a pasted URL used to squeeze the label and push the rows below down).
    <box flexDirection="row" height={1} flexShrink={0} onMouseDown={onFocus}>
      <text flexShrink={0} fg={focused ? theme.accent : theme.fg2}>{`  ${label.padEnd(18)}`}</text>
      <box
        flexGrow={1}
        flexShrink={1}
        flexBasis={0}
        minWidth={0}
        height={1}
        overflow="hidden"
        marginRight={2}
        paddingLeft={1}
        backgroundColor={focused ? theme.bg3 : theme.bg2}
      >
        <input
          width="100%"
          onPaste={singleLinePaste}
          value={value}
          focused={focused}
          onInput={(v: string) => {
            latest.current = v;
            onInput(v);
          }}
          onSubmit={() => onSubmit(latest.current)}
          placeholder={placeholder}
          backgroundColor={focused ? theme.bg3 : theme.bg2}
          focusedBackgroundColor={theme.bg3}
          textColor={theme.fg0}
          placeholderColor={theme.fg2}
          cursorColor={theme.accent}
        />
      </box>
    </box>
  );
}

type FieldId = "ollama" | "gpuMem" | "workdir" | "model" | "ctx" | "memoryModel";
const FIELDS: FieldId[] = ["ollama", "gpuMem", "workdir", "model", "ctx", "memoryModel"];

/** On/off settings that save the moment they're flipped. */
type SwitchId = "tools" | "memory" | "autoLearn" | "autosave";
const SWITCHES: Record<SwitchId, { label: string; key: string; config: string; session?: "toolsEnabled" | "memoryEnabled" }> = {
  tools: { label: "Tool calling", key: "t", config: "tools_enabled", session: "toolsEnabled" },
  memory: { label: "Memory", key: "m", config: "memory_enabled", session: "memoryEnabled" },
  autoLearn: { label: "Auto-learn", key: "a", config: "memory_auto" },
  autosave: { label: "Autosave chats", key: "h", config: "history_autosave" },
};

export type EngineChange = {
  /** Effective tools working directory after the save. */
  workdir: string;
  /** The Ollama server address changed — models/status must be re-read. */
  ollamaChanged: boolean;
};

/** Engine settings (config.get / config.set) plus a context-size editor that
 *  consults hardware.recommend_context. */
export function SettingsModal({
  session,
  onPatchSession,
  onEngineChanged,
  onClose,
}: {
  session: SessionState;
  onPatchSession: (patch: Partial<SessionState>) => void;
  onEngineChanged?: (change: EngineChange) => void;
  onClose: () => void;
}) {
  const bridge = useBridge();
  const modals = useModals();
  const [cfg, setCfg] = useState<any>(null);
  const [ollama, setOllama] = useState("");
  const [workdir, setWorkdir] = useState("");
  const [model, setModel] = useState("");
  const [ctx, setCtx] = useState("");
  const [memoryModel, setMemoryModel] = useState("");
  // GPU memory of the machine running Ollama; empty = learned from chats.
  const [gpuMem, setGpuMem] = useState("");
  const [switches, setSwitches] = useState<Record<SwitchId, boolean>>({
    tools: true, memory: true, autoLearn: true, autosave: true,
  });
  const tools = switches.tools;
  const memory = switches.memory;
  const [focus, setFocus] = useState<FieldId | null>(null);
  const [status, setStatus] = useState<{ text: string; tone: "ok" | "warn" | "info" }>({ text: "", tone: "info" });
  const [saving, setSaving] = useState(false);
  const width = 72;

  useEffect(() => {
    bridge
      .request("config.get")
      .then((d) => {
        setCfg(d);
        setOllama(d.ollama_api_url ?? "");
        setWorkdir(d.project_dir ?? "");
        setModel(d.default_chat_model ?? "");
        setCtx(String(d.default_context_length ?? 2048));
        setMemoryModel(d.memory_model ?? "");
        setGpuMem(d.ollama_gpu_memory_gb ? String(d.ollama_gpu_memory_gb) : "");
        setSwitches({
          tools: !!d.tools_enabled,
          memory: !!d.memory_enabled,
          autoLearn: d.memory_auto !== false,
          autosave: d.history_autosave !== false,
        });
      })
      .catch((e) => setStatus({ text: `load failed: ${(e as Error).message}`, tone: "warn" }));
  }, []);

  /** `latest` carries the value of the field Enter was pressed in: after a
   *  paste + quick Enter, React state may not have caught up with the input. */
  const save = async (latest: Partial<Record<FieldId, string>> = {}) => {
    if (!cfg || saving) return;
    setSaving(true);
    setFocus(null);
    const v = { ollama, gpuMem, workdir, model, ctx, memoryModel, ...latest };
    const ctxN = parseInt(v.ctx, 10);
    const gpuN = v.gpuMem.trim() ? Number(v.gpuMem.trim().replace(",", ".")) : 0;
    if (!Number.isFinite(gpuN) || gpuN < 0 || gpuN > 1024) {
      setStatus({ text: `Not saved: GPU memory must be a number of GB (e.g. 8), or empty.`, tone: "warn" });
      setSaving(false);
      return;
    }
    const ollamaChanged = v.ollama.trim() !== (cfg.ollama_api_url ?? "");
    let note = "";
    try {
      if (ollamaChanged) {
        setStatus({ text: `checking ${v.ollama.trim()}…`, tone: "info" });
        const check = await bridge.request("ollama.check", { url: v.ollama });
        // Saved either way (the server may simply not be up yet), but say so.
        note = check.ok ? `  Ollama ${check.version} at ${check.url}.` : `  ⚠ ${check.url} unreachable: ${check.error}`;
      }
      const patch: Record<string, unknown> = {
        ollama_api_url: v.ollama,
        project_dir: v.workdir,
        default_chat_model: v.model.trim() || cfg.default_chat_model,
        memory_model: v.memoryModel.trim(),
        ollama_gpu_memory_gb: gpuN,
        default_context_length: Number.isFinite(ctxN) && ctxN >= 256 ? ctxN : 2048,
        tools_enabled: tools,
        memory_enabled: memory,
      };
      const d = await bridge.request("config.set", { patch });
      setCfg(d);
      setOllama(d.ollama_api_url ?? "");
      setWorkdir(d.project_dir ?? "");
      setGpuMem(d.ollama_gpu_memory_gb ? String(d.ollama_gpu_memory_gb) : "");
      onPatchSession({
        toolsEnabled: tools,
        memoryEnabled: memory,
        ctxMax: patch.default_context_length as number,
        contextLength: Math.min(session.contextLength, patch.default_context_length as number),
      });
      onEngineChanged?.({ workdir: d.workdir ?? "", ollamaChanged });
      setStatus({ text: `Settings saved.${note}`, tone: note.includes("⚠") ? "warn" : "ok" });
    } catch (e) {
      setStatus({ text: `Not saved: ${(e as Error).message || e}`, tone: "warn" });
    } finally {
      setSaving(false);
    }
  };

  /** Switches take effect at once, like switches: flip and save just that
   *  field (text fields still wait for Enter). They used to need a separate
   *  save, and Enter did nothing unless a text field was focused. */
  const toggle = async (which: SwitchId) => {
    const sw = SWITCHES[which];
    const next = !switches[which];
    setSwitches((v) => ({ ...v, [which]: next }));
    try {
      const d = await bridge.request("config.set", { patch: { [sw.config]: next } });
      setCfg(d);
      if (sw.session) onPatchSession({ [sw.session]: next });
      setStatus({ text: `${sw.label} ${next ? "on" : "off"} — saved.`, tone: "ok" });
    } catch (e) {
      setSwitches((v) => ({ ...v, [which]: !next }));
      setStatus({ text: `${sw.label} not changed: ${(e as Error).message || e}`, tone: "warn" });
    }
  };

  const moveFocus = (step: number) =>
    setFocus((f) => {
      const i = f == null ? (step > 0 ? -1 : 0) : FIELDS.indexOf(f);
      return FIELDS[(i + step + FIELDS.length) % FIELDS.length]!;
    });

  // Letter shortcuts only while no field is being typed into.
  const typing = () => focus != null;
  useModalKeys([
    { key: "escape", run: () => (focus ? setFocus(null) : onClose()) },
    { key: "tab", run: () => moveFocus(1) },
    { key: "shift+tab", run: () => moveFocus(-1) },
    { key: "ctrl+s", run: () => void save() },
  ]);
  useModalKeys(
    [
      { key: "return", run: () => void save() },
      { key: "s", run: () => void save() },
      ...(Object.keys(SWITCHES) as SwitchId[]).map((id) => ({ key: SWITCHES[id].key, run: () => void toggle(id) })),
      {
        key: "c",
        run: () => {
          if (!session.modelName) {
            setStatus({ text: "Select a model first.", tone: "warn" });
            return;
          }
          modals
            .push<void>((close) => (
              <ContextConfigModal
                model={session.modelName!}
                current={session.contextLength}
                onApply={(n) => {
                  onPatchSession({ contextLength: n, ctxMax: n });
                  close();
                }}
                onClose={() => close()}
              />
            ))
            .catch(() => {});
        },
      },
    ],
    { enabled: () => !typing() },
  );

  const field = (id: FieldId, label: string, value: string, set: (v: string) => void, placeholder: string) => (
    <FieldRow
      label={label}
      value={value}
      placeholder={placeholder}
      focused={focus === id}
      onFocus={() => setFocus(id)}
      onInput={set}
      onSubmit={(value) => void save({ [id]: value })}
    />
  );

  const tone = status.tone === "ok" ? theme.success : status.tone === "warn" ? theme.warn : theme.fg2;
  return (
    <ModalShell
      title="Settings"
      width={width}
      height={24}
      hints={[
        ["tab", "field"],
        ["enter", "save"],
        ["t/m/a/h", "switch"],
        ["c", "context"],
      ]}
    >
      <box flexDirection="column" paddingTop={1} flexGrow={1}>
        <SectionLabel label="engine" width={width - 4} />
        {field("ollama", "Ollama server", ollama, setOllama, "http://localhost:11434")}
        {field("gpuMem", "Ollama GPU memory", gpuMem, setGpuMem, "GB · empty = learned from chats")}
        {field(
          "workdir",
          "Working directory",
          workdir,
          setWorkdir,
          // Empty = the launch directory; show which one that currently is.
          `empty = launch dir (${fit(cfg?.workdir ?? "…", width - 48)})`,
        )}

        <box marginTop={1} flexDirection="column">
          <SectionLabel label="defaults" width={width - 4} />
          {field("model", "Default model", model, setModel, "ollama model tag")}
          {field("ctx", "Default context", ctx, setCtx, "2048")}
        </box>

        <box marginTop={1} flexDirection="column">
          <SectionLabel label="session" width={width - 4} />
          {(Object.keys(SWITCHES) as SwitchId[]).map((id) => (
            <ToggleRow key={id} label={SWITCHES[id].label} value={switches[id]} onToggle={() => void toggle(id)} />
          ))}
          {field("memoryModel", "Memory model", memoryModel, setMemoryModel, "empty = the chat model")}
        </box>
      </box>

      {/* Two lines: an unreachable-server reason must not be cut off. */}
      <box flexShrink={0} height={2}>
        <text fg={tone}>{status.text || " "}</text>
      </box>
    </ModalShell>
  );
}

const CTX_OPTIONS = [512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072];

/** Context-size picker capped by the largest window that fits the hardware. */
export function ContextConfigModal({
  model,
  current,
  onApply,
  onClose,
}: {
  model: string;
  current: number;
  onApply: (n: number) => void;
  onClose: () => void;
}) {
  const bridge = useBridge();
  const [recommended, setRecommended] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [sel, setSel] = useState(CTX_OPTIONS.indexOf(current) >= 0 ? CTX_OPTIONS.indexOf(current) : 2);
  const width = 52;

  useEffect(() => {
    bridge
      .request("hardware.recommend_context", { model })
      .then((d) => setRecommended(d.context ?? null))
      .catch((e) => setNote(String((e as Error).message || e)));
  }, [model]);

  const options = CTX_OPTIONS.filter((n) => recommended == null || n <= Math.max(recommended, current));

  useModalKeys([
    { key: "escape", run: onClose },
    { key: "up", run: () => setSel((s) => Math.max(0, s - 1)) },
    { key: "down", run: () => setSel((s) => Math.min(options.length - 1, s + 1)) },
    { key: "return", run: () => onApply(options[sel] ?? current) },
  ]);

  return (
    <ModalShell
      title={`Context — ${fit(model, 26)}`}
      width={width}
      height={Math.min(16, options.length + 7)}
      hints={[
        ["↑↓", "select"],
        ["enter", "apply"],
      ]}
    >
      {recommended != null ? (
        <text fg={theme.fg2}>{`  fits your hardware: ${recommended.toLocaleString()} tokens`}</text>
      ) : (
        <text fg={theme.warn}>{`  ${fit(note || "checking hardware…", width - 6)}`}</text>
      )}
      <box flexDirection="column" paddingTop={1} flexGrow={1}>
        {options.map((n, i) => {
          const selected = i === sel;
          const isCurrent = n === current;
          const isRec = n === recommended;
          return (
            <box key={n} onMouseDown={() => setSel(i)} backgroundColor={selected ? theme.bg3 : undefined}>
              <text>
                <span fg={selected ? theme.accent : theme.border}>{"▎"}</span>
                <span fg={selected ? theme.fg0 : theme.fg1}>{` ${n.toLocaleString()}`}</span>
                {isCurrent ? <span fg={theme.fg2}>{"  current"}</span> : null}
                {isRec ? <span fg={theme.success}>{"  ✓ recommended"}</span> : null}
              </text>
            </box>
          );
        })}
      </box>
    </ModalShell>
  );
}

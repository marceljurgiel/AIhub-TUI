import { useEffect, useRef, useState } from "react";
import { useRenderer, useTerminalDimensions } from "@opentui/react";
import { useBindings } from "@opentui/keymap/react";
import { ACTIONS, SIDEBAR_ACTIONS, type ActionId } from "../keymap/actions.ts";
import { LAYER } from "../keymap/AppKeymap.tsx";
import { theme, humanTokens } from "../theme.ts";
import { useBridge } from "../state/BridgeContext.tsx";
import { useSession } from "../state/SessionContext.tsx";
import { useModals } from "../state/ModalContext.tsx";
import { Sidebar, SIDEBAR_WIDTH } from "../widgets/Sidebar.tsx";
import { Header, Footer } from "../widgets/StatusBar.tsx";
import { ChatLog } from "../widgets/ChatLog.tsx";
import { ChatInput } from "../widgets/ChatInput.tsx";
import {
  ModelPickerModal,
  HistoryModal,
  MemoryModal,
  HardwareModal,
  SettingsModal,
  PaletteModal,
  HelpModal,
  PermissionModal,
  AgentModal,
  type AgentProfile,
  SkillsModal,
  type SkillInfo,
  TemperatureModal,
  McpModal,
} from "../modals/index.ts";
import { toolsLabel } from "../modals/AgentModal.tsx";
import { parseSlash } from "../slash.ts";
import { sanitizeText } from "../bridge/sanitize.ts";
import { debugLog } from "../bridge/client.ts";
import type { LogItem } from "../log.ts";
import type { Attachment, ChatMessage } from "../bridge/types.ts";
import { imagePaste } from "../clipboard.ts";
import type { SessionState } from "../state/SessionContext.tsx";
import type { EngineChange } from "../modals/SettingsModal.tsx";
import { ActivityLine, type Activity, type Phase } from "../widgets/ActivityLine.tsx";

/** True when a text field currently owns the keyboard. Bare-letter nav is
 *  suppressed in that case, mirroring the Textual app's rule — but read from
 *  the renderer's own focus state instead of a parallel context of our own. */
function isTextInputFocused(renderer: { currentFocusedRenderable?: unknown }): boolean {
  const focused = renderer.currentFocusedRenderable as { constructor?: { name?: string } } | null;
  if (!focused) return false;
  const name = focused.constructor?.name ?? "";
  return name === "InputRenderable" || name === "TextareaRenderable";
}

function errorText(e: unknown): string {
  return String((e as Error)?.message || e);
}

// Automatic memory runs once the user has been quiet this long after a reply.
// (AIHUB_LEARN_IDLE_MS shortens it for tests.)
const LEARN_IDLE_MS = Number(process.env.AIHUB_LEARN_IDLE_MS) || 20_000;
// Longest reasoning kept for the "✻ Thought for Ns" log entry.
const MAX_THOUGHT = 20_000;
// Approximate width taken by the sidebar, for sizing the status preview.

const MIN_WIDTH = 80;
const MIN_HEIGHT = 18;
const WELCOME_ITEM: LogItem = {
  kind: "system",
  text:
    "Welcome to AIhub.  ^P palette · ^O models · ^R history · F1 help · ^Q quit",
};

export function ChatScreen({
  version,
  coreVersion,
}: {
  /** This UI's version (package.json). */
  version: string;
  /** The Python engine's version, as reported by the bridge ready banner. */
  coreVersion: string;
}) {
  const bridge = useBridge();
  const { state, dispatch } = useSession();
  const modals = useModals();
  const renderer = useRenderer();
  const { width, height } = useTerminalDimensions();

  const [logItems, setLogItems] = useState<LogItem[]>([WELCOME_ITEM]);
  const [streamingText, setStreamingText] = useState("");
  const [projectDir, setProjectDir] = useState("");
  const [activeAction, setActiveAction] = useState<ActionId>("new_chat");
  // The sidebar menu has the keyboard instead of the prompt.
  const [navFocus, setNavFocus] = useState(false);
  const [navIndex, setNavIndex] = useState(0);
  const [installedNames, setInstalledNames] = useState<Set<string>>(new Set());
  const streamId = useRef<number | null>(null);
  const streamAccum = useRef("");
  // Id of the latest chat turn. Bridge events/results carrying an older id are
  // stale (the turn was superseded or abandoned) and get dropped.
  const turnSeq = useRef(0);
  // Live status line ("Thinking… (14s · esc to interrupt)") for the running turn.
  const [activity, setActivity] = useState<Activity | null>(null);
  // The current stretch of reasoning, logged as "✻ Thought for Ns" once the
  // model moves on (starts writing, calls a tool, or the turn ends).
  const thinkStart = useRef<number | null>(null);
  const thoughtText = useRef("");
  // Automatic memory: how many of this session's user messages were already
  // examined, and the pending "user has gone quiet" timer.
  const learnCursor = useRef(0);
  const learnSession = useRef(0);
  const learnTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Turn cancelled with Esc: its late events are dropped, but its final
  // messages (user message + partial reply) are still adopted unless a newer
  // turn has started since.
  const cancelledTurn = useRef(-1);
  const stateRef = useRef(state);
  stateRef.current = state;
  const modalsRef = useRef(modals);
  modalsRef.current = modals;

  const addSystem = (text: string, error = false) =>
    setLogItems((prev) => [...prev, { kind: "system", text, error }]);

  /** Catch handler for engine calls the user triggered: the failure is shown
   *  in the log instead of the action silently doing nothing. */
  const setPhase = (phase: Phase, tool?: string) =>
    setActivity((a) => (a ? { ...a, phase, tool } : a));

  /** Close the current stretch of thinking and log it (collapsed). */
  const flushThought = () => {
    if (thinkStart.current == null) return;
    const seconds = (Date.now() - thinkStart.current) / 1000;
    const text = thoughtText.current;
    thinkStart.current = null;
    thoughtText.current = "";
    if (text.trim()) setLogItems((prev) => [...prev, { kind: "thought", seconds, text }]);
  };

  /** Save the chat to history (one file per session, updated each time).
   *  `auto` saves honour the Settings switch; Ctrl+S always saves. */
  const saveSession = (s: SessionState, messages: ChatMessage[], auto: boolean) =>
    bridge.request("chat.finalize", {
      model: s.modelName,
      messages,
      temperature: s.temperature,
      start_time: s.startTime,
      backend: s.backend,
      stream_model: s.streamModel,
      auto,
    });

  const cancelLearnTimer = () => {
    if (learnTimer.current) clearTimeout(learnTimer.current);
    learnTimer.current = null;
  };

  /** Learn durable facts from the user's messages not examined yet. Each
   *  change shows up in the log with a way to undo it. */
  const learnNow = (messages: ChatMessage[] = stateRef.current.messages, s: SessionState = stateRef.current) => {
    cancelLearnTimer();
    if (!s.modelName || !messages.some((m) => m.role === "user")) return;
    const session = learnSession.current;
    bridge
      .request("memory.learn", { messages, cursor: learnCursor.current, model: s.modelName, session: s.startTime })
      .then((d) => {
        if (session === learnSession.current) learnCursor.current = d.cursor ?? learnCursor.current;
        const changes = (d.changes || []) as Array<Extract<LogItem, { kind: "memory" }>>;
        if (changes.length) setLogItems((prev) => [...prev, ...changes.map((c) => ({ ...c, kind: "memory" as const }))]);
      })
      .catch(reportBackground("Learning memory"));
  };

  /** After a reply, learn once the user has been quiet for a while — so the
   *  memory model doesn't compete with the chat model mid-conversation. */
  const scheduleLearning = () => {
    cancelLearnTimer();
    learnTimer.current = setTimeout(() => {
      if (stateRef.current.streaming) return scheduleLearning();
      learnNow();
    }, LEARN_IDLE_MS);
  };

  /** A session ends (new chat, clear, model switch, history load): learn from
   *  what's left of it, then start counting afresh. */
  const endSessionLearning = (nextCursor = 0) => {
    const s = stateRef.current;
    learnNow(s.messages, s);
    learnSession.current++;
    learnCursor.current = nextCursor;
  };

  /** Drop the status line and any unlogged reasoning (turn over / discarded). */
  const endActivity = () => {
    thinkStart.current = null;
    thoughtText.current = "";
    setActivity(null);
  };

  const reportFailure = (what: string) => (e: unknown) => {
    debugLog(`${what} failed: ${errorText(e)}`);
    addSystem(`${what} failed: ${errorText(e)}`, true);
  };

  // Background calls (status poll, model list refresh) fail repeatedly while
  // e.g. the engine is down — show each distinct failure once, not every 15s.
  const lastBackgroundError = useRef("");
  const reportBackground = (what: string) => (e: unknown) => {
    const text = `${what} failed: ${errorText(e)}`;
    debugLog(text);
    if (text === lastBackgroundError.current) return;
    lastBackgroundError.current = text;
    addSystem(text, true);
  };

  const patchSession = (patch: Partial<SessionState>) => dispatch({ type: "patch", patch });

  const refreshInstalled = () =>
    bridge
      .request("models.installed")
      .then((d) => setInstalledNames(new Set((d.models || []).map((m: any) => m.name))))
      .catch(reportBackground("Listing installed models"));

  // ── startup ──
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cfg = await bridge.request("config.get");
        if (cancelled) return;
        // Where tools actually run: project_dir, else the launch directory.
        setProjectDir(cfg.workdir || cfg.project_dir || "");
        dispatch({
          type: "patch",
          patch: {
            memoryEnabled: !!cfg.memory_enabled,
            toolsEnabled: !!cfg.tools_enabled,
            temperature: typeof cfg.temperature === "number" ? cfg.temperature : 0.7,
            contextLength: cfg.default_context_length || 2048,
            ctxMax: cfg.default_context_length || 2048,
          },
        });

        const status = await bridge.request("backend.status");
        if (!cancelled) applyStatus(status);
        if (!cancelled && status.ollama_started) addSystem("Started Ollama in the background.");

        const inst = await bridge.request("models.installed");
        if (cancelled) return;
        setInstalledNames(new Set((inst.models || []).map((m: any) => m.name)));
        const names: string[] = (inst.models || []).map((m: any) => m.name);
        const model = names.includes(cfg.default_chat_model) ? cfg.default_chat_model : names[0];
        if (model) {
          const started = await bridge.request("chat.start", { model, messages: [] });
          if (cancelled) return;
          dispatch({
            type: "patch",
            patch: { modelName: model, streamModel: model, backend: "ollama", messages: started.messages || [] },
          });
          // Same sizing as picking a model: the configured default (often
          // 2048) can't even hold the tool descriptions.
          const sized = await bridge.request("hardware.recommend_context", { model }).catch(() => null);
          if (!cancelled && sized?.context > 0)
            dispatch({ type: "patch", patch: { contextLength: sized.context, ctxMax: sized.context } });
        } else if (!cancelled) {
          // An offline Ollama also lists zero models — say which one it is.
          addSystem(
            status.ollama_online
              ? "No installed models yet — press ^O to pick or download one."
              : "Ollama isn't running — start it with `ollama serve`, or press ^O for a cloud model.",
            !status.ollama_online,
          );
        }
      } catch (e) {
        if (!cancelled) reportFailure("Starting up")(e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const applyStatus = (s: any) =>
    dispatch({
      type: "patch",
      patch: {
        ollamaOnline: !!s.ollama_online,
        llamacppOnline: !!s.llamacpp_online,
        llamacppModel: s.llamacpp_model || "",
      },
    });

  // A pending learn timer must not fire into an unmounted screen.
  useEffect(() => () => cancelLearnTimer(), []);

  // Model catalogs (Ollama library, HF GGUF): refreshed in the background
  // once per app start; the picker reads the cache meanwhile.
  useEffect(() => {
    bridge.request("catalog.refresh").catch(reportBackground("Refreshing model catalogs"));
  }, []);

  // ── backend status poll (15s) ──
  useEffect(() => {
    const t = setInterval(() => {
      bridge.request("backend.status", { start: false }).then(applyStatus).catch(reportBackground("Checking backends"));
    }, 15000);
    return () => clearInterval(t);
  }, []);

  // Skills → "/skill <name>" suggestions in the prompt; refreshed when the
  // Skills modal changes them.
  const [skillList, setSkillList] = useState<SkillInfo[]>([]);
  useEffect(() => {
    bridge
      .request("skills.list")
      .then((d) => setSkillList(d.skills || []))
      .catch(reportBackground("Listing skills"));
  }, []);
  const skillCommands = skillList
    .filter((s) => s.enabled)
    .map((s) => ({ cmd: `/skill ${s.name}`, desc: s.description }));
  const [prefill, setPrefill] = useState<{ text: string; seq: number } | undefined>(undefined);

  // ── image attachments ──
  const [pending, setPending] = useState<Attachment[]>([]);
  const pendingRef = useRef(pending);
  pendingRef.current = pending;
  const addAttachments = (list: Attachment[]) => setPending((p) => [...p, ...list].slice(0, 8));
  // Can the current model see? Asked once per model, when something is attached.
  const [vision, setVision] = useState<Record<string, boolean>>({});
  useEffect(() => {
    const s = stateRef.current;
    const key = s.streamModel || s.modelName;
    if (!pending.length || !key || key in vision) return;
    bridge
      .request("vision.check", { model: s.modelName, stream_model: key, backend: s.backend })
      .then((d) => setVision((v) => ({ ...v, [key]: !!d.vision })))
      .catch(() => {});
  }, [pending.length, state.modelName, state.streamModel]);
  const visionKey = state.streamModel || state.modelName || "";
  const attachNote =
    pending.length && visionKey in vision && !vision[visionKey]
      ? `${state.modelName} can't see images — pick a vision model (^O), e.g. gemma4:cloud`
      : "";

  // Ctrl+V with an image in the clipboard (the keymap asks us first).
  useEffect(() => {
    imagePaste.handler = () => {
      if (modalsRef.current.isOpen) return false;
      bridge
        .request("attach.clipboard")
        .then((d) => addAttachments([d.attachment]))
        .catch(reportFailure("Attaching the clipboard image"));
      return true;
    };
    return () => {
      imagePaste.handler = null;
    };
  }, []);

  const attachPaths = (text: string): Promise<boolean> =>
    bridge
      .request("attach.paste", { text })
      .then((d) => {
        const got: Attachment[] = d.attachments || [];
        if (got.length) addAttachments(got);
        return got.length > 0;
      })
      .catch((e) => {
        reportFailure("Attaching the image")(e);
        return true;            // the path was an image that failed: don't paste it as text
      });

  // ── chat submit ──
  /** `wire`: what the model gets when it differs from what the user typed
   *  (a /skill message carries the skill's instructions). */
  const startChat = (input: string, wire?: string) => {
    const s = stateRef.current;
    if (s.streaming || !s.modelName) return;
    const images = pendingRef.current;
    const userMsg: ChatMessage = { role: "user", content: wire ?? input };
    if (images.length) userMsg.images = images.map((a) => a.id);
    const outgoing = [...s.messages, userMsg];
    setPending([]);
    // Pasted text can carry control characters too; the log must not.
    setLogItems((prev) => [
      ...prev,
      { kind: "user", text: sanitizeText(input), images: images.length ? images.map((a) => a.name) : undefined },
    ]);
    dispatch({ type: "patch", patch: { messages: outgoing, streaming: true } });
    setStreamingText("");
    streamAccum.current = "";
    const turn = ++turnSeq.current;
    const live = () => turn === turnSeq.current && turn !== cancelledTurn.current;
    thinkStart.current = null;
    thoughtText.current = "";
    cancelLearnTimer();
    setActivity({ phase: "working", startedAt: Date.now(), thought: "" });

    const { id, done } = bridge.stream(
      "chat.turn",
      {
        model: s.modelName,
        stream_model: s.streamModel || s.modelName,
        backend: s.backend,
        messages: outgoing,
        temperature: s.temperature,
        context_length: s.contextLength,
        tools_enabled: s.toolsEnabled,
        agent: s.mode === "agent",
        agent_name: s.agentName,
        submode: s.agentSubmode,
      },
      {
        onEvent: (event, data) => {
          if (!live()) {
            // A stale turn still waiting on approval must not hang the engine.
            if (event === "permission_request") bridge.permission(id, false);
            return;
          }
          switch (event) {
            case "thinking":
              if (thinkStart.current == null) thinkStart.current = Date.now();
              // Keep the log copy bounded; the status line only shows the tail.
              thoughtText.current = (thoughtText.current + data.text).slice(-MAX_THOUGHT);
              setActivity((a) => (a ? { ...a, phase: "thinking", thought: thoughtText.current.slice(-600) } : a));
              break;
            case "text":
              flushThought();
              setPhase("writing");
              streamAccum.current += data.text;
              setStreamingText(streamAccum.current);
              break;
            case "usage":
              dispatch({
                type: "addUsage",
                promptTokens: data.prompt_tokens || 0,
                completionTokens: data.completion_tokens || 0,
                tps: data.tps || 0,
              });
              break;
            case "round": {
              const t = (data.text || "").trim();
              if (t) setLogItems((prev) => [...prev, { kind: "assistant", text: data.text }]);
              streamAccum.current = "";
              setStreamingText("");
              break;
            }
            case "tool_call":
              flushThought();
              setPhase("tool", data.name);
              setLogItems((prev) => [
                ...prev,
                { kind: "tool", id: data.call_id, name: data.name, args: data.arguments, status: "running" },
              ]);
              break;
            case "tool_result":
              setPhase("working");               // the model reads the result next
              setLogItems((prev) =>
                prev.map((it) =>
                  it.kind === "tool" && it.id === data.call_id
                    ? {
                        ...it,
                        // The engine flags failures that tools report in-band
                        // ("[Edit Error] …", non-zero exit) and user denials.
                        status: data.denied ? "denied" : data.error ? "error" : "done",
                        result: data.result,
                        error: data.error,
                        durationMs: data.duration_ms,
                      }
                    : it,
                ),
              );
              break;
            case "permission_request": {
              // The engine pauses before a mutating tool (plain chat and agent
              // plan mode) until we answer.
              setPhase("approval");
              modalsRef.current
                .push<void>((close) => (
                  <PermissionModal
                    tool={data.name}
                    args={data.arguments}
                    onAnswer={(allow) => {
                      setPhase(allow ? "tool" : "working", allow ? data.name : undefined);
                      bridge.permission(id, allow);
                    }}
                    onClose={close}
                  />
                ))
                .catch(() => {});
              return;
            }
            case "chat_error":
              addSystem(data.message, data.fatal);
              break;
          }
        },
      },
    );
    streamId.current = id;

    done
      .then((data) => {
        if (turn !== turnSeq.current) return; // superseded or abandoned
        if (turn === cancelledTurn.current) {
          // Esc already flushed the partial text and unlocked the input.
          dispatch({ type: "patch", patch: { messages: data.messages || outgoing } });
          return;
        }
        flushThought();                      // a turn that only thought
        endActivity();
        if (streamAccum.current.trim())
          setLogItems((prev) => [...prev, { kind: "assistant", text: streamAccum.current }]);
        // Small models sometimes think, run a tool, and then say nothing.
        const last = (data.messages || [])[data.messages?.length - 1];
        if (last && !(last.role === "assistant" && String(last.content || "").trim()))
          addSystem("The model ended without an answer — ask it to continue, or try a bigger model.", true);
        dispatch({ type: "patch", patch: { messages: data.messages || outgoing, streaming: false } });
        saveSession(s, data.messages || outgoing, true).catch(reportBackground("Saving the chat"));
        scheduleLearning();
      })
      .catch((e) => {
        if (!live()) return;
        flushThought();
        endActivity();
        addSystem(String(e?.message || e), true);
        dispatch({ type: "patch", patch: { streaming: false } });
      })
      .finally(() => {
        if (!live()) return;
        setStreamingText("");
        streamAccum.current = "";
        streamId.current = null;
      });
  };

  /** Stop listening to the running turn right away. The bridge is told to
   *  cancel; the engine stops at its next check and closes the backend stream. */
  const detachStream = () => {
    if (streamId.current != null) bridge.cancel(streamId.current);
    streamId.current = null;
    streamAccum.current = "";
    setStreamingText("");
    endActivity();
    dispatch({ type: "patch", patch: { streaming: false } });
  };

  /** Esc: keep what was already shown, unlock the input immediately. */
  const cancelStream = () => {
    if (!stateRef.current.streaming || streamId.current == null) return;
    cancelledTurn.current = turnSeq.current;
    flushThought();                          // keep what it had thought so far
    const partial = streamAccum.current;
    if (partial.trim()) setLogItems((prev) => [...prev, { kind: "assistant", text: partial }]);
    detachStream();
    addSystem("Stream cancelled.");
  };

  /** Discard the running turn entirely (new chat, clear, model switch,
   *  history load): its results must not land in the new conversation. */
  const abandonTurn = () => {
    if (!stateRef.current.streaming) return;
    turnSeq.current++;
    detachStream();
  };

  // ── new chat / clear / history ──
  const doNewChat = () => {
    abandonTurn();
    endSessionLearning();
    const s = stateRef.current;
    setLogItems([WELCOME_ITEM]);
    dispatch({ type: "newChat" });
    if (s.modelName) {
      bridge
        .request("chat.start", { model: s.modelName, messages: [] })
        .then((r) => dispatch({ type: "patch", patch: { messages: r.messages || [] } }))
        .catch(reportFailure("Starting a new chat"));
    }
  };

  const doClear = () => {
    abandonTurn();
    endSessionLearning();
    const sys = stateRef.current.messages.filter((m) => m.role === "system");
    // A new session: autosave must not overwrite the cleared chat's file.
    dispatch({ type: "patch", patch: { messages: sys, startTime: new Date().toISOString() } });
    setLogItems([{ kind: "system", text: "Chat cleared." }]);
  };

  const doLoadHistory = (messages: ChatMessage[], startTime?: string) => {
    abandonTurn();
    // Old messages were already there to learn from; only new ones count.
    endSessionLearning(messages.filter((m) => m.role === "user").length);
    const items: LogItem[] = [WELCOME_ITEM];
    for (const m of messages) {
      if (m.role === "user")
        items.push({
          kind: "user",
          text: String(m.content),
          images: m.images?.length ? m.images.map((_, i) => `image ${i + 1}`) : undefined,
        });
      else if (m.role === "assistant") items.push({ kind: "assistant", text: String(m.content) });
    }
    setLogItems(items);
    // Keep the session's own start time so autosave updates its file.
    dispatch({ type: "patch", patch: { messages, streaming: false, startTime: startTime || new Date().toISOString() } });
    addSystem(`Resumed session — ${messages.filter((m) => m.role !== "system").length} messages.`);
  };

  const doPickModel = (display: string, backend: "ollama" | "api", streamModel: string) => {
    abandonTurn();
    endSessionLearning();
    dispatch({
      type: "patch",
      patch: { modelName: display, streamModel, backend, mode: "chat", messages: [], startTime: new Date().toISOString() },
    });
    setLogItems([WELCOME_ITEM]);
    bridge
      .request("chat.start", { model: display, messages: [] })
      .then((r) => dispatch({ type: "patch", patch: { messages: r.messages || [] } }))
      .catch(reportFailure(`Switching to ${display}`));
    refreshInstalled();
    addSystem(`Model → ${display}${backend === "api" ? "  (cloud API)" : ""}.`);
    if (backend === "ollama") {
      // Touchless context: size the window to what the hardware fits.
      bridge
        .request("hardware.recommend_context", { model: display })
        .then((d) => {
          if (d.context && d.context > 0)
            dispatch({ type: "patch", patch: { contextLength: d.context, ctxMax: d.context } });
        })
        .catch(reportFailure("Sizing the context window"));
    }
  };

  // ── slash dispatch ──
  const handleSlash = (raw: string) => {
    const r = parseSlash(raw);
    const model = stateRef.current.modelName;
    switch (r.kind) {
      case "new": return doNewChat();
      case "clear": return doClear();
      case "help": return openHelp();
      case "tools":
        bridge.request("tools.describe").then((d) => addSystem(d.text || "(no tools)")).catch(reportFailure("Listing tools"));
        return;
      case "model": return openModelPicker();
      case "agent": return openAgents();
      case "skills": return openSkills();
      case "mcp": return openMcp();
      case "skill": {
        const s = stateRef.current;
        if (!s.modelName) return addSystem("Select a model first (^O).", true);
        if (s.streaming) return;
        const name = r.payload?.key ?? "";
        bridge
          .request("skills.invoke", { name, task: r.payload?.value ?? "", context_length: s.contextLength })
          .then((d) => startChat(raw.trim(), d.content))
          .catch(reportFailure(`Using skill ${name}`));
        return;
      }
      case "history": return openHistory();
      case "memory_show": return openMemory();
      case "memory_save":
        bridge
          .request("memory.save_entry", { key: r.payload!.key, value: r.payload!.value })
          .then(() => addSystem(`Saved “${r.payload!.key}” to memory.`))
          .catch(reportFailure("Saving to memory"));
        return;
      case "memory_undo":
        bridge
          .request("memory.undo", {})
          .then((d) => {
            const undone = (d.reverted || []) as Array<{ topic: string; before?: string | null; after?: string | null }>;
            if (!undone.length) return addSystem("Nothing to undo — memory hasn't learned anything since the last undo.");
            setLogItems((prev) => [
              ...prev,
              ...undone.map((c) => ({ kind: "memory" as const, op: "undo" as const, topic: c.topic, before: c.before, after: c.after })),
            ]);
          })
          .catch(reportFailure("Undoing memory"));
        return;
      case "memory_clear":
        bridge.request("memory.clear").then(() => addSystem("Memory cleared.")).catch(reportFailure("Clearing memory"));
        return;
      case "memory_extract":
        if (!model) return addSystem("No model selected.", true);
        addSystem("Extracting facts from this chat…");
        bridge
          .request("memory.extract", { model, messages: stateRef.current.messages })
          .then((d) => addSystem(d.ok ? "Memory updated with extracted facts." : d.summary, !d.ok))
          .catch(reportFailure("Extracting memory"));
        return;
      case "temp": {
        const raw = (r.payload?.value ?? "").replace(",", ".");
        if (!raw) return openTemperature();
        const t = Number(raw);
        if (!Number.isFinite(t) || t < 0 || t > 2) return addSystem("Temperature is a number from 0 to 2, e.g. /temp 0.3", true);
        return setTemperature(t);
      }
      case "websearch": {
        const query = r.payload?.value ?? "";
        addSystem(`Searching the web for “${query || "weather Lisbon"}”…`);
        bridge
          .request("search.check", { query })
          .then((d) =>
            d.ok
              ? addSystem(`Web search works — ${d.count} results via ${d.source}. First: ${d.first.title} — ${d.first.url}`)
              : addSystem(`Web search failed: ${(d.failures || []).join("; ") || "no results"}`, true),
          )
          .catch(reportFailure("Testing web search"));
        return;
      }
      case "cd": {
        const path = r.payload?.path ?? "";
        if (!path) {
          // Bare /cd: say where tools run and how to change it.
          bridge
            .request("config.get")
            .then((d) => addSystem(`Working directory: ${d.workdir}  (change with /cd <path>, default in Settings)`))
            .catch(reportFailure("Reading the working directory"));
          return;
        }
        bridge
          .request("workdir.set", { path })
          .then((d) => {
            setProjectDir(d.workdir);
            addSystem(`Working directory → ${d.workdir}`);
          })
          .catch(reportFailure("Changing directory"));
        return;
      }
      case "unknown":
        return addSystem(r.message || "Unknown command.", true);
    }
  };

  const submit = (input: string) => {
    if (input.startsWith("/")) handleSlash(input);
    else startChat(input);
  };

  // ── modal openers ──
  const openModelPicker = () => {
    modals
      .push<void>((close) => (
        <ModelPickerModal
          currentModel={stateRef.current.modelName}
          installedSet={installedNames}
          onPick={doPickModel}
          onClose={close}
        />
      ))
      .catch(() => {});
  };

  // Context the chat used before an agent enlarged it — restored on leaving.
  const chatContext = useRef<{ contextLength: number; ctxMax: number } | null>(null);
  useEffect(() => {
    if (state.mode === "chat" && chatContext.current) {
      dispatch({ type: "patch", patch: chatContext.current });
      chatContext.current = null;
    }
  }, [state.mode]);

  const startAgent = (agent: AgentProfile, submode: "plan" | "build") => {
    const s = stateRef.current;
    if (!s.modelName) return addSystem("Select a model first (^O).", true);
    bridge
      .request("agent.check", { model: s.streamModel || s.modelName, backend: s.backend, agent: agent.name })
      .then((d) => {
        if (!d.ok) return addSystem(`Agent unavailable: ${d.reason}`, true);
        const cur = stateRef.current;
        if (cur.mode === "chat") chatContext.current = { contextLength: cur.contextLength, ctxMax: cur.ctxMax };
        const patch: Partial<SessionState> = { mode: "agent", agentName: agent.name, agentSubmode: submode };
        if (d.context > 0) Object.assign(patch, { contextLength: d.context, ctxMax: d.context });
        dispatch({ type: "patch", patch });
        const asks = submode === "plan" || agent.permission === "ask";
        addSystem(
          `Agent ${agent.name} · ${submode} — ${humanTokens(d.context || cur.contextLength)} context` +
            `${d.context_note ? ` (${d.context_note})` : ""}. ` +
            `Tools: ${toolsLabel(agent.tools) || "none"}; ` +
            (asks ? "asks before edits and commands." : "runs edits and commands without asking.") +
            (agent.model && agent.model !== cur.modelName ? `  This agent suggests ${agent.model} (^O).` : "") +
            "  ^G to switch.",
        );
      })
      .catch(reportFailure("Checking agent support"));
  };

  /** Session + saved default, so new chats and restarts keep it. */
  const setTemperature = (t: number) => {
    const v = Math.round(t * 10) / 10;
    dispatch({ type: "patch", patch: { temperature: v } });
    bridge
      .request("config.set", { patch: { temperature: v } })
      .then(() => addSystem(`Temperature → ${v.toFixed(1)}.`))
      .catch(reportFailure("Saving the temperature"));
  };

  const openMcp = () => {
    modals.push<void>((close) => <McpModal onClose={close} />).catch(() => {});
  };

  const openTemperature = () => {
    modals
      .push<void>((close) => (
        <TemperatureModal value={stateRef.current.temperature} onSave={setTemperature} onClose={close} />
      ))
      .catch(() => {});
  };

  /** Footer click on "mem": same switch as in Settings (saved). */
  const toggleMemory = () => {
    const next = !stateRef.current.memoryEnabled;
    bridge
      .request("config.set", { patch: { memory_enabled: next } })
      .then(() => {
        dispatch({ type: "patch", patch: { memoryEnabled: next } });
        addSystem(`Memory ${next ? "on" : "off"}.`);
      })
      .catch(reportFailure("Switching memory"));
  };

  const openSkills = () => {
    const s = stateRef.current;
    modals
      .push<void>((close) => (
        <SkillsModal
          model={s.modelName}
          backend={s.backend}
          streamModel={s.streamModel || s.modelName || ""}
          onUse={(name) => setPrefill({ text: `/skill ${name} `, seq: Date.now() })}
          onChanged={setSkillList}
          onClose={close}
        />
      ))
      .catch(() => {});
  };

  const openAgents = () => {
    const s = stateRef.current;
    modals
      .push<void>((close) => (
        <AgentModal
          current={s.mode === "agent" ? s.agentName : null}
          model={s.modelName}
          backend={s.backend}
          streamModel={s.streamModel || s.modelName || ""}
          onChoose={(c) => {
            if (c.kind === "agent") return startAgent(c.agent, c.submode);
            if (stateRef.current.mode === "agent") {
              dispatch({ type: "patch", patch: { mode: "chat" } });
              addSystem("Back to plain chat.");
            }
          }}
          onClose={close}
        />
      ))
      .catch(() => {});
  };

  const openHistory = () => {
    modals
      .push<void>((close) => (
        <HistoryModal model={stateRef.current.modelName} onLoad={doLoadHistory} onClose={close} />
      ))
      .catch(() => {});
  };

  const openMemory = () => {
    modals.push<void>((close) => <MemoryModal onClose={close} />).catch(() => {});
  };

  const openHardware = () => {
    modals
      .push<void>((close) => (
        <HardwareModal model={stateRef.current.modelName} onClose={close} />
      ))
      .catch(() => {});
  };

  /** Settings saved: the tools' directory or the Ollama server may differ now. */
  const onEngineChanged = (change: EngineChange) => {
    if (change.workdir) setProjectDir(change.workdir);
    if (!change.ollamaChanged) return;
    bridge.request("backend.status").then(applyStatus).catch(reportFailure("Checking the new Ollama server"));
    bridge
      .request("models.installed")
      .then((d) => {
        const names: string[] = (d.models || []).map((m: any) => m.name);
        setInstalledNames(new Set(names));
        const s = stateRef.current;
        if (s.backend === "ollama" && s.modelName && !names.includes(s.modelName))
          addSystem(`${s.modelName} isn't on this Ollama server — press ^O to pick one of its ${names.length} models.`, true);
      })
      .catch(reportFailure("Listing models on the new Ollama server"));
  };

  const openSettings = () => {
    modals
      .push<void>((close) => (
        <SettingsModal
          session={stateRef.current}
          onPatchSession={patchSession}
          onEngineChanged={onEngineChanged}
          onClose={close}
        />
      ))
      .catch(() => {});
  };

  const openPalette = () => {
    modals
      .push<void>((close) => <PaletteModal onAction={dispatchAction} onClose={close} />)
      .catch(() => {});
  };

  const openHelp = () => {
    modals.push<void>((close) => <HelpModal onClose={close} />).catch(() => {});
  };

  // ── actions ──
  // Every keybinding, sidebar click and slash command funnels through here, so
  // there is exactly one place an action can be triggered from.
  function dispatchAction(action: ActionId) {
    setNavFocus(false);                       // any action hands the keyboard back
    switch (action) {
      case "quit": {
        // Autosave the chat before leaving; never hang the exit on it.
        const s = stateRef.current;
        if (!s.modelName || !s.messages.some((m) => m.role === "user")) return renderer.destroy();
        cancelLearnTimer();
        Promise.race([saveSession(s, s.messages, true), new Promise((r) => setTimeout(r, 1500))])
          .catch(() => {})
          .finally(() => renderer.destroy());
        return;
      }
      case "cancel_stream":
        return cancelStream();
    }
    setActiveAction(action);
    switch (action) {
      case "new_chat": return doNewChat();
      case "clear_chat": return doClear();
      case "model_picker": return openModelPicker();
      case "history": return openHistory();
      case "memory": return openMemory();
      case "hardware": return openHardware();
      case "settings": return openSettings();
      case "command_palette": return openPalette();
      case "help": return openHelp();
      case "temperature":
        return openTemperature();
      case "toggle_tools":
        dispatch({ type: "patch", patch: { toolsEnabled: !stateRef.current.toolsEnabled } });
        addSystem(`Tools ${!stateRef.current.toolsEnabled ? "enabled" : "disabled"}.`);
        return;
      case "agent":
        return openAgents();
      case "skills":
        return openSkills();
      case "mcp":
        return openMcp();
      case "save_session":
        if (stateRef.current.modelName)
          bridge
            .request("chat.finalize", {
              model: stateRef.current.modelName,
              messages: stateRef.current.messages,
              temperature: stateRef.current.temperature,
              start_time: stateRef.current.startTime,
              backend: stateRef.current.backend,
              stream_model: stateRef.current.streamModel,
            })
            .then((d) => addSystem(d.path ? "Session saved." : "Nothing to save."))
            .catch(reportFailure("Saving the session"));
        return;
    }
  }

  // ── keybindings ──
  // Two declarative layers instead of one hand-rolled key switch. `enabled` is
  // evaluated at dispatch time, so the gates below stay correct without the
  // layers being re-registered; the commands read `actionRef` for the same
  // reason (the layer is memoised once, the handler changes every render).
  const actionRef = useRef(dispatchAction);
  actionRef.current = dispatchAction;

  // Keyboard in the sidebar menu (Tab from an empty prompt): arrows move,
  // enter opens, the row letters jump (the nav layer below — it is live
  // because no text field has focus now), esc / tab go back to typing.
  const navState = useRef({ focus: navFocus, index: navIndex });
  navState.current = { focus: navFocus, index: navIndex };
  useBindings(
    () => ({
      priority: LAYER.nav,
      enabled: () => navState.current.focus && !modalsRef.current.isOpen,
      commands: [
        { name: "menu.up", run: () => setNavIndex((i) => (i - 1 + SIDEBAR_ACTIONS.length) % SIDEBAR_ACTIONS.length) },
        { name: "menu.down", run: () => setNavIndex((i) => (i + 1) % SIDEBAR_ACTIONS.length) },
        { name: "menu.open", run: () => actionRef.current(SIDEBAR_ACTIONS[navState.current.index]!.id) },
        { name: "menu.leave", run: () => setNavFocus(false) },
      ],
      bindings: [
        { key: "up", cmd: "menu.up" },
        { key: "down", cmd: "menu.down" },
        { key: "return", cmd: "menu.open" },
        { key: "escape", cmd: "menu.leave" },
        { key: "tab", cmd: "menu.leave" },
      ],
    }),
    [],
  );

  useBindings(
    () => ({
      priority: LAYER.global,
      // A modal owns the keyboard while it is up.
      enabled: () => !modalsRef.current.isOpen,
      commands: ACTIONS.map((a) => ({
        name: a.id,
        run: () => {
          actionRef.current(a.id);
        },
      })),
      bindings: ACTIONS.flatMap((a) =>
        [a.key, ...(a.altKeys ?? [])].filter((k): k is string => !!k).map((k) => ({ key: k, cmd: a.id })),
      ),
    }),
    [],
  );

  useBindings(
    () => ({
      priority: LAYER.nav,
      // Bare letters must not fire while a text field is swallowing characters.
      // Asking the renderer which renderable has focus beats tracking it in our
      // own context — the framework already owns that state.
      enabled: () => !modalsRef.current.isOpen && !isTextInputFocused(renderer),
      bindings: ACTIONS.filter((a) => a.nav).map((a) => ({ key: a.nav!, cmd: a.id })),
    }),
    [renderer],
  );

  // ── size guard ──
  if (width < MIN_WIDTH || height < MIN_HEIGHT) {
    return (
      <box width="100%" height="100%" alignItems="center" justifyContent="center" backgroundColor={theme.bg0}>
        <text fg={theme.warn}>{`Terminal too small — resize to at least ${MIN_WIDTH}×${MIN_HEIGHT}`}</text>
        <text fg={theme.fg2}>{`current: ${width}×${height}`}</text>
      </box>
    );
  }

  const ctxK = Math.max(1, Math.round(state.contextLength / 1024));

  return (
    <box width="100%" height="100%" flexDirection="column" backgroundColor={theme.bg0}>
      <Header state={state} />
      <box flexDirection="row" flexGrow={1}>
        <Sidebar
          model={state.modelName}
          online={state.ollamaOnline}
          ctxK={ctxK}
          version={version}
          coreVersion={coreVersion}
          activeAction={navFocus ? SIDEBAR_ACTIONS[navIndex]!.id : modals.isOpen ? activeAction : null}
          menuFocused={navFocus && !modals.isOpen}
          onAction={dispatchAction}
        />
        <box flexDirection="column" flexGrow={1}>
          <ChatLog items={logItems} streamingText={streamingText} />
          {activity ? (
            <ActivityLine activity={activity} width={width - SIDEBAR_WIDTH} />
          ) : (
            <box paddingLeft={2} flexShrink={0}>
              <text fg={theme.fg2}>
                {navFocus
                  ? "↑↓ choose · ↵ open · letters jump · esc back to typing"
                  : "↵ send · tab menu · / commands · ^V paste"}
              </text>
            </box>
          )}
          <ChatInput
            focused={!modals.isOpen && !navFocus}
            onTabOut={() => setNavFocus(true)}
            attachments={pending}
            onRemoveLast={() => setPending((p) => p.slice(0, -1))}
            onImagePaths={attachPaths}
            attachNote={attachNote}
            onFocusRequest={() => setNavFocus(false)}
            disabled={state.streaming}
            onSubmit={submit}
            extraCommands={skillCommands}
            prefill={prefill}
          />
        </box>
      </box>
      <Footer
        state={state}
        onToggleMemory={toggleMemory}
        onToggleTools={() => dispatchAction("toggle_tools")}
        onTemperature={openTemperature}
      />
    </box>
  );
}

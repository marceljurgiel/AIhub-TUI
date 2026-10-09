import { useCallback, useEffect, useRef, useState } from "react";
import { singleLinePaste, looksLikeImagePaths } from "../clipboard.ts";
import { decodePasteBytes, stripAnsiSequences, type PasteEvent, type EditBufferRenderable } from "@opentui/core";
import type { Attachment } from "../bridge/types.ts";
import { useBindings } from "@opentui/keymap/react";
import { theme } from "../theme.ts";
import { filterSlash as filterBase, type SlashCommand } from "../slash.ts";
import { LAYER } from "../keymap/AppKeymap.tsx";
import { SlashSuggest } from "./SlashSuggest.tsx";

/**
 * The chat prompt box: a "/command" autocomplete popup, prompt-history recall,
 * and Enter to submit.
 *
 * Two OpenTUI details shape this component.
 *
 * 1. **`onInput`, not `onChange`.** `InputRenderable` emits INPUT on every
 *    keystroke but CHANGE only on commit (blur/submit), so a controlled field
 *    that mirrors each keystroke has to listen to INPUT. `onChange` is the
 *    right choice only when you want the committed value.
 *
 * 2. **The renderable owns the text.** React batches the per-keystroke updates,
 *    so a fast typist can press Enter before the mirrored state has re-rendered
 *    and submit a stale value. Every read goes through `current()` and every
 *    write through `setValue()`, which pushes into the renderable first.
 *
 * Enter stays on the input's own `onSubmit` rather than moving into the keymap:
 * `InputRenderable` already binds return/kpenter/linefeed to submit, and going
 * through the widget's own contract keeps the value and the event in sync.
 */
export function ChatInput({
  focused,
  disabled,
  onSubmit,
  extraCommands = [],
  prefill,
  onTabOut,
  onFocusRequest,
  attachments = [],
  onRemoveLast,
  onImagePaths,
  attachNote,
}: {
  focused: boolean;
  disabled: boolean;
  onSubmit: (text: string) => void;
  /** More suggestions, e.g. one "/skill <name>" per skill. */
  extraCommands?: SlashCommand[];
  /** Put text in the box (a new `seq` each time). */
  prefill?: { text: string; seq: number };
  /** Tab in an empty box: hand the keyboard to the sidebar menu. */
  onTabOut?: () => void;
  /** Clicked while something else had the keyboard. */
  onFocusRequest?: () => void;
  /** Images waiting to go with the next message. */
  attachments?: Attachment[];
  /** Backspace in an empty prompt drops the last attachment. */
  onRemoveLast?: () => void;
  /** Pasted text that is only image paths: attach them (resolves false when
   *  they couldn't be, and the text is pasted after all). */
  onImagePaths?: (text: string) => Promise<boolean>;
  /** A warning shown with the attachments (e.g. the model can't see). */
  attachNote?: string;
}) {
  const filterSlash = (t: string) => filterBase(t, extraCommands);
  const [text, setText] = useState("");
  const [slashHi, setSlashHi] = useState(0);
  const [histPos, setHistPos] = useState(-1);
  const hist = useRef<string[]>([]);
  const el = useRef<any>(null);
  const bind = useCallback((node: any) => {
    el.current = node;
  }, []);

  /** Authoritative current text (renderable first, mirrored state as fallback). */
  const current = () => (el.current ? String(el.current.value ?? "") : text);

  /** Write through to the renderable so the two never drift apart. */
  const setValue = (v: string) => {
    if (el.current) el.current.value = v;
    setText(v);
  };

  // Backspace removes the last attachment — only while the prompt is empty
  // (the layer is off otherwise, so backspace edits text as usual).
  const attachState = useRef({ count: 0, remove: () => {} });
  attachState.current = { count: attachments.length, remove: () => onRemoveLast?.() };
  useBindings(
    () => ({
      priority: LAYER.input,
      enabled: () =>
        gate.current.focused && !gate.current.disabled && attachState.current.count > 0 && current() === "",
      commands: [{ name: "prompt.unattach", run: () => attachState.current.remove() }],
      bindings: [{ key: "backspace", cmd: "prompt.unattach" }],
    }),
    [],
  );

  const handlePaste = function (this: EditBufferRenderable, event: PasteEvent) {
    const text = stripAnsiSequences(decodePasteBytes(event.bytes));
    if (onImagePaths && looksLikeImagePaths(text)) {
      event.preventDefault();
      const field = this;
      onImagePaths(text).then((ok) => {
        if (!ok) field.insertText(text.replace(/\s*\r?\n\s*/g, " "));
      });
      return;
    }
    singleLinePaste.call(this, event);
  };

  useEffect(() => {
    if (prefill) setValue(prefill.text);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill?.seq]);

  const items = filterSlash(text);
  const hi = Math.min(slashHi, Math.max(0, items.length - 1));

  const handleEnter = () => {
    if (!focused || disabled) return;
    const value = current();
    // Only image paths, arrived as typing rather than a paste (drag and drop
    // in some terminals, over SSH): attach them instead of sending the path.
    if (onImagePaths && looksLikeImagePaths(value) && !imageEnter.current) {
      imageEnter.current = true;
      const typed = value;
      setValue("");
      onImagePaths(typed)
        .then((ok) => {
          if (!ok) send(typed.trim());       // not image files: on as typed
        })
        .finally(() => (imageEnter.current = false));
      return;
    }
    const live = filterSlash(value);
    const chosen = live.length ? live[Math.min(slashHi, live.length - 1)]! : null;
    // Enter accepts the highlighted suggestion — unless the text already IS
    // that command, in which case it runs (no second Enter needed).
    if (chosen && chosen.cmd !== value.trim()) {
      setValue(chosen.cmd + " ");
      setSlashHi(0);
      return;
    }
    send(value.trim());
  };

  const send = (v: string) => {
    if (!v && !attachments.length) return;      // an image alone may be sent
    if (v) hist.current.push(v);
    if (hist.current.length > 100) hist.current.shift();
    setHistPos(-1);
    setValue("");
    onSubmit(v);
  };
  const imageEnter = useRef(false);

  // Input-layer bindings: highest non-modal priority, so Up/Down drive the
  // slash popup and prompt history instead of the input's own cursor motion.
  // `enabled` is read at dispatch time, so the layer registers once.
  const gate = useRef({ focused, disabled });
  gate.current = { focused, disabled };
  const handlers = useRef({ accept: () => {}, up: () => {}, down: () => {} });

  handlers.current.accept = () => {
    const live = filterSlash(current());
    if (!live.length) {
      if (!current().trim()) onTabOut?.();
      return;
    }
    setValue(live[Math.min(slashHi, live.length - 1)]!.cmd + " ");
    setSlashHi(0);
  };
  handlers.current.up = () => {
    const value = current();
    const live = filterSlash(value);
    if (live.length) return setSlashHi((h) => (h - 1 + live.length) % live.length);
    if (value !== "" && histPos === -1) return;
    const h = hist.current;
    if (!h.length) return;
    const pos = histPos === -1 ? h.length - 1 : Math.max(0, histPos - 1);
    setHistPos(pos);
    setValue(h[pos]!);
  };
  handlers.current.down = () => {
    const live = filterSlash(current());
    if (live.length) return setSlashHi((h) => (h + 1) % live.length);
    if (histPos === -1) return;
    const h = hist.current;
    if (histPos < h.length - 1) {
      const pos = histPos + 1;
      setHistPos(pos);
      setValue(h[pos]!);
    } else {
      setHistPos(-1);
      setValue("");
    }
  };

  useBindings(
    () => ({
      priority: LAYER.input,
      enabled: () => gate.current.focused && !gate.current.disabled,
      commands: [
        { name: "prompt.up", run: () => void handlers.current.up() },
        { name: "prompt.down", run: () => void handlers.current.down() },
        { name: "prompt.accept", run: () => void handlers.current.accept() },
      ],
      bindings: [
        { key: "up", cmd: "prompt.up" },
        { key: "down", cmd: "prompt.down" },
        { key: "tab", cmd: "prompt.accept" },
      ],
    }),
    [],
  );

  return (
    <box flexDirection="column" flexShrink={0} onMouseDown={() => onFocusRequest?.()}>
      <SlashSuggest commands={items} highlight={hi} />
      {attachments.length ? (
        <box flexDirection="column" flexShrink={0} marginLeft={2} marginRight={1}>
          <text>
            {attachments.map((a, i) => (
              <span key={a.id + i}>
                <span fg={theme.accentSoft} bg={theme.bg2}>{` ▣ ${a.name} · ${a.width}×${a.height} · ${a.kb} KB `}</span>
                <span>{" "}</span>
              </span>
            ))}
            <span fg={theme.fg2}>{"  ⌫ removes the last"}</span>
          </text>
          {attachNote ? <text fg={theme.warn}>{attachNote}</text> : null}
        </box>
      ) : null}
      <box
        minHeight={3}
        border
        borderStyle="rounded"
        borderColor={
          disabled ? theme.border : focused ? theme.accent : theme.borderStrong
        }
        backgroundColor={theme.bg1}
        marginLeft={1}
        marginRight={1}
        marginBottom={1}
        paddingLeft={1}
        paddingRight={1}
      >
        <input
          onPaste={handlePaste}
          ref={bind}
          value={text}
          onInput={(v: string) => {
            setText(v);
            if (histPos !== -1) setHistPos(-1);
          }}
          onSubmit={handleEnter}
          focused={focused && !disabled}
          placeholder={disabled ? "streaming… (Esc to cancel)" : "Message AIhub…  (/ for commands)"}
          backgroundColor={theme.bg1}
          textColor={theme.fg0}
          placeholderColor={theme.fg2}
          cursorColor={theme.accent}
        />
      </box>
    </box>
  );
}

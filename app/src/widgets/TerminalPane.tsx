import { useEffect, useRef } from "react";
import { extend } from "@opentui/react";
import { EmbeddedTerminalRenderable } from "@opentui/core";
import { theme, fit } from "../theme.ts";
import { useThemeVersion } from "../state/useTheme.ts";
import { startShell, type Shell } from "../terminal/pty.ts";

// OpenTUI's VT emulator, as a JSX element.
extend({ "embedded-terminal": EmbeddedTerminalRenderable });
declare module "@opentui/react" {
  interface OpenTUIComponents {
    "embedded-terminal": typeof EmbeddedTerminalRenderable;
  }
}

export type TerminalOptions = {
  /** Tests run a known shell; the user gets $SHELL. */
  shell?: string;
  args?: string[];
  /** Injectable for tests: Windows has no PTY in Bun. */
  platform?: string;
};

/**
 * A real shell beside the chat (F8). It starts once the panel knows its size
 * and lives until it exits (`exit`, Ctrl+D) or the panel closes; while it has
 * focus every key is the shell's — ChatScreen keeps only F8 for itself.
 */
export function TerminalPane({
  cwd,
  focused,
  width,
  options,
  command,
  onExit,
  onFocusRequest,
}: {
  cwd: string;
  focused: boolean;
  /** Run this instead of an interactive shell (e.g. the Ollama update);
   *  the panel waits for Enter at the end so the output can be read. */
  command?: string;
  /** Columns the panel has (for the title line). */
  width: number;
  options?: TerminalOptions;
  onExit: (code: number) => void;
  onFocusRequest: () => void;
}) {
  useThemeVersion();
  const term = useRef<EmbeddedTerminalRenderable | null>(null);
  const shell = useRef<Shell | null>(null);
  const exitRef = useRef(onExit);
  exitRef.current = onExit;

  useEffect(() => () => shell.current?.kill(), []);
  // Focus follows the prop (keys reach the emulator only while focused).
  useEffect(() => {
    if (focused) term.current?.focus();
    else term.current?.blur();
  }, [focused]);

  /** First size: start the shell at it; later sizes: tell the shell. */
  const resized = (cols: number, rows: number) => {
    if (shell.current) return shell.current.resize(cols, rows);
    shell.current = startShell({
      cwd,
      cols,
      rows,
      shell: options?.shell,
      args: command
        ? ["-c", `${command}; s=$?; echo; printf 'Finished (exit %s) — press Enter to close ' "$s"; read _; exit $s`]
        : options?.args,
      onData: (data) => term.current?.write(data),
      onExit: (code) => {
        shell.current = null;
        exitRef.current(code);
      },
    });
  };

  const home = process.env.HOME || "";
  const where = home && (cwd === home || cwd.startsWith(home + "/")) ? "~" + cwd.slice(home.length) : cwd;
  const hint = focused ? "F8 back to chat" : "F8 to type here";
  return (
    <box
      flexDirection="column"
      flexGrow={1}
      flexBasis={0}
      border
      borderStyle="rounded"
      borderColor={focused ? theme.accent : theme.border}
      onMouseDown={onFocusRequest}
    >
      <box flexDirection="row" justifyContent="space-between" paddingLeft={1} paddingRight={1} flexShrink={0}>
        <text fg={focused ? theme.fg0 : theme.fg2}>
          {fit(command ? `running · ${command}` : `terminal · ${where}`, Math.max(8, width - hint.length - 6))}
        </text>
        <text fg={focused ? theme.accentSoft : theme.fg2}>{hint}</text>
      </box>
      {/* Sized by the layout: without width/height it takes a fixed 80×24
          and spills over the frame. */}
      <embedded-terminal
        ref={term}
        width="auto"
        height="auto"
        flexGrow={1}
        onData={(data: Uint8Array) => shell.current?.write(data)}
        onTerminalResize={resized}
      />
    </box>
  );
}

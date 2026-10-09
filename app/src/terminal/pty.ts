/**
 * The shell behind the terminal panel: a process in a real pseudo-terminal
 * (Bun.spawn with `terminal`). Bun has PTYs on Linux and macOS only, so on
 * Windows the panel says so instead of starting anything.
 */

export function ptySupported(platform: string = process.platform): boolean {
  return platform !== "win32";
}

// Shells still running, ended when AIhub exits however it exits.
const live = new Set<{ kill: () => void }>();
let hooked = false;

export type Shell = {
  /** Keystrokes, pastes and terminal replies for the shell. */
  write: (data: string | Uint8Array) => void;
  resize: (cols: number, rows: number) => void;
  /** End the shell (onExit still fires). */
  kill: () => void;
};

export function startShell(opts: {
  cwd: string;
  cols: number;
  rows: number;
  onData: (data: Uint8Array) => void;
  onExit: (code: number) => void;
  /** Default: $SHELL, else /bin/sh. */
  shell?: string;
  /** Default: ["-i"] (interactive). */
  args?: string[];
  env?: Record<string, string | undefined>;
}): Shell {
  const shell = opts.shell || process.env.SHELL || "/bin/sh";
  let done = false;
  if (!hooked) {
    hooked = true;
    process.once("exit", () => live.forEach((s) => s.kill()));
  }
  const proc = Bun.spawn([shell, ...(opts.args ?? ["-i"])], {
    cwd: opts.cwd,
    env: { ...process.env, ...opts.env, TERM: "xterm-256color", COLORTERM: "truecolor" },
    terminal: {
      cols: Math.max(1, opts.cols),
      rows: Math.max(1, opts.rows),
      data: (_t, data) => opts.onData(data),
    },
  });
  // The process ending (exit, Ctrl+D, kill) is what closes the panel.
  const handle = { kill: () => !done && proc.kill("SIGHUP") };
  live.add(handle);
  void proc.exited.then((code) => {
    done = true;
    live.delete(handle);
    try {
      proc.terminal?.close();
    } catch {
      // already closed
    }
    opts.onExit(code ?? 0);
  });
  return {
    write: (data) => {
      if (!done) proc.terminal?.write(data);
    },
    resize: (cols, rows) => {
      if (!done) proc.terminal?.resize(Math.max(1, cols), Math.max(1, rows));
    },
    kill: () => handle.kill(),
  };
}

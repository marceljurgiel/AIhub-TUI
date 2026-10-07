/**
 * BridgeClient — spawns the Python engine (aihub.bridge) and speaks NDJSON
 * over its stdio. Provides request() for one-shot calls and stream() for
 * streaming calls (chat.turn, download.*), plus cancel()/permission() control
 * messages.
 */
import { sanitizingReviver } from "./sanitize.ts";
import { appendFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { BridgeMessage, StreamHandlers } from "./types.ts";

type Pending = {
  resolve: (data: any) => void;
  reject: (err: Error) => void;
  handlers?: StreamHandlers;
};

/** ~/.aihub/opentui-bridge.err.log, or AIHUB_ERR_LOG (the test preload points
 *  it at a temp file so test runs don't write into the user's log). */
function errLogPath(): string {
  return process.env.AIHUB_ERR_LOG || join(homedir(), ".aihub", "opentui-bridge.err.log");
}

/** Append a line to the bridge error log (never throws). */
export function debugLog(msg: string) {
  try {
    appendFileSync(errLogPath(), `${new Date().toISOString()} ${msg}\n`);
  } catch {
    /* ignore */
  }
}

/**
 * Resolve the command that launches the Python bridge. Overridable via
 * AIHUB_BRIDGE_CMD (space-separated). Defaults to the AIhub-TUI venv python
 * running `-m aihub.bridge`.
 */
function resolveBridgeCmd(): string[] {
  const override = process.env.AIHUB_BRIDGE_CMD;
  if (override && override.trim()) return override.trim().split(/\s+/);
  // The engine lives next to the app (repo root = app/..), unless told otherwise.
  const core = process.env.AIHUB_CORE_DIR || join(import.meta.dir, "..", "..", "..");
  const venvPython =
    process.platform === "win32"
      ? join(core, ".venv", "Scripts", "python.exe")
      : join(core, ".venv", "bin", "python");
  return [venvPython, "-m", "aihub.bridge"];
}

export class BridgeClient {
  private proc: Bun.Subprocess<"pipe", "pipe", "pipe"> | null = null;
  private nextId = 1;
  private pending = new Map<number, Pending>();
  private buffer = "";
  private readyResolvers: Array<(v: { version: string }) => void> = [];
  /** The ready banner, once received — kept so a late ready() still gets the
   *  engine version (it used to answer "?", shown as "core ?" in the footer). */
  private readyInfo: { version: string } | null = null;
  private cwd: string;
  private cmd: string[];

  constructor() {
    this.cmd = resolveBridgeCmd();
    this.cwd = process.env.AIHUB_CORE_DIR || join(import.meta.dir, "..", "..", "..");
  }

  /** Launch the bridge subprocess and start reading its stdout. */
  start(): void {
    this.proc = Bun.spawn(this.cmd, {
      cwd: this.cwd,
      stdin: "pipe",
      stdout: "pipe",
      stderr: "pipe",
      // The engine runs inside its own checkout; tools must use the directory
      // the user launched aihub from (see aihub/tools/workdir.py).
      env: { ...process.env, PYTHONUTF8: "1", AIHUB_WORKDIR: process.env.AIHUB_WORKDIR || process.cwd() },
    }) as Bun.Subprocess<"pipe", "pipe", "pipe">;
    this.readStdout();
    this.drainStderr();
    this.proc.exited.then((code) => {
      debugLog(`bridge exited code=${code}`);
      const err = new Error(`bridge process exited (code ${code})`);
      for (const p of this.pending.values()) p.reject(err);
      this.pending.clear();
    });
  }

  /** Wait until the bridge emits its `ready` banner. */
  ready(): Promise<{ version: string }> {
    if (this.readyInfo) return Promise.resolve(this.readyInfo);
    return new Promise((resolve) => this.readyResolvers.push(resolve));
  }

  private async readStdout() {
    const stream = this.proc!.stdout as ReadableStream<Uint8Array>;
    const decoder = new TextDecoder();
    for await (const chunk of stream) {
      this.buffer += decoder.decode(chunk, { stream: true });
      let nl: number;
      while ((nl = this.buffer.indexOf("\n")) >= 0) {
        const line = this.buffer.slice(0, nl).trim();
        this.buffer = this.buffer.slice(nl + 1);
        if (line) this.handleLine(line);
      }
    }
  }

  private async drainStderr() {
    const stream = this.proc!.stderr as ReadableStream<Uint8Array>;
    const decoder = new TextDecoder();
    for await (const chunk of stream) {
      const text = decoder.decode(chunk, { stream: true });
      if (text.trim()) debugLog(`[py] ${text.trimEnd()}`);
    }
  }

  private handleLine(line: string) {
    let msg: BridgeMessage;
    try {
      // Strip terminal control characters from every string the engine sends
      // (model output, tool results, file names…) before any of it renders.
      msg = JSON.parse(line, sanitizingReviver);
    } catch {
      debugLog(`bad JSON: ${line}`);
      return;
    }

    // Global events (id === null), e.g. the ready banner.
    if (msg.id === null || msg.id === undefined) {
      if (msg.event === "ready") {
        const info = { version: msg.data?.version ?? "?" };
        this.readyInfo = info;
        this.readyResolvers.splice(0).forEach((r) => r(info));
      }
      return;
    }

    const p = this.pending.get(msg.id);
    if (!p) return;

    if (msg.error !== undefined) {
      this.pending.delete(msg.id);
      p.reject(new Error(msg.error));
      return;
    }
    if (msg.done) {
      this.pending.delete(msg.id);
      p.resolve(msg.data ?? {});
      return;
    }
    if (msg.event && p.handlers?.onEvent) {
      p.handlers.onEvent(msg.event, msg.data ?? {});
    }
  }

  private write(obj: unknown) {
    const w = this.proc?.stdin;
    if (!w) return;
    (w as any).write(JSON.stringify(obj) + "\n");
    (w as any).flush?.();
  }

  /** One-shot request → resolves with the `done` payload. */
  request<T = any>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    const id = this.nextId++;
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.write({ id, method, params });
    });
  }

  /**
   * Streaming request → onEvent fires per event; the promise resolves with the
   * terminating `done` payload. Returns the request id so callers can cancel.
   */
  stream(
    method: string,
    params: Record<string, unknown>,
    handlers: StreamHandlers,
  ): { id: number; done: Promise<any> } {
    const id = this.nextId++;
    const done = new Promise<any>((resolve, reject) => {
      this.pending.set(id, { resolve, reject, handlers });
      this.write({ id, method, params });
    });
    return { id, done };
  }

  /** Cancel an in-flight streaming request (chat.turn / download.*). */
  cancel(requestId: number) {
    this.write({ method: "chat.cancel", params: { request_id: requestId } });
  }

  /** Answer an agent plan-mode permission request. */
  permission(requestId: number, allow: boolean) {
    this.write({ method: "chat.permission", params: { request_id: requestId, allow } });
  }

  destroy() {
    try {
      this.proc?.stdin?.end?.();
    } catch {
      /* ignore */
    }
    this.proc?.kill();
  }
}

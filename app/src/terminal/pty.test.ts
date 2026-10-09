/** The shell behind the terminal panel: a real PTY (Linux/macOS). */
import { test, expect } from "bun:test";
import { startShell, ptySupported } from "./pty.ts";

const posix = process.platform !== "win32";

function collect() {
  let out = "";
  return {
    onData: (b: Uint8Array) => (out += new TextDecoder().decode(b)),
    text: () => out,
  };
}

async function until(pred: () => boolean, ms = 5000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (pred()) return;
    await new Promise((r) => setTimeout(r, 20));
  }
  throw new Error("timed out");
}

test("supported on Linux and macOS, not on Windows", () => {
  expect(ptySupported("linux")).toBe(true);
  expect(ptySupported("darwin")).toBe(true);
  expect(ptySupported("win32")).toBe(false);
});

test.skipIf(!posix)("a shell runs in a real terminal: output, size, input, exit", async () => {
  const out = collect();
  let exited = null as number | null;
  const sh = startShell({
    cwd: "/",
    cols: 80,
    rows: 24,
    shell: "/bin/sh",
    onData: out.onData,
    onExit: (code) => (exited = code),
  });
  sh.write("stty size; pwd; printf 'he''llo\\n'\n");
  await until(() => out.text().includes("hello"));
  expect(out.text()).toContain("24 80");
  expect(out.text()).toMatch(/\r?\n\/\r?\n/);              // started in cwd

  sh.resize(100, 30);
  sh.write("stty size\n");
  await until(() => out.text().includes("30 100"));

  sh.write("exit 3\n");
  await until(() => exited !== null);
  expect(exited).toBe(3);
});

test.skipIf(!posix)("kill ends the shell", async () => {
  let exited = false;
  const sh = startShell({ cwd: "/", cols: 80, rows: 24, shell: "/bin/sh", onData: () => {}, onExit: () => (exited = true) });
  sh.kill();
  await until(() => exited);
});

test.skipIf(!posix)("the shell sees a colour terminal", async () => {
  const out = collect();
  const sh = startShell({ cwd: "/", cols: 80, rows: 24, shell: "/bin/sh", onData: out.onData, onExit: () => {} });
  sh.write("echo T=$TERM C=$COLORTERM\n");
  await until(() => out.text().includes("T=xterm-256color C=truecolor"));
  sh.kill();
});

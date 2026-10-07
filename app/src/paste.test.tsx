import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { AppTree, MockBridge } from "./test-tree.tsx";
import type { BridgeClient } from "./bridge/client.ts";

let setup: Awaited<ReturnType<typeof testRender>> | undefined;
afterEach(() => {
  setup?.renderer.destroy();
  setup = undefined;
});

async function settle() {
  for (let i = 0; i < 6; i++) {
    await new Promise((r) => setTimeout(r, 30));
    await setup!.flush();
  }
  return setup!.captureCharFrame();
}

async function until(pred: (f: string) => boolean, tries = 40) {
  for (let i = 0; i < tries; i++) {
    const f = await settle();
    if (pred(f)) return f;
  }
  throw new Error("frame never matched:\n" + setup!.captureCharFrame());
}

class Bridge extends MockBridge {
  sent: any[] = [];
  override async request(method: string, params: any = {}): Promise<any> {
    if (method === "memory.load") return { content: "" };
    return super.request(method);
  }
  override stream(method: string, params: any, handlers: any) {
    if (method === "chat.turn") this.sent.push(params);
    return super.stream(method, params, handlers);
  }
}

async function boot(clipboard: () => Promise<string>) {
  const bridge = new Bridge();
  setup = await testRender(
    <AppTree client={bridge as unknown as BridgeClient} readClipboard={clipboard} />,
    { width: 110, height: 30 },
  );
  await until((f) => f.includes("llama3.2:3b"));
  return { t: setup, bridge };
}

const ctrlV = () => setup!.mockInput.pressKey("v", { ctrl: true });

test("Ctrl+V pastes the clipboard into the chat box; line breaks become spaces", async () => {
  const { t, bridge } = await boot(async () => "line one\nline two");
  ctrlV();
  await until((f) => f.includes("line one line two"));
  t.mockInput.pressEnter();
  await settle();
  expect(bridge.sent.at(-1).messages.at(-1).content).toBe("line one line two");
});

test("a terminal paste (Ctrl+Shift+V) doesn't glue lines together either", async () => {
  await boot(async () => "");
  await setup!.mockInput.pasteBracketedText("first\nsecond");
  await until((f) => f.includes("first second"));
});

test("Ctrl+V pastes into a settings field (single line)", async () => {
  const { t } = await boot(async () => "gpu-box.lan\n");
  t.mockInput.pressKey("F3");
  await until((f) => f.includes("Ollama server"));
  t.mockInput.pressKey("TAB");
  await settle();
  ctrlV();
  const frame = await until((f) => /Ollama server\s+gpu-box\.lan/.test(f));
  expect(frame).not.toMatch(/gpu-box\.lan\s*\n.*gpu-box/);
});

test("Ctrl+V pastes into the model picker filter", async () => {
  const { t } = await boot(async () => "qwen");
  t.mockInput.pressKey("o", { ctrl: true });
  await until((f) => f.includes("Models"));
  t.mockInput.pressKey("/");
  await settle();
  ctrlV();
  await until((f) => f.includes("qwen"));
});

test("escape sequences in the clipboard are stripped", async () => {
  await boot(async () => "safe\x1b[31mRED\x1b[0m text");
  ctrlV();
  const frame = await until((f) => f.includes("safeRED text"));
  expect(frame).not.toContain("\x1b");
});

test("a failing clipboard doesn't break anything", async () => {
  const { t } = await boot(async () => {
    throw new Error("no clipboard tool found");
  });
  ctrlV();
  await settle();
  await t.mockInput.typeText("still typing");
  await until((f) => f.includes("still typing"));
});

// ── Ctrl+A select all ────────────────────────────────────────────────────────

/** The chat input's current line (inside its rounded box). */
function chatLine(frame: string) {
  const lines = frame.split("\n").map((l) => l.slice(40));   // right of the sidebar
  const top = lines.findLastIndex((l) => l.includes("╭"));
  return lines[top + 1]!.replace(/[│]/g, "").trim();
}

for (const [what, act, expected] of [
  ["typing replaces it", async () => setup!.mockInput.typeText("new"), "new"],
  ["backspace clears it", async () => setup!.mockInput.pressBackspace(), "Message AIhub…  (/ for commands)"],
  ["Ctrl+V replaces it", async () => ctrlV(), "PASTED"],
] as const) {
  test(`Ctrl+A selects all in the chat box; ${what}`, async () => {
    const { t } = await boot(async () => "PASTED");
    await t.mockInput.typeText("hello world");
    await settle();
    t.mockInput.pressKey("a", { ctrl: true });
    await settle();
    await act();
    const frame = await settle();
    expect(chatLine(frame)).toBe(expected);
  });
}

test("Ctrl+A works in a settings field too", async () => {
  const { t } = await boot(async () => "gpu-box.lan");
  t.mockInput.pressKey("F3");
  await until((f) => f.includes("Ollama server"));
  t.mockInput.pressKey("TAB");
  await settle();
  await t.mockInput.typeText("wrong-address");
  await settle();
  t.mockInput.pressKey("a", { ctrl: true });
  await settle();
  ctrlV();
  const frame = await until((f) => /Ollama server\s+gpu-box\.lan\s/.test(f));
  expect(frame).not.toContain("wrong-address");
});

// ── Long pastes keep the layout ──────────────────────────────────────────────

test("a long paste scrolls inside a settings field instead of reshaping the dialog", async () => {
  const long = "http://" + "very-long-host-name.".repeat(8) + "example.com:11434";
  const { t } = await boot(async () => long);
  t.mockInput.pressKey("F3");
  const before = (await until((f) => f.includes("Ollama server"))).split("\n");
  t.mockInput.pressKey("TAB");
  await settle();
  ctrlV();
  const after = (await until((f) => f.includes("example.com:11434"))).split("\n");
  const rowOf = (lines: string[], s: string) => lines.findIndex((l) => l.includes(s));
  // Label intact, and every row below it where it was.
  expect(after[rowOf(after, "Ollama server")]).toMatch(/Ollama server {6}/);
  for (const label of ["Working directory", "Default model", "Default context", "Tool calling", "Memory"])
    expect(rowOf(after, label)).toBe(rowOf(before, label));
  // The dialog's right border didn't move.
  const border = (lines: string[]) => lines[rowOf(lines, "Ollama server")]!.lastIndexOf("│");
  expect(border(after)).toBe(border(before));
});

test("a long paste scrolls inside the chat box", async () => {
  const long = "word ".repeat(80) + "END";
  await boot(async () => long);
  const before = setup!.captureCharFrame().split("\n").length;
  ctrlV();
  const frame = await until((f) => f.includes("END"));
  expect(frame.split("\n").length).toBe(before);
  expect(chatLine(frame).endsWith("END")).toBe(true);
});

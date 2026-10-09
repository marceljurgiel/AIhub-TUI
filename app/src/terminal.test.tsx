/** The terminal panel: F8 opens a real shell beside the chat; while it has
 *  focus every key is the shell's, except F8, which goes back to the chat. */
import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { AppTree, MockBridge } from "./test-tree.tsx";
import { ChatScreen } from "./screens/ChatScreen.tsx";
import type { BridgeClient } from "./bridge/client.ts";

const posix = process.platform !== "win32";

let setup: Awaited<ReturnType<typeof testRender>> | undefined;
afterEach(() => {
  setup?.renderer.destroy();
  setup = undefined;
}, 20000);

async function until(pred: (f: string) => boolean, tries = 120) {
  for (let i = 0; i < tries; i++) {
    await new Promise((r) => setTimeout(r, 40));
    await setup!.flush();
    const f = setup!.captureCharFrame();
    if (pred(f)) return f;
  }
  throw new Error("frame never matched:\n" + setup!.captureCharFrame());
}

class TermBridge extends MockBridge {
  calls: Array<[string, any]> = [];
  override async request(method: string, params: any = {}): Promise<any> {
    this.calls.push([method, params]);
    return super.request(method);
  }
}

const BASH = Bun.which("bash");

async function boot(opts: { width?: number; platform?: string; clipboard?: string; bash?: boolean } = {}) {
  const bridge = new TermBridge();
  setup = await testRender(
    <AppTree client={bridge as unknown as BridgeClient} readClipboard={async () => opts.clipboard ?? ""}>
      <ChatScreen version="0.2.1" coreVersion="0.3.15" terminal={{
        shell: opts.bash ? BASH! : "/bin/sh",
        args: opts.bash ? ["--norc", "--noprofile", "-i"] : undefined,
        platform: opts.platform ?? "linux",
      }} />
    </AppTree>,
    { width: opts.width ?? 160, height: 34 },
  );
  await until((f) => f.includes("llama3.2:3b") && f.includes("tab menu"));
  return bridge;
}

const type = async (s: string) => {
  await setup!.mockInput.typeText(s);
  await new Promise((r) => setTimeout(r, 60));
};

test.skipIf(!posix)("F8 opens a shell beside the chat; what you type runs there", async () => {
  await boot();
  setup!.mockInput.pressKey("F8");
  await until((f) => f.includes("terminal ·") && f.includes("F8 back to chat"));
  await type("echo hi-from-$((40+2))");
  setup!.mockInput.pressEnter();
  const f = await until((x) => x.includes("hi-from-42"));
  expect(f).toContain("Welcome to AIhub");                    // the chat is still there
  // The shell has the panel's size — the inside of its frame — and the frame
  // is whole on the right (a fixed 80×24 emulator spilled over it).
  await type("stty size");
  setup!.mockInput.pressEnter();
  const g = await until((x) => /│\d+ \d+\s*│/.test(x));
  const lines = g.split("\n");
  const top = lines.find((l) => l.includes("╭") && l.lastIndexOf("╭") > 80)!;
  const inner = top.lastIndexOf("╮") - top.lastIndexOf("╭") - 1;
  const [, , cols] = g.match(/│(\d+) (\d+)\s*│/)!;
  expect(Number(cols)).toBe(inner);
  expect(lines.find((l) => l.includes("hi-from-42"))!.trimEnd().endsWith("│")).toBe(true);
}, 20000);

test.skipIf(!posix)("while the shell has focus, AIhub's keys are the shell's — except F8", async () => {
  const bridge = await boot();
  setup!.mockInput.pressKey("F8");
  await until((f) => f.includes("F8 back to chat"));
  setup!.mockInput.pressTab();                                  // not the menu
  await type("m");                                              // not the Models window
  setup!.mockInput.pressEscape();                               // not "cancel"
  await new Promise((r) => setTimeout(r, 200));
  await setup!.flush();
  let f = setup!.captureCharFrame();
  expect(f).not.toContain("↑↓ choose");
  expect(f).not.toContain("1 Installed");
  // F8 hands the keyboard back: typing goes to the chat box again.
  setup!.mockInput.pressKey("F8");
  f = await until((x) => x.includes("F8 to type here"));
  await type("hello chat");
  setup!.mockInput.pressEnter();
  // Sent as a chat message, not typed into the shell.
  await until((x) => x.includes("› YOU") && x.includes("hello chat"));
  expect(bridge.calls.some(([m]) => m === "chat.start")).toBe(true);
}, 20000);

test.skipIf(!posix || !BASH)("Ctrl+V pastes the clipboard into the shell; Ctrl+A is the shell's", async () => {
  await boot({ clipboard: "echo pasted-$((6*7))", bash: true });
  setup!.mockInput.pressKey("F8");
  await until((f) => f.includes("F8 back to chat"));
  setup!.mockInput.pressKey("v", { ctrl: true });
  await new Promise((r) => setTimeout(r, 150));
  setup!.mockInput.pressEnter();
  await until((x) => x.includes("pasted-42"));
  // Ctrl+A = start of line in the shell (not "select all"): "ho X" → "echo X".
  await type("ho line-$((1+1))");
  setup!.mockInput.pressKey("a", { ctrl: true });
  await type("ec");
  setup!.mockInput.pressEnter();
  await until((x) => x.includes("line-2"));
}, 20000);

test.skipIf(!posix)("exit in the shell closes the panel", async () => {
  await boot();
  setup!.mockInput.pressKey("F8");
  await until((f) => f.includes("F8 back to chat"));
  await type("exit");
  setup!.mockInput.pressEnter();
  const f = await until((x) => x.includes("Terminal closed."));
  expect(f).not.toContain("F8 back to chat");
}, 20000);

test("a narrow window says how wide it must be, and opens nothing", async () => {
  await boot({ width: 110 });
  setup!.mockInput.pressKey("F8");
  const f = await until((x) => x.includes("at least 120 columns"));
  expect(f).not.toContain("terminal ·");
}, 20000);

test("on Windows the panel says it needs Linux or macOS", async () => {
  await boot({ platform: "win32" });
  setup!.mockInput.pressKey("F8");
  const f = await until((x) => x.includes("needs Linux or macOS"));
  expect(f).not.toContain("terminal ·");
}, 20000);

test.skipIf(!posix)("a click on the chat box takes the keyboard back from the shell", async () => {
  await boot();
  setup!.mockInput.pressKey("F8");
  let f = await until((x) => x.includes("F8 back to chat"));
  // Click inside the chat's input box (its placeholder line).
  const lines = f.split("\n");
  const y = lines.findIndex((l) => l.includes("Message AIhub…"));
  await setup!.mockMouse.click(lines[y]!.indexOf("Message AIhub…") + 2, y);
  f = await until((x) => x.includes("F8 to type here"));
  await type("hi from a click");
  setup!.mockInput.pressEnter();
  await until((x) => x.includes("› YOU") && x.includes("hi from a click"));
}, 20000);

test.skipIf(!posix)("a click on the panel gives the shell the keyboard", async () => {
  await boot();
  setup!.mockInput.pressKey("F8");
  await until((x) => x.includes("F8 back to chat"));
  setup!.mockInput.pressKey("F8");
  const f = await until((x) => x.includes("F8 to type here"));
  const lines = f.split("\n");
  const y = lines.findIndex((l) => l.includes("F8 to type here")) + 3;
  await setup!.mockMouse.click(lines[y]!.length - 10, y);
  await until((x) => x.includes("F8 back to chat"));
}, 20000);

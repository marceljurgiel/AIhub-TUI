/** A newer Ollama at start: a note with the command when Ollama runs on
 *  another machine; on this one, an offer to run the update in the
 *  terminal panel, then a check that it worked. */
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

async function until(pred: (f: string) => boolean, tries = 150) {
  for (let i = 0; i < tries; i++) {
    await new Promise((r) => setTimeout(r, 40));
    await setup!.flush();
    const f = setup!.captureCharFrame();
    if (pred(f)) return f;
  }
  throw new Error("frame never matched:\n" + setup!.captureCharFrame());
}

const REMOTE = { server: "0.30.7", latest: "0.40.2", newer: true, local: false, host: "gpu-box.lan", how: "manual",
                 command: "curl -fsSL https://ollama.com/install.sh | sh" };

class UpdateBridge extends MockBridge {
  checks: any[] = [REMOTE];
  calls: string[] = [];
  override async request(method: string, params: any = {}): Promise<any> {
    this.calls.push(method);
    if (method === "ollama.update_check") return this.checks.length > 1 ? this.checks.shift() : this.checks[0];
    return super.request(method);
  }
}

/** The chat column's text as one line (the menu sits left of it, 40 wide). */
const chat = (f: string) => f.split("\n").map((l) => l.slice(40)).join(" ").replace(/\s+/g, " ");

async function boot(bridge: UpdateBridge, width = 160) {
  setup = await testRender(
    <AppTree client={bridge as unknown as BridgeClient}>
      <ChatScreen version="0.2.1" coreVersion="0.3.15" terminal={{ shell: "/bin/sh", platform: "linux" }} />
    </AppTree>,
    { width, height: 34 },
  );
  // Or the update prompt, whose backdrop covers the screen.
  await until((f) => f.includes("llama3.2:3b") || f.includes("Ollama update"));
}

test("Ollama on another machine: a note with the command to run there", async () => {
  const bridge = new UpdateBridge();
  await boot(bridge);
  const f = await until((x) => x.includes("Ollama 0.40.2 is out"));
  expect(chat(f)).toContain("gpu-box.lan has 0.30.7");
  expect(chat(f)).toContain("curl -fsSL https://ollama.com/install.sh | sh");
  expect(f).not.toContain("Update Ollama");                     // no offer to do it from here
}, 20000);

test("up to date: nothing is said", async () => {
  const bridge = new UpdateBridge();
  bridge.checks = [{ ...REMOTE, server: "0.40.2", newer: false }];
  await boot(bridge);
  await until(() => bridge.calls.includes("ollama.update_check"));
  await new Promise((r) => setTimeout(r, 200));
  await setup!.flush();
  expect(setup!.captureCharFrame()).not.toContain("is out");
}, 20000);

test.skipIf(!posix)("Ollama on this machine: Enter runs the update in the terminal panel, then checks it", async () => {
  const bridge = new UpdateBridge();
  bridge.checks = [
    { ...REMOTE, local: true, host: "localhost", how: "installer", command: "printf 'installer-ran\\n'" },
    { ...REMOTE, local: true, host: "localhost", how: "installer", server: "0.40.2", newer: false },
  ];
  await boot(bridge);
  await until((x) => x.includes("Update Ollama 0.30.7 → 0.40.2?"));
  await new Promise((r) => setTimeout(r, 150));                 // its keys bind after it draws
  setup!.mockInput.pressEnter();
  await until((x) => x.includes("installer-ran") && x.includes("press Enter to close"));
  setup!.mockInput.pressEnter();
  const f = await until((x) => x.includes("Ollama is now 0.40.2."));
  expect(f).not.toContain("terminal ·");
}, 20000);

test("Ollama on this machine, Esc: later — nothing runs", async () => {
  const bridge = new UpdateBridge();
  bridge.checks = [{ ...REMOTE, local: true, host: "localhost", how: "installer", command: "printf 'no\\n'" }];
  await boot(bridge);
  await until((x) => x.includes("Update Ollama 0.30.7 → 0.40.2?"));
  await new Promise((r) => setTimeout(r, 150));                 // its keys bind after it draws
  setup!.mockInput.pressEscape();
  const f = await until((x) => !x.includes("Update Ollama 0.30.7"));
  expect(f).not.toContain("terminal ·");
}, 20000);

test("Ollama's own app updates itself: just a note", async () => {
  const bridge = new UpdateBridge();
  bridge.checks = [{ ...REMOTE, local: true, host: "localhost", how: "app", command: "" }];
  await boot(bridge);
  const f = await until((x) => x.includes("Ollama 0.40.2 is out"));
  expect(chat(f)).toContain("Ollama app");
}, 20000);

test("a window too narrow for the panel: the command instead", async () => {
  const bridge = new UpdateBridge();
  bridge.checks = [{ ...REMOTE, local: true, host: "localhost", how: "installer" }];
  await boot(bridge, 110);
  await until((x) => x.includes("Update Ollama 0.30.7 → 0.40.2?"));
  await new Promise((r) => setTimeout(r, 150));                 // its keys bind after it draws
  setup!.mockInput.pressEnter();
  const f = await until((x) => chat(x).includes("run it yourself"));
  expect(chat(f)).toContain("https://ollama.com/install.sh | sh");      // a wrap may split "-fsSL"
}, 20000);

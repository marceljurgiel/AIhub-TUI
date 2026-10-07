import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { AppTree, MockBridge } from "./test-tree.tsx";
import type { BridgeClient } from "./bridge/client.ts";

let setup: Awaited<ReturnType<typeof testRender>> | undefined;
afterEach(() => {
  setup?.renderer.destroy();
  setup = undefined;
});

const tick = (ms = 30) => new Promise((r) => setTimeout(r, ms));
async function until(pred: (f: string) => boolean, tries = 50) {
  for (let i = 0; i < tries; i++) {
    await tick(40);
    await setup!.flush();
    const f = setup!.captureCharFrame();
    if (pred(f)) return f;
  }
  throw new Error("frame never matched:\n" + setup!.captureCharFrame());
}

/** Engine double: finishes chat turns at once and records memory/history calls. */
class LearnBridge extends MockBridge {
  calls: Array<[string, any]> = [];
  learnReply: any = { changes: [], cursor: 0 };
  override async request(method: string, params: any = {}): Promise<any> {
    this.calls.push([method, params]);
    if (method === "memory.learn") {
      const users = params.messages.filter((m: any) => m.role === "user").length;
      return { ...this.learnReply, cursor: users };
    }
    if (method === "memory.undo")
      return { reverted: [{ id: "c1", op: "undo", topic: "Editor", before: "VS Code", after: "Neovim" }] };
    if (method === "chat.finalize") return { path: "/tmp/x.json" };
    return super.request(method);
  }
  override stream(method: string, params: any, handlers: any) {
    if (method !== "chat.turn") return super.stream(method, params, handlers);
    const done = (async () => {
      await Promise.resolve();
      handlers.onEvent("text", { text: "ok" });
      return { messages: [...params.messages, { role: "assistant", content: "ok" }] };
    })();
    return { id: 1, done };
  }
  of(method: string) {
    return this.calls.filter(([m]) => m === method).map(([, p]) => p);
  }
}

async function boot(bridge = new LearnBridge()) {
  setup = await testRender(<AppTree client={bridge as unknown as BridgeClient} />, { width: 110, height: 32 });
  await until((f) => f.includes("llama3.2:3b"));
  return { t: setup, bridge };
}

async function send(text: string) {
  await setup!.mockInput.typeText(text);
  setup!.mockInput.pressEnter();
  await tick(60);
  await setup!.flush();
}

test("each finished turn autosaves the session to one file", async () => {
  const { bridge } = await boot();
  await send("first");
  await until(() => bridge.of("chat.finalize").length === 1);
  await send("second");
  await until(() => bridge.of("chat.finalize").length === 2);
  const [a, b] = bridge.of("chat.finalize");
  expect(a.auto).toBe(true);
  expect(a.start_time).toBe(b.start_time);                      // same session file
  expect(b.messages.filter((m: any) => m.role === "user").length).toBe(2);
});

test("learning runs once the user goes quiet, and only on new messages", async () => {
  const { bridge } = await boot();
  await send("I use Neovim");
  await until(() => bridge.of("memory.learn").length === 1);
  expect(bridge.of("memory.learn")[0].cursor).toBe(0);
  await send("and I live in Lisbon");
  await until(() => bridge.of("memory.learn").length === 2);
  expect(bridge.of("memory.learn")[1].cursor).toBe(1);          // first message not re-sent
});

test("learned changes show in the log and /memory undo reverts them", async () => {
  const bridge = new LearnBridge();
  bridge.learnReply = { changes: [{ id: "c1", op: "update", topic: "Editor", before: "Neovim", after: "VS Code" }] };
  await boot(bridge);
  await send("switched to VS Code");
  let frame = await until((f) => f.includes("✻ Remembered · Editor — VS Code"));
  expect(frame).toContain("(was: Neovim)");
  expect(frame).toContain("/memory undo");
  await send("/memory undo");
  frame = await until((f) => f.includes("✻ Undid · Editor — Neovim"));
  expect(bridge.of("memory.undo")).toHaveLength(1);
});

test("a new chat learns what's left of the old one and starts a fresh cursor", async () => {
  const { t, bridge } = await boot();
  await send("remember my cat is Mruczek");
  await until(() => bridge.of("memory.learn").length === 1);   // idle run, cursor 0
  await send("and my dog is Burek");
  t.mockInput.pressKey("n", { ctrl: true });                 // before the idle run
  await until(() => bridge.of("memory.learn").some((p) => p.cursor === 1));
  const ended = bridge.of("memory.learn").find((p) => p.cursor === 1)!;
  expect(ended.messages.some((m: any) => m.content === "and my dog is Burek")).toBe(true);
  const before = bridge.of("memory.learn").length;
  await send("hello again");
  await until(() => bridge.of("memory.learn").length > before);
  expect(bridge.of("memory.learn").at(-1).cursor).toBe(0);     // new session counts from 0
});

test("clearing the chat starts a new history file", async () => {
  const { t, bridge } = await boot();
  await send("one");
  await until(() => bridge.of("chat.finalize").length === 1);
  t.mockInput.pressKey("l", { ctrl: true });
  await tick(30);
  await send("two");
  await until(() => bridge.of("chat.finalize").length === 2);
  const [a, b] = bridge.of("chat.finalize");
  expect(a.start_time).not.toBe(b.start_time);
});

test("quitting saves the chat first", async () => {
  const { t, bridge } = await boot();
  await send("bye soon");
  await until(() => bridge.of("chat.finalize").length === 1);
  t.mockInput.pressKey("q", { ctrl: true });
  await until(() => bridge.of("chat.finalize").length === 2);
  expect(bridge.of("chat.finalize")[1].auto).toBe(true);
});

test("Enter on a partial slash command completes it; on an exact one runs it", async () => {
  const { t, bridge } = await boot();
  await t.mockInput.typeText("/memory un");
  t.mockInput.pressEnter();
  await until((f) => f.includes("/memory undo"));
  expect(bridge.of("memory.undo")).toHaveLength(0);          // only completed
  t.mockInput.pressEnter();
  await until(() => bridge.of("memory.undo").length === 1);   // now it ran
});

import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { AppTree, MockBridge } from "./test-tree.tsx";
import type { BridgeClient } from "./bridge/client.ts";
import { formatElapsed } from "./widgets/ActivityLine.tsx";

let setup: Awaited<ReturnType<typeof testRender>> | undefined;
afterEach(() => {
  setup?.renderer.destroy();
  setup = undefined;
});

async function until(pred: (f: string) => boolean, tries = 40) {
  for (let i = 0; i < tries; i++) {
    await new Promise((r) => setTimeout(r, 40));
    await setup!.flush();
    const f = setup!.captureCharFrame();
    if (pred(f)) return f;
  }
  throw new Error("frame never matched:\n" + setup!.captureCharFrame());
}

/** Chat turns driven by hand, so each phase can be observed. */
class TurnBridge extends MockBridge {
  turn: { id: number; emit: (e: string, d: any) => void; finish: (d: any) => void; params: any } | null = null;
  permissions: boolean[] = [];
  override permission(_id?: number, allow?: boolean) {
    this.permissions.push(!!allow);
  }
  override stream(method: string, params: any, handlers: any) {
    if (method !== "chat.turn") return super.stream(method, params, handlers);
    let finish!: (d: any) => void;
    const done = new Promise<any>((r) => (finish = r));
    this.turn = { id: 7, emit: (e, d) => handlers.onEvent(e, d), finish, params };
    return { id: 7, done };
  }
}

async function ask(text = "is 391 prime?") {
  const bridge = new TurnBridge();
  setup = await testRender(<AppTree client={bridge as unknown as BridgeClient} />, { width: 120, height: 32 });
  await until((f) => f.includes("llama3.2:3b"));
  await setup.mockInput.typeText(text);
  setup.mockInput.pressEnter();
  await until((f) => f.includes("esc to interrupt"));
  return { t: setup, bridge, turn: bridge.turn! };
}

test("before the first token the status says Working… with a timer", async () => {
  await ask();
  const frame = await until((f) => /Working… \(\d+s · esc to interrupt\)/.test(f));
  expect(frame).not.toContain("↵ send");              // hint replaced while busy
});

test("reasoning shows as Thinking… with a live preview, then is logged collapsed", async () => {
  const { turn } = await ask();
  turn.emit("thinking", { text: "First, check small primes.\n" });
  turn.emit("thinking", { text: "391 = 17 × 23, so not prime." });
  let frame = await until((f) => f.includes("Thinking…"));
  expect(frame).toContain("⎿ 391 = 17 × 23, so not prime.");

  turn.emit("text", { text: "No — 391 = 17 × 23." });
  frame = await until((f) => f.includes("Writing…"));
  expect(frame).toMatch(/✻ Thought for (<1|\d+)s/);

  turn.emit("round", { round: 0, text: "No — 391 = 17 × 23.", had_tool_calls: false });
  turn.finish({ messages: [...turn.params.messages, { role: "assistant", content: "No — 391 = 17 × 23." }] });
  frame = await until((f) => f.includes("↵ send"));
  expect(frame).not.toContain("esc to interrupt");
  expect(frame).toMatch(/✻ Thought for (<1|\d+)s/);
});

test("clicking the thought expands the reasoning", async () => {
  const { t, turn } = await ask();
  turn.emit("thinking", { text: "SECRET-REASONING-LINE" });
  turn.emit("text", { text: "done" });
  turn.finish({ messages: [...turn.params.messages, { role: "assistant", content: "done" }] });
  const frame = await until((f) => f.includes("✻ Thought for"));
  expect(frame).not.toContain("SECRET-REASONING-LINE");
  const lines = frame.split("\n");
  const y = lines.findIndex((l) => l.includes("✻ Thought for"));
  const x = lines[y]!.indexOf("✻");
  await t.mockMouse.click(x + 2, y);
  await until((f) => f.includes("SECRET-REASONING-LINE"));
});

test("tools and approvals get their own status", async () => {
  const { turn, bridge } = await ask("save notes");
  turn.emit("tool_call", { call_id: "c1", name: "read_file", arguments: { path: "a" } });
  await until((f) => f.includes("Running read_file…"));
  turn.emit("tool_result", { call_id: "c1", name: "read_file", arguments: {}, result: "ok", error: null, duration_ms: 1 });
  await until((f) => f.includes("Working…"));
  turn.emit("permission_request", { name: "write_file", arguments: { path: "a", content: "x" } });
  await until((f) => f.includes("Permission required"));
  setup!.mockInput.pressKey("y");
  await until((f) => f.includes("Running write_file…"));
  expect(bridge.permissions).toEqual([true]);
});

test("Esc while thinking keeps what was thought and clears the status", async () => {
  const { t, turn } = await ask();
  turn.emit("thinking", { text: "halfway through" });
  await until((f) => f.includes("Thinking…"));
  t.mockInput.pressEscape();
  const frame = await until((f) => f.includes("Stream cancelled."));
  expect(frame).toMatch(/✻ Thought for/);
  expect(frame).not.toContain("esc to interrupt");
});

test("elapsed time formatting", () => {
  expect(formatElapsed(0)).toBe("0s");
  expect(formatElapsed(14_900)).toBe("14s");
  expect(formatElapsed(65_000)).toBe("1m 05s");
  expect(formatElapsed(-5)).toBe("0s");
});

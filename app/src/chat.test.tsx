import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { AppTree, mockClient } from "./test-tree.tsx";

const SCRIPT = [
  { e: "text", d: { text: "Let me check. " } },
  { e: "usage", d: { prompt_tokens: 100, completion_tokens: 3, tps: 30 } },
  { e: "round", d: { round: 0, text: "Let me check. ", had_tool_calls: true } },
  { e: "tool_call", d: { call_id: "c1", name: "read_file", arguments: { path: "/etc/hostname" } } },
  {
    e: "tool_result",
    d: {
      call_id: "c1",
      name: "read_file",
      arguments: { path: "/etc/hostname" },
      result: "localhost",
      error: null,
      duration_ms: 5,
    },
  },
  { e: "text", d: { text: "The host is localhost." } },
  { e: "usage", d: { prompt_tokens: 120, completion_tokens: 8, tps: 30 } },
  { e: "round", d: { round: 1, text: "The host is localhost.", had_tool_calls: false } },
  { e: "final", d: { text: "The host is localhost." } },
];

let setup: Awaited<ReturnType<typeof testRender>> | undefined;
afterEach(() => {
  setup?.renderer.destroy();
  setup = undefined;
});

async function boot(script: typeof SCRIPT = []) {
  setup = await testRender(<AppTree client={mockClient(script)} />, { width: 110, height: 34 });
  await setup.waitForFrame((f) => f.includes("llama3.2:3b"), { maxPasses: 40 });
  return setup;
}

test("typing a message streams an assistant reply and renders a tool panel", async () => {
  const t = await boot(SCRIPT);

  await t.mockInput.typeText("what host is this");
  t.mockInput.pressEnter();
  // React batches the per-keystroke updates; give the submit a tick to land
  // before waiting on a frame.
  await new Promise((r) => setTimeout(r, 30));
  await t.flush();

  // The assistant body renders through the tree-sitter worker, which parses
  // off-thread — first parse includes WASM warm-up, so poll wall-clock rather
  // than counting frame passes.
  let frame = t.captureCharFrame();
  for (let i = 0; i < 40 && !frame.includes("The host is localhost."); i++) {
    await new Promise((r) => setTimeout(r, 100));
    await t.flush();
    frame = t.captureCharFrame();
  }

  expect(frame).toContain("what host is this"); // user bubble
  expect(frame).toContain("Let me check"); // first-round assistant text
  expect(frame).toContain("read_file"); // tool panel title
});

test("typing a slash shows the autocomplete popup", async () => {
  const t = await boot();

  await t.mockInput.typeText("/mem");
  const frame = await t.waitForFrame((f) => f.includes("/memoryadd"), { maxPasses: 30 });

  expect(frame).toContain("/memory");
  expect(frame).toContain("/memoryadd");
});

test("arrows scroll the slash popup through every command", async () => {
  const t = await boot();
  const { SLASH_COMMANDS } = await import("./slash.ts");
  await t.mockInput.typeText("/");
  let frame = await t.waitForFrame((f) => f.includes("/new") && f.includes("more"), { maxPasses: 30 });
  expect(frame).not.toContain("/cd ");
  for (let i = 0; i < SLASH_COMMANDS.length - 1; i++) {
    t.mockInput.pressArrow("down");
    await new Promise((r) => setTimeout(r, 15));
    await t.flush();
  }
  frame = t.captureCharFrame();
  expect(frame).toContain("/cd");                         // the last one is reachable
  expect(frame).toContain(`${SLASH_COMMANDS.length}/${SLASH_COMMANDS.length}`);
  expect(frame).not.toMatch(/\/new\s+Start/);              // scrolled past the top
  t.mockInput.pressArrow("down");                          // wraps to the first
  await new Promise((r) => setTimeout(r, 30));
  await t.flush();
  expect(t.captureCharFrame()).toMatch(/\/new\s+Start/);
});

test("a global chord fires while the chat input has focus", async () => {
  const t = await boot();

  // Ctrl+T toggles tools. The input is focused and would normally swallow the
  // key, but the keymap host runs ahead of it — the point of the global layer.
  await t.mockInput.typeText("hello");
  t.mockInput.pressKey("t", { ctrl: true });
  const frame = await t.waitForFrame((f) => /Tools (enabled|disabled)\./.test(f), {
    maxPasses: 30,
  });

  expect(frame).toMatch(/Tools (enabled|disabled)\./);
  // The chord must not have leaked a "t" into the prompt.
  expect(frame).toContain("hello");
});

test("bare-letter nav is suppressed while the input is focused", async () => {
  const t = await boot();

  // Put something in the log that new_chat would wipe.
  await t.mockInput.typeText("keep me");
  t.mockInput.pressEnter();
  await new Promise((r) => setTimeout(r, 30));
  await t.flush();
  await t.waitForFrame((f) => f.includes("keep me"), { maxPasses: 30 });

  // "n" is bound to new_chat on the nav layer. With the input focused the layer
  // is disabled, so this must be typed rather than clearing the conversation.
  await t.mockInput.typeText("n");
  await t.flush();
  const frame = t.captureCharFrame();

  expect(frame).toContain("keep me"); // nav did NOT fire
});

test("the startup model gets a hardware-sized context, not the 2048 default", async () => {
  const { MockBridge, AppTree } = await import("./test-tree.tsx");
  class Sized extends MockBridge {
    override async request(m: string): Promise<any> {
      return m === "hardware.recommend_context" ? { context: 16384 } : super.request(m);
    }
  }
  const { testRender } = await import("@opentui/react/test-utils");
  const t = await testRender(<AppTree client={new Sized() as any} />, { width: 110, height: 34 });
  try {
    await t.waitForFrame((f) => f.includes("16K CTX"), { maxPasses: 60 });
  } finally {
    t.renderer.destroy();
  }
});

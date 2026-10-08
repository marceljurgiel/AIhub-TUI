import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { AppTree, mockClient } from "./test-tree.tsx";

// Each test owns a renderer; tear it down so terminal state and native
// resources don't leak into the next one.
let setup: Awaited<ReturnType<typeof testRender>> | undefined;
afterEach(() => {
  setup?.renderer.destroy();
  setup = undefined;
});

test("shell renders header, sidebar nav, footer and welcome", async () => {
  setup = await testRender(<AppTree client={mockClient()} />, { width: 110, height: 32 });

  // Let the startup effects (config.get / backend.status / models.installed) settle.
  const frame = await setup.waitForFrame(
    (f) => f.includes("llama3.2:3b") && f.includes("New Chat"),
    { maxPasses: 40 },
  );

  for (const label of ["New Chat", "Agent", "Models", "History", "Memory", "Hardware", "Settings"]) {
    expect(frame).toContain(label);
  }
  expect(frame).toContain("Welcome to AIhub");
  expect(frame).toMatch(/mem ✓  tools ✓/);
  expect(frame).not.toContain("T 0.7");
  expect(frame).toContain("v0.2.1");
  expect(frame).toContain("core 0.3.15");
  expect(frame).toContain("llama3.2:3b");
});

test("size guard shows on a tiny terminal", async () => {
  setup = await testRender(<AppTree client={mockClient()} />, { width: 50, height: 12 });
  await setup.flush();
  expect(setup.captureCharFrame().toLowerCase()).toContain("too small");
});

test("footer: mem / tools only; temperature lives in Settings (e) and /temp", async () => {
  const { MockBridge } = await import("./test-tree.tsx");
  const calls: any[] = [];
  class B extends MockBridge {
    override async request(m: string, p: any = {}): Promise<any> {
      calls.push([m, p]);
      return m === "config.get" ? { ...(await super.request(m)), temperature: 0.4 } : m === "config.set" ? {} : super.request(m);
    }
  }
  setup = await testRender(<AppTree client={new B() as any} />, { width: 110, height: 32 });
  const until = async (pred: (f: string) => boolean) => {
    for (let i = 0; i < 80; i++) {
      await new Promise((r) => setTimeout(r, 40));
      await setup!.flush();
      const f = setup!.captureCharFrame();
      if (pred(f)) return f;
    }
    throw new Error("frame never matched:\n" + setup!.captureCharFrame());
  };
  const frame = await until((f) => f.includes("llama3.2:3b") && f.includes("mem ✓"));
  const last = frame.trimEnd().split("\n").at(-1)!;
  expect(last.trim()).toBe("mem ✓  tools ✓");                           // nothing else down there

  // Settings shows the temperature; e opens the editor, the row follows the save.
  setup.mockInput.pressKey("F3");
  await until((f) => /Temperature\s+0\.4 · precise and repeatable/.test(f));
  setup.mockInput.pressKey("e");
  await until((f) => f.includes("precise"));
  setup.mockInput.pressArrow("right");
  setup.mockInput.pressArrow("right");
  await until((f) => f.includes("0.6"));
  setup.mockInput.pressEnter();
  await until((f) => /Temperature\s+0\.6 · balanced/.test(f));
  expect(calls).toContainEqual(["config.set", { patch: { temperature: 0.6 } }]);

  // /temp still opens the same editor straight from the chat.
  setup.mockInput.pressEscape();
  await until((f) => !f.includes("e to change"));
  await setup.mockInput.typeText("/temp 0.3");
  setup.mockInput.pressEnter();
  await until(() => calls.some(([m, p]) => m === "config.set" && p.patch?.temperature === 0.3));
});

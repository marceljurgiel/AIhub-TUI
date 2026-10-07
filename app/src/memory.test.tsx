import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { AppTree, MockBridge } from "./test-tree.tsx";
import type { BridgeClient } from "./bridge/client.ts";

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

const STORED = "## Name\nAlex\n\n## Language\nPolish";

class MemoryBridge extends MockBridge {
  content = STORED;
  saves: string[] = [];
  clears = 0;
  override async request(method: string, params: any = {}): Promise<any> {
    switch (method) {
      case "memory.load":
        return { content: this.content };
      case "memory.save":
        this.saves.push(params.content);
        this.content = params.content;
        return { ok: true };
      case "memory.clear":
        this.clears++;
        this.content = "";
        return { cleared: true };
      default:
        return super.request(method);
    }
  }
}

async function openMemory() {
  const bridge = new MemoryBridge();
  setup = await testRender(<AppTree client={bridge as unknown as BridgeClient} />, { width: 110, height: 32 });
  await until((f) => f.includes("llama3.2:3b"));
  setup.mockInput.pressKey("e", { ctrl: true });
  await until((f) => f.includes("## Language"));   // loaded (not the placeholder)
  return { t: setup, bridge };
}

test("the stored memory is shown in the editor", async () => {
  const frame = (await openMemory()).t.captureCharFrame();
  expect(frame).toContain("## Name");
  expect(frame).toContain("Alex");
  expect(frame).toContain("## Language");
});

test("edits are what gets saved (not the text as loaded)", async () => {
  const { t, bridge } = await openMemory();
  t.mockInput.pressKey("END", { ctrl: true });     // to the end of the buffer
  await t.mockInput.typeText("\n\n## Editor\nNeovim");
  await until((f) => f.includes("unsaved"));
  t.mockInput.pressKey("s", { ctrl: true });
  await until((f) => f.includes("Memory saved."));
  expect(bridge.saves).toHaveLength(1);
  expect(bridge.saves[0]).toContain("## Name\nAlex");
  expect(bridge.saves[0]).toContain("## Editor\nNeovim");
});

test("typing s and x is just text — it doesn't save or wipe memory", async () => {
  const { t, bridge } = await openMemory();
  await t.mockInput.typeText("xx ss xx");
  await until((f) => f.includes("xx ss xx"));
  expect(bridge.saves).toEqual([]);
  expect(bridge.clears).toBe(0);
});

test("^X needs a second press to wipe", async () => {
  const { t, bridge } = await openMemory();
  t.mockInput.pressKey("x", { ctrl: true });
  await until((f) => f.includes("Press ^X again"));
  expect(bridge.clears).toBe(0);
  t.mockInput.pressKey("x", { ctrl: true });
  await until((f) => f.includes("Memory cleared."));
  expect(bridge.clears).toBe(1);
});

test("Esc with unsaved edits warns first, then discards", async () => {
  const { t, bridge } = await openMemory();
  await t.mockInput.typeText("draft");
  await until((f) => f.includes("unsaved"));
  t.mockInput.pressEscape();
  await until((f) => f.includes("Unsaved changes"));
  t.mockInput.pressEscape();
  await until((f) => !f.includes("◆ Memory"));
  expect(bridge.saves).toEqual([]);
});

test("reopening shows what was learned meanwhile", async () => {
  const { t, bridge } = await openMemory();
  t.mockInput.pressEscape();
  await until((f) => !f.includes("## Language"));
  bridge.content = STORED + "\n\n## Programming languages\nRust";   // learned in the background
  t.mockInput.pressKey("e", { ctrl: true });
  const f = await until((x) => x.includes("## Name"));
  await new Promise((r) => setTimeout(r, 300));
  await t.flush();
  expect(t.captureCharFrame()).toContain("Rust");
});

test("a tall terminal shows long memory without scrolling", async () => {
  const bridge = new MemoryBridge();
  bridge.content = Array.from({ length: 10 }, (_, i) => `## Topic ${i + 1}\nFact ${i + 1}`).join("\n\n");
  setup = await testRender(<AppTree client={bridge as unknown as BridgeClient} />, { width: 120, height: 44 });
  await until((f) => f.includes("llama3.2:3b"));
  setup.mockInput.pressKey("e", { ctrl: true });
  await until((f) => f.includes("## Topic 1"));
  expect(await until((f) => f.includes("Fact 10"))).toContain("## Topic 10");
});

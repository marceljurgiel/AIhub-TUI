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
    await new Promise((r) => setTimeout(r, 50));
    await setup!.flush();
    const f = setup!.captureCharFrame();
    if (pred(f)) return f;
  }
  throw new Error("frame never matched:\n" + setup!.captureCharFrame());
}

/** MockBridge whose chosen methods fail or return custom data. */
class FailingBridge extends MockBridge {
  constructor(private overrides: Record<string, () => Promise<any>>) {
    super();
  }
  override async request(method: string): Promise<any> {
    const o = this.overrides[method];
    return o ? o() : super.request(method);
  }
}

async function boot(overrides: Record<string, () => Promise<any>>, waitFor = "llama3.2:3b") {
  setup = await testRender(<AppTree client={new FailingBridge(overrides) as unknown as BridgeClient} />, {
    width: 110,
    height: 34,
  });
  await until((f) => f.includes(waitFor));
  return setup;
}

test("a failed user action is reported instead of silently doing nothing", async () => {
  const t = await boot({ "memory.save_entry": () => Promise.reject(new Error("disk full")) });
  await t.mockInput.typeText("/memory save editor vim");
  t.mockInput.pressEnter();
  const frame = await until((f) => f.includes("disk full"));
  expect(frame).toContain("Saving to memory failed: disk full");
});

test("a failed save is reported, not shown as 'Nothing to save.'", async () => {
  const t = await boot({ "chat.finalize": () => Promise.reject(new Error("could not save the session")) });
  t.mockInput.pressKey("s", { ctrl: true });
  const frame = await until((f) => f.includes("could not save"));
  expect(frame).toContain("Saving the session failed");
  expect(frame).not.toContain("Nothing to save.");
});

test("startup failure is shown", async () => {
  await boot({ "config.get": () => Promise.reject(new Error("engine exploded")) }, "Welcome");
  const frame = await until((f) => f.includes("engine exploded"));
  expect(frame).toContain("Starting up failed: engine exploded");
});

test("offline Ollama is not reported as 'no installed models'", async () => {
  await boot(
    {
      "backend.status": async () => ({ ollama_online: false, llamacpp_online: false, llamacpp_model: "" }),
      "models.installed": async () => ({ models: [], recent: [] }),
    },
    "Welcome",
  );
  const frame = await until((f) => f.includes("Ollama isn't running"));
  expect(frame).not.toContain("No installed models yet");
});

test("no models with Ollama up says so", async () => {
  await boot({ "models.installed": async () => ({ models: [], recent: [] }) }, "Welcome");
  await until((f) => f.includes("No installed models yet"));
});

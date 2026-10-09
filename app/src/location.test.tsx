/** The header's device readout: where the chat's model runs, as the Ollama
 *  machine reports it (models.location) — also when Ollama is on a server. */
import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { AppTree, MockBridge } from "./test-tree.tsx";
import type { BridgeClient } from "./bridge/client.ts";

let setup: Awaited<ReturnType<typeof testRender>> | undefined;
afterEach(() => {
  setup?.renderer.destroy();
  setup = undefined;
});

async function until(pred: (f: string) => boolean, tries = 80) {
  for (let i = 0; i < tries; i++) {
    await new Promise((r) => setTimeout(r, 40));
    await setup!.flush();
    const f = setup!.captureCharFrame();
    if (pred(f)) return f;
  }
  throw new Error("frame never matched:\n" + setup!.captureCharFrame());
}

class LocationBridge extends MockBridge {
  calls: Array<[string, any]> = [];
  location: any = { state: "gpu", gpu_fraction: 1, vram_gb: 5.2, size_gb: 5.2 };
  gate: Promise<void> | null = null;
  override async request(method: string, params: any = {}): Promise<any> {
    this.calls.push([method, params]);
    if (method === "models.location") {
      if (this.gate) await this.gate;
      return this.location;
    }
    return super.request(method);
  }
  located() {
    return this.calls.filter(([m]) => m === "models.location");
  }
}

async function start(bridge: LocationBridge) {
  setup = await testRender(<AppTree client={bridge as unknown as BridgeClient} />, { width: 110, height: 34 });
  await until((f) => f.includes("llama3.2:3b") && f.includes("New Chat"));
}
const header = () => setup!.captureCharFrame().split("\n")[0]!;

test("a model on the GPU: the header says so, with its VRAM, read from the Ollama machine", async () => {
  const bridge = new LocationBridge();
  await start(bridge);
  await until(() => header().includes("GPU 100% 5.2G"));
  expect(header()).not.toContain("CPU");
  expect(bridge.located()[0]![1]).toEqual({ model: "llama3.2:3b" });
});

for (const [location, shown] of [
  [{ state: "split", gpu_fraction: 0.62, vram_gb: 6.2, size_gb: 10 }, "GPU 62% · CPU 38%"],
  [{ state: "cpu", gpu_fraction: 0, vram_gb: 0, size_gb: 2 }, "·  CPU"],
  [{ state: "unloaded" }, "not loaded"],
  [{ state: "cloud" }, "·  cloud"],
] as const) {
  test(`state ${location.state}: "${shown}"`, async () => {
    const bridge = new LocationBridge();
    bridge.location = location;
    await start(bridge);
    await until(() => header().trimEnd().endsWith(shown));
  });
}

test("nothing is claimed before Ollama answers, nor when it is offline", async () => {
  const bridge = new LocationBridge();
  let release = () => {};
  bridge.gate = new Promise<void>((r) => (release = r));
  bridge.location = { state: "offline" };
  await start(bridge);
  await until(() => bridge.located().length > 0);
  for (const h of [header()]) expect(h).not.toMatch(/CPU|GPU|not loaded/);
  release();
  await new Promise((r) => setTimeout(r, 200));
  await setup!.flush();
  expect(header()).not.toMatch(/CPU|GPU|not loaded/);
  expect(header().trimEnd()).toMatch(/ctx 0\/4\.1k$/);
});

test("asked again right after a reply — the first message is what loads the model", async () => {
  const bridge = new LocationBridge();
  bridge.location = { state: "unloaded" };
  bridge.script = [
    { e: "text", d: { text: "The host is localhost." } },
    { e: "usage", d: { prompt_tokens: 10, completion_tokens: 3, tps: 30 } },
  ];
  await start(bridge);
  await until(() => header().includes("not loaded"));
  bridge.location = { state: "gpu", gpu_fraction: 1, vram_gb: 2.1, size_gb: 2.1 };
  await setup!.mockInput.typeText("hello");
  setup!.mockInput.pressEnter();
  await until(() => header().includes("2 messages"));               // the reply is in
  await until(() => header().includes("GPU 100% 2.1G"), 25);         // well before the 10 s poll
});

test("a long chat title gives way: the location stays whole in the header", async () => {
  const bridge = new LocationBridge();
  bridge.location = { state: "gpu", gpu_fraction: 1, vram_gb: 2.1, size_gb: 2.1 };
  bridge.script = [
    { e: "text", d: { text: "Yes." } },
    { e: "usage", d: { prompt_tokens: 1100, completion_tokens: 3, tps: 15.1 } },
  ];
  setup = await testRender(<AppTree client={bridge as unknown as BridgeClient} />, { width: 110, height: 34 });
  await until((f) => f.includes("llama3.2:3b") && f.includes("New Chat"));
  await setup!.mockInput.typeText("A customer wants to send back a faulty kettle after three weeks. Who pays?");
  setup!.mockInput.pressEnter();
  await until(() => header().includes("2 messages"));
  const h = await until(() => header().includes("tok/s")).then(() => header());
  expect(h.trimEnd()).toMatch(/GPU 100% 2\.1G$/);
  expect(h).toContain("A customer wants");
});

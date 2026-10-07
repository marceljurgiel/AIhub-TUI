import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { BridgeClient } from "./bridge/client.ts";
import { AppTree } from "./test-tree.tsx";

let setup: Awaited<ReturnType<typeof testRender>> | undefined;
let client: BridgeClient | undefined;
afterEach(() => { setup?.renderer.destroy(); client?.destroy(); setup = undefined; client = undefined; });

async function until(t: any, pred: (f: string) => boolean, tries = 60): Promise<string | null> {
  for (let i = 0; i < tries; i++) {
    await new Promise((r) => setTimeout(r, 250));
    await t.flush();
    const f = t.captureCharFrame();
    if (pred(f)) return f;
  }
  return null;
}

/** Type, let React flush the keystroke state, then submit — mirrors a human. */
async function typeAndEnter(t: any, text: string) {
  await t.mockInput.typeText(text);
  await new Promise((r) => setTimeout(r, 100));
  await t.flush();
  t.mockInput.pressEnter();
}

async function boot() {
  client = new BridgeClient();
  client.start();
  await client.ready();
  setup = await testRender(<AppTree client={client} />, { width: 110, height: 36 });
  await until(setup, (x) => x.includes("CONNECTED") && !x.includes("choose a model"))   // connected, model picked;
}

test("ollama library search", async () => {
  await boot();
  setup!.mockInput.pressKey("o", { ctrl: true });
  await until(setup!, (f) => f.includes("Models"));
  setup!.mockInput.pressKey("3");
  // the ollama placeholder only renders on that tab — proves the switch landed
  await until(setup!, (f) => f.includes("search the Ollama library"));
  setup!.mockInput.pressKey("/");
  await new Promise((r) => setTimeout(r, 100));
  await typeAndEnter(setup!, "qwen");
  const f = await until(setup!, (x) => /qwen3[.\d]*:\S+.*t\/s/.test(x), 40);
  console.log("OLLAMA>>>\n" + (f ?? "TIMEOUT") + "\n<<<");
  expect(f).not.toBeNull();
}, 120_000);

test("fit tab scores", async () => {
  await boot();
  setup!.mockInput.pressKey("o", { ctrl: true });
  await until(setup!, (f) => f.includes("Models"));
  setup!.mockInput.pressKey("2");
  const f = await until(setup!, (x) => x.includes("fit for") && x.includes("█"), 80);
  console.log("FIT>>>\n" + (f ?? "TIMEOUT") + "\n<<<");
  expect(f).not.toBeNull();
}, 150_000);

test("hf search", async () => {
  await boot();
  setup!.mockInput.pressKey("o", { ctrl: true });
  await until(setup!, (f) => f.includes("Models"));
  setup!.mockInput.pressKey("4");
  await until(setup!, (f) => f.includes("search HuggingFace"));
  setup!.mockInput.pressKey("/");
  await new Promise((r) => setTimeout(r, 100));
  await typeAndEnter(setup!, "qwen3");
  const f = await until(setup!, (x) => x.includes("HF Hub GGUF"), 40);
  console.log("HF>>>\n" + (f ?? "TIMEOUT") + "\n<<<");
  expect(f).not.toBeNull();
}, 120_000);

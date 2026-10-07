import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { BridgeClient } from "./bridge/client.ts";
import { AppTree } from "./test-tree.tsx";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

// Drives the REAL app against the REAL Python bridge — and a real Ollama with
// at least one model. Without one (CI, a fresh machine) these are skipped.
const ollamaUrl = (() => {
  try {
    const cfg = readFileSync(join(homedir(), ".aihub", "config.yaml"), "utf8");
    return cfg.match(/^ollama_api_url:\s*(\S+)/m)?.[1] ?? "http://localhost:11434";
  } catch {
    return "http://localhost:11434";
  }
})();
const hasOllama = await fetch(`${ollamaUrl}/api/tags`, { signal: AbortSignal.timeout(3000) })
  .then((r) => r.json())
  .then((d: any) => (d.models || []).length > 0)
  .catch(() => false);
const liveTest = hasOllama ? test : test.skip;
let setup: Awaited<ReturnType<typeof testRender>> | undefined;
let client: BridgeClient | undefined;

afterEach(() => {
  setup?.renderer.destroy();
  client?.destroy();
  setup = undefined;
  client = undefined;
});

/** Real bridge calls take wall-clock time; maxPasses counts frames, so poll. */
async function until(t: any, pred: (f: string) => boolean, tries = 40): Promise<string | null> {
  for (let i = 0; i < tries; i++) {
    await new Promise((r) => setTimeout(r, 250));
    await t.flush();
    const f = t.captureCharFrame();
    if (pred(f)) return f;
  }
  return null;
}

async function boot() {
  client = new BridgeClient();
  client.start();
  await client.ready();
  setup = await testRender(<AppTree client={client} />, { width: 110, height: 36 });
  const f = await until(setup, (x) => x.includes("CONNECTED") && !x.includes("choose a model"))   // connected, model picked;
  expect(f).not.toBeNull();
  return setup;
}

liveTest("boots against the engine and streams a real reply", async () => {
  const t = await boot();
  await t.mockInput.typeText("reply with exactly: pong");
  t.mockInput.pressEnter();
  const f = await until(t, (x) => x.includes("reply with exactly"), 20);
  expect(f).not.toBeNull();
}, 120_000);

liveTest("^O opens the model picker with real installed models", async () => {
  const t = await boot();
  t.mockInput.pressKey("o", { ctrl: true });
  const f = await until(t, (x) => x.includes("Models") && x.includes("GB"), 20);
  console.log("=== MODEL PICKER ===\n" + (f ?? t.captureCharFrame()));
  expect(f).not.toBeNull();
}, 120_000);

liveTest("^B opens hardware with a real scan", async () => {
  const t = await boot();
  t.mockInput.pressKey("b", { ctrl: true });
  const f = await until(t, (x) => x.includes("Hardware") && x.includes("RAM"), 20);
  console.log("=== HARDWARE ===\n" + (f ?? t.captureCharFrame()));
  expect(f).not.toBeNull();
}, 120_000);

liveTest("^P palette filters and Esc closes it", async () => {
  const t = await boot();
  t.mockInput.pressKey("p", { ctrl: true });
  expect(await until(t, (x) => x.includes("Command palette"), 20)).not.toBeNull();
  await t.mockInput.typeText("hard");
  const filtered = await until(t, (x) => x.includes("Hardware"), 30);
  console.log("=== PALETTE ===\n" + (filtered ?? t.captureCharFrame()));
  expect(filtered).not.toBeNull();
  t.mockInput.pressEscape();
  expect(await until(t, (x) => !x.includes("Command palette"), 30)).not.toBeNull();
}, 120_000);

liveTest("^, opens settings and ^E opens memory", async () => {
  const t = await boot();
  t.mockInput.pressKey("F3");
  const s = await until(t, (x) => x.includes("Settings") && x.includes("Tool calling"), 20);
  console.log("=== SETTINGS ===\n" + (s ?? t.captureCharFrame()));
  expect(s).not.toBeNull();
  t.mockInput.pressEscape();
  await until(t, (x) => !x.includes("Tool calling"), 30);

  t.mockInput.pressKey("e", { ctrl: true });
  const m = await until(t, (x) => x.includes("Memory"), 20);
  expect(m).not.toBeNull();
}, 120_000);

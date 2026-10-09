/** Context window by hand, per model: Settings → c. */
import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { AppTree, MockBridge } from "./test-tree.tsx";
import type { BridgeClient } from "./bridge/client.ts";
import { parseContext } from "./modals/SettingsModal.tsx";

let setup: Awaited<ReturnType<typeof testRender>> | undefined;
afterEach(() => {
  setup?.renderer.destroy();
  setup = undefined;
});

async function until(pred: (f: string) => boolean, tries = 60) {
  for (let i = 0; i < tries; i++) {
    await new Promise((r) => setTimeout(r, 40));
    await setup!.flush();
    const f = setup!.captureCharFrame();
    if (pred(f)) return f;
  }
  throw new Error("frame never matched:\n" + setup!.captureCharFrame());
}
const settle = async () => {
  for (let i = 0; i < 4; i++) {
    await new Promise((r) => setTimeout(r, 30));
    await setup!.flush();
  }
};
const pause = (ms = 250) => new Promise((r) => setTimeout(r, ms));

class ContextBridge extends MockBridge {
  calls: Array<[string, any]> = [];
  manual = 0;
  fits = 16384;
  setError = "";
  override async request(method: string, params: any = {}): Promise<any> {
    this.calls.push([method, params]);
    switch (method) {
      case "hardware.recommend_context":
        return { context: this.manual || this.fits, manual: this.manual, fits: this.fits };
      case "context.set":
        if (this.setError) throw new Error(this.setError);
        this.manual = params.context;
        return { model: params.model, manual: params.context, note: "" };
      case "config.get":
        return { ...(await super.request(method)), default_context_length: 4096 };
      default:
        return super.request(method);
    }
  }
  sets() {
    return this.calls.filter(([m]) => m === "context.set").map(([, p]) => p);
  }
}

async function boot(bridge = new ContextBridge()) {
  setup = await testRender(<AppTree client={bridge as unknown as BridgeClient} />, { width: 110, height: 34 });
  await until((f) => f.includes("llama3.2:3b") && f.includes("tab menu"));
  return bridge;
}

async function openContext() {
  setup!.mockInput.pressKey("F3");
  await until((f) => /Context\s+llama3\.2:3b · auto 16K/.test(f));
  setup!.mockInput.pressKey("c");
  // The rows draw at once; "fits" only once the hardware answer is in.
  await until((f) => f.includes("Context — llama3.2:3b") && f.includes("131,072") && f.includes("fits"));
}

test("context sizes can be typed as 24k, 24K, 1.5k or a plain number", () => {
  expect(parseContext("24k")).toBe(24576);
  expect(parseContext(" 32K ")).toBe(32768);
  expect(parseContext("1.5k")).toBe(1536);
  expect(parseContext("16384")).toBe(16384);
  expect(parseContext("16,384")).toBe(16384);
  expect(parseContext("lots")).toBeNull();
  expect(parseContext("")).toBeNull();
});

test("Settings shows the model's context; the Default context field is gone", async () => {
  await boot();
  setup!.mockInput.pressKey("F3");
  const f = await until((x) => /Context\s+llama3\.2:3b · auto 16K/.test(x));
  expect(f).not.toContain("Default context");
});

test("c: sizes above what fits are offered and marked; Enter saves for this model", async () => {
  const bridge = await boot();
  await openContext();
  const f = setup!.captureCharFrame();
  expect(f).toMatch(/16,384\s+.*fits/);
  expect(f).toMatch(/65,536\s+.*more than fits/);
  setup!.mockInput.pressArrow("down");                       // 16K → 32K
  await settle();
  setup!.mockInput.pressEnter();
  await until((x) => /Context\s+llama3\.2:3b · manual 32K/.test(x));
  expect(bridge.sets()).toEqual([{ model: "llama3.2:3b", context: 32768 }]);
  setup!.mockInput.pressEscape();
  await until((x) => x.includes("32K CTX"));
});

test("custom: any number, typed as 24k", async () => {
  const bridge = await boot();
  await openContext();
  for (let i = 0; i < 6; i++) {
    setup!.mockInput.pressArrow("down");
    await settle();
  }
  setup!.mockInput.pressEnter();                             // the "custom…" row
  await until((x) => x.includes("Tokens, e.g. 24k"));
  await settle();
  await setup!.mockInput.typeText("24k");
  await pause();
  setup!.mockInput.pressEnter();
  await until((x) => /manual 24K/.test(x));
  expect(bridge.sets()).toEqual([{ model: "llama3.2:3b", context: 24576 }]);
});

test("a: back to automatic", async () => {
  const bridge = new ContextBridge();
  bridge.manual = 32768;
  await boot(bridge);
  setup!.mockInput.pressKey("F3");
  await until((x) => /Context\s+llama3\.2:3b · manual 32K/.test(x));
  setup!.mockInput.pressKey("c");
  await until((x) => x.includes("manual: 32,768 tokens"));
  setup!.mockInput.pressKey("a");
  await until((x) => /Context\s+llama3\.2:3b · auto 16K/.test(x));
  expect(bridge.sets()).toEqual([{ model: "llama3.2:3b", context: 0 }]);
});

test("a refused size says why and keeps the window open", async () => {
  const bridge = await boot();
  bridge.setError = "context must be a number of tokens from 512 to 1,048,576";
  await openContext();
  setup!.mockInput.pressEnter();
  await until((x) => x.includes("context must be a number of tokens from 512"));
  expect(setup!.captureCharFrame()).toContain("Context — llama3.2:3b");
});

test("a model with a manual context says so when it loads", async () => {
  const bridge = new ContextBridge();
  bridge.manual = 24576;
  await boot(bridge);
  await until((x) => x.includes("Context 24K (manual) — Settings → c to change.") && x.includes("24K CTX"));
});

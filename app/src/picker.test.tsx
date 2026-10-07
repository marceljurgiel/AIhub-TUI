import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { AppTree, MockBridge } from "./test-tree.tsx";
import type { BridgeClient } from "./bridge/client.ts";
import { catalogCells, tpsLabel, humanAge, targetHeader } from "./modals/ModelPickerModal.tsx";

let setup: Awaited<ReturnType<typeof testRender>> | undefined;
afterEach(() => {
  setup?.renderer.destroy();
  setup = undefined;
});

async function until(pred: (f: string) => boolean, tries = 60) {
  for (let i = 0; i < tries; i++) {
    await new Promise((r) => setTimeout(r, 50));
    await setup!.flush();
    const f = setup!.captureCharFrame();
    if (pred(f)) return f;
  }
  throw new Error("frame never matched:\n" + setup!.captureCharFrame());
}

const TARGET = {
  where: "server", label: "server 192.0.2.10", vram_gb: 8, vram_basis: "learned",
  ram_gb: 0, bw_eff: 37.4, bw_basis: "measured", shared_memory: true,
};
const fitOf = (size: number, extra: any = {}) => ({
  fits: true, placement: "gpu", est_tps: 37.4 / size, need_gb: size + 0.6,
  basis: "estimated", score: 80, ...extra,
});
const FIT_MODELS = [
  { name: "qwen3.5:4b", size_gb: 3.4, capabilities: ["tools", "thinking"], updated: "2 weeks ago", fit: fitOf(3.4, { score: 91 }) },
  { name: "qwen3:8b", size_gb: 5.2, capabilities: ["tools"], updated: "6 months ago", fit: fitOf(5.2, { basis: "measured", est_tps: 7.2, score: 74 }) },
  { name: "a-model-with-a-really-long-name-that-must-be-cut:latest", size_gb: 1, capabilities: [], fit: fitOf(1, { score: 40 }) },
  { name: "llama3.3:70b", size_gb: 43, capabilities: ["tools"], fit: { fits: false, placement: "none", est_tps: 0, basis: "estimated", score: 0 } },
];

class PickerBridge extends MockBridge {
  calls: Array<[string, any]> = [];
  override async request(method: string, params: any = {}): Promise<any> {
    this.calls.push([method, params]);
    switch (method) {
      case "models.recommend":
        return { target: TARGET, catalog_age_s: 120, models: FIT_MODELS };
      case "ollama.library":
        return {
          target: TARGET, catalog_age_s: 30,
          models: [
            { name: "gemma4", description: "Google Gemma 4", capabilities: ["vision", "tools"], updated: "1 week ago",
              best: { name: "gemma4:e4b", size_gb: 9.6, fit: fitOf(9.6, { placement: "partial", score: 55 }) } },
            { name: "granite4.1", description: "IBM Granite", capabilities: ["tools"], updated: "3 days ago",
              best: { name: "granite4.1:8b", size_gb: 5.1, fit: fitOf(5.1) } },
          ],
        };
      case "cloud.models":
        return { models: [
          { name: "gpt-oss:20b-cloud", family: "gpt-oss", description: "OpenAI open-weight", status: "free" },
          { name: "kimi-k2.6:cloud", family: "kimi-k2.6", description: "Moonshot", status: "" },
          { name: "glm-4.7:cloud", family: "glm-4.7", description: "", status: "retired", installed: true },
        ] };
      case "cloud.probe":
        return { results: params.names.map((n: string) => ({ name: n, status: "paid" })) };
      case "hf.gguf":
        return {
          target: TARGET, catalog_age_s: 30,
          models: [{ name: "unsloth/Qwen3-8B-GGUF", size_gb: 4.8, description: "unsloth · 1,234 downloads/mo", fit: fitOf(4.8) }],
        };
      default:
        return super.request(method);
    }
  }
}

async function openPicker(size: { width: number; height: number }) {
  const bridge = new PickerBridge();
  setup = await testRender(<AppTree client={bridge as unknown as BridgeClient} />, size);
  await until((f) => f.includes("llama3.2:3b"));
  setup.mockInput.pressKey("o", { ctrl: true });
  await until((f) => f.includes("Installed"));
  return bridge;
}

const rowsOf = (frame: string, names: string[]) =>
  frame.split("\n").filter((l) => names.some((n) => l.includes(n)));

for (const size of [{ width: 80, height: 24 }, { width: 110, height: 34 }]) {
  test(`fit tab: aligned columns, header inside the modal (${size.width}×${size.height})`, async () => {
    await openPicker(size);
    setup!.mockInput.pressKey("2");
    const f = await until((x) => x.includes("qwen3.5:4b") && x.includes("fit for"));
    expect(f).toContain("server 192.0.2.10");
    expect(f).toContain("catalog 2 min ago");
    const lines = rowsOf(f, ["qwen3.5:4b", "qwen3:8b", "a-model-with", "llama3.3:70b"]);
    expect(lines.length).toBe(4);
    // Speed / placement / score columns line up on every row.
    const col = (s: string) => lines.map((l) => l.indexOf(s));
    expect(new Set(lines.map((l) => l.search(/[█░]/))).size).toBe(1);
    expect(lines[0]).toContain("~11 t/s");
    expect(lines[1]).toContain("7.2 t/s✓");        // measured on this server
    expect(lines[3]).toContain("—");
    expect(new Set(col("GPU").slice(0, 3)).size).toBe(1);
    // The hint bar is still the last line of the modal, not overwritten.
    const all = f.split("\n");
    const hints = all.findIndex((l) => l.includes("select") && l.includes("tab"));
    expect(hints).toBeGreaterThan(all.findIndex((l) => l.includes("llama3.3:70b")));
    expect(all.every((l) => l.length <= size.width)).toBe(true);
  });
}

test("ollama tab lists the cached catalog without a search", async () => {
  const bridge = await openPicker({ width: 110, height: 34 });
  setup!.mockInput.pressKey("3");
  const f = await until((x) => x.includes("granite4.1:8b"));
  expect(f).toContain("gemma4:e4b");
  expect(f).toContain("part");
  expect(f).toContain("catalog just now");
  expect(bridge.calls).toContainEqual(["ollama.library", { query: "", limit: 60 }]);
});

test("hf tab lists popular trusted models without a search", async () => {
  const bridge = await openPicker({ width: 110, height: 34 });
  setup!.mockInput.pressKey("4");
  const f = await until((x) => x.includes("unsloth/Qwen3-8B-GGUF"));
  expect(f).toContain("~7.8 t/s");
  expect(bridge.calls).toContainEqual(["hf.gguf", { query: "", limit: 40 }]);
});

test("cell helpers", () => {
  expect(tpsLabel({ fits: true, est_tps: 23.4, basis: "estimated" })).toBe("~23 t/s");
  expect(tpsLabel({ fits: false, est_tps: 5, basis: "estimated" })).toBe("—");
  expect(humanAge(null)).toBe("not downloaded yet");
  expect(humanAge(3 * 86400)).toBe("3 d ago");
  expect(targetHeader(TARGET)).toBe("fit for server 192.0.2.10 · GPU ~8 GB learned · 37 GB/s measured");
  expect(catalogCells({ kind: "ollama", name: "gemma4", best: { name: "gemma4:e4b", size_gb: 9.6, fit: fitOf(9.6) } }).name).toBe("gemma4:e4b");
});

test("cloud tab: Ollama Cloud models with plan status; free ones are used directly", async () => {
  const bridge = await openPicker({ width: 110, height: 34 });
  setup!.mockInput.pressKey("5");
  let f = await until((x) => x.includes("gpt-oss:20b-cloud") && x.includes("kimi-k2.6:cloud") && x.includes("paid"));
  expect(f).toMatch(/gpt-oss:20b-cloud\s+ollama\s+free/);
  expect(f).toMatch(/glm-4.7:cloud\s+ollama\s+retired/);
  expect(bridge.calls).toContainEqual(["cloud.probe", { names: ["kimi-k2.6:cloud"] }]);  // only the unknown one
  // paid → explained, not picked
  setup!.mockInput.pressArrow("down");
  await new Promise((r) => setTimeout(r, 60));
  setup!.mockInput.pressEnter();
  await until((x) => x.includes("isn't in Ollama's free cloud plan"));
  // free → picked through the Ollama backend, no download
  setup!.mockInput.pressArrow("up");
  await new Promise((r) => setTimeout(r, 60));
  setup!.mockInput.pressEnter();
  f = await until((x) => x.includes("Model → gpt-oss:20b-cloud"));
  expect(bridge.calls.some(([m]) => m === "models.pull")).toBe(false);
});

test("installed rows show size, params, context and what the model can do", async () => {
  const bridge = new PickerBridge();
  const orig = bridge.request.bind(bridge);
  bridge.request = async (m: string, p: any = {}) =>
    m === "models.installed"
      ? { models: [
          { name: "qwen3.5:9b", size_gb: 6.1, cloud: false, status: "", capabilities: ["vision", "tools", "thinking"], max_context: 262144, params: "9.7B", quant: "Q4_K_M" },
          { name: "deepseek-coder:6.7b", size_gb: 3.6, cloud: false, status: "", capabilities: [], max_context: 16384, params: "7B", quant: "Q4_0" },
          { name: "nemotron-3-ultra:cloud", size_gb: 0, cloud: true, status: "free", capabilities: ["thinking", "tools"], max_context: 262144, params: "550B", quant: "" },
        ], recent: [] }
      : orig(m, p);
  setup = await testRender(<AppTree client={bridge as unknown as BridgeClient} />, { width: 110, height: 34 });
  await until((f) => f.includes("llama3.2:3b") || f.includes("qwen3.5:9b"));
  setup.mockInput.pressKey("o", { ctrl: true });
  const f = await until((x) => x.includes("can do") && x.includes("nemotron-3-ultra:cloud"));
  expect(f).toMatch(/qwen3\.5:9b\s+6\.1 GB\s+9\.7B\s+256K\s+tools · thinking · vision/);
  expect(f).toMatch(/deepseek-coder:6\.7b\s+3\.6 GB\s+7B\s+16K\s+—/);
  expect(f).toMatch(/nemotron-3-ultra:cloud\s+cloud\s+550B\s+256K\s+free\s+tools · thinking/);
});

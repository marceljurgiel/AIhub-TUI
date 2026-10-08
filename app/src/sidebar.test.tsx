import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { AppTree, mockClient } from "./test-tree.tsx";

let setup: Awaited<ReturnType<typeof testRender>> | undefined;
afterEach(() => {
  setup?.renderer.destroy();
  setup = undefined;
});

const LABELS = ["New Chat", "Agent", "Schedule", "Skills", "Models", "History", "Memory", "Hardware", "Settings", "Theme", "Palette", "Help"];

async function frameAt(w: number, h: number) {
  setup = await testRender(<AppTree client={mockClient()} />, { width: w, height: h });
  return setup.waitForFrame((f) => f.includes("llama3.2:3b") && f.includes("New Chat"), { maxPasses: 40 });
}

/** The sidebar column (first 40 cells) of a frame. */
const sidebar = (f: string) => f.split("\n").map((l) => l.slice(0, 40));

test("tall terminal: figlet logo, grouped nav card with headers", async () => {
  const lines = sidebar(await frameAt(110, 34));
  const text = lines.join("\n");
  expect(text).toContain("|  .-.  ||  ||  .-.  ||  ||  || .-. '");
  for (const h of ["CHAT", "MODELS", "SYSTEM"]) expect(text).toContain(h);
  // Every item sits inside one rounded card, with its keycap.
  const top = lines.findIndex((l) => l.includes("CHAT")) - 1;
  const bottom = lines.findIndex((l, i) => i > top && l.includes("╰"));
  expect(lines[top]).toContain("╭");
  for (const label of LABELS) {
    const i = lines.findIndex((l) => l.includes(label));
    expect(i).toBeGreaterThan(top);
    expect(i).toBeLessThan(bottom);
  }
  expect(text).toMatch(/Skills\s+K/);
  expect(text).toContain("aihub v0.2.1");
});

for (const [w, h] of [[80, 24], [80, 18]] as const) {
  test(`short terminal ${w}x${h}: nothing in the nav is clipped`, async () => {
    const text = sidebar(await frameAt(w, h)).join("\n");
    for (const label of LABELS) expect(text).toContain(label);
    // A card is drawn whole or not at all — never with its bottom cut off.
    expect(text.split("╭").length).toBe(text.split("╰").length);
    expect(text).not.toContain("`--' `--'");          // no room for the figlet logo
    // Room for the boxed card at 24 rows; at 18 it shrinks to one line.
    expect(text).toContain(h >= 24 ? "CONNECTED" : "llama3.2:3b · 4K");
    expect(text).not.toContain("●");
  });
}

test("no status dots: the header and the model card say it in words", async () => {
  const f = await frameAt(110, 34);
  expect(f).not.toContain("●");
  expect(f).toMatch(/│ CONNECTED · 4K CTX/);
});

test("no row is highlighted when no panel is open", async () => {
  const lines = sidebar(await frameAt(110, 34));
  expect(lines.filter((l) => l.includes("▎"))).toEqual([]);
});

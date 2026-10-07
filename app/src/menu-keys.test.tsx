import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { AppTree, mockClient } from "./test-tree.tsx";

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
    await new Promise((r) => setTimeout(r, 25));
    await setup!.flush();
  }
};

async function boot() {
  setup = await testRender(<AppTree client={mockClient()} />, { width: 110, height: 34 });
  await until((f) => f.includes("llama3.2:3b") && f.includes("tab menu"));
}

const row = (f: string, label: string) => f.split("\n").find((l) => l.slice(0, 40).includes(label)) ?? "";

test("tab from an empty prompt focuses the menu; arrows + enter open a panel", async () => {
  await boot();
  setup!.mockInput.pressTab();
  let f = await until((x) => x.includes("esc back to typing"));
  expect(row(f, "New Chat")).toContain("▎");                    // cursor on the first row
  for (let i = 0; i < 4; i++) {      // Agent, Schedule, Skills, Models
    setup!.mockInput.pressArrow("down");
    await settle();
  }
  f = setup!.captureCharFrame();
  expect(row(f, "Models")).toContain("▎");
  expect(row(f, "New Chat")).not.toContain("▎");
  setup!.mockInput.pressEnter();
  await until((x) => x.includes("Installed") && x.includes("HF GGUF"));
});

test("letters jump straight to a panel while the menu has the keyboard", async () => {
  await boot();
  setup!.mockInput.pressTab();
  await until((x) => x.includes("esc back to typing"));
  setup!.mockInput.pressKey("h");
  await until((x) => x.includes("History —"));
});

test("esc goes back to typing; letters type again", async () => {
  await boot();
  setup!.mockInput.pressTab();
  await until((x) => x.includes("esc back to typing"));
  setup!.mockInput.pressEscape();
  await until((x) => x.includes("tab menu"));
  await setup!.mockInput.typeText("hello");
  const f = await until((x) => x.includes("hello"));
  expect(f).not.toContain("History —");
  expect(f.split("\n").filter((l) => l.slice(0, 40).includes("▎"))).toEqual([]);
});

test("tab with text in the prompt does not leave it", async () => {
  await boot();
  await setup!.mockInput.typeText("draft");
  await settle();
  setup!.mockInput.pressTab();
  await settle();
  expect(setup!.captureCharFrame()).toContain("tab menu");
  await setup!.mockInput.typeText(" more");
  await until((x) => x.includes("draft more"));
});

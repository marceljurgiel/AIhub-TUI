import { expect, test } from "bun:test";
import { CONSOLE_SAFE_MAP, consoleSafe } from "./glyphs.ts";

test("console-safe swaps keep one cell per cell, except spelled-out keys", () => {
  const words = new Set(["enter", "bksp", "^[", "^?"]);
  for (const [from, to] of Object.entries(CONSOLE_SAFE_MAP)) {
    expect([...from].length).toBe(1);
    if (!words.has(to)) expect([...to].length).toBe(1);
  }
});

test("swaps what Consolas lacks and leaves the rest", () => {
  expect(consoleSafe("↵ send · ✓ done ▎ ⠋")).toBe("enter send · √ done ▌ |");
  expect(consoleSafe("plain — text … ● ↑↓")).toBe("plain — text … ● ↑↓");
});

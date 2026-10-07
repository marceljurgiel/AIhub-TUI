/** Themes: palettes and accents apply live everywhere, Esc in the picker puts
 *  back what was there, Enter saves to the engine's config. */
import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { AppTree, MockBridge } from "./test-tree.tsx";
import type { BridgeClient } from "./bridge/client.ts";
import { ACCENTS, THEMES, activeTheme, applyTheme, logoGradient, theme } from "./theme.ts";

let setup: Awaited<ReturnType<typeof testRender>> | undefined;
afterEach(() => {
  setup?.renderer.destroy();
  setup = undefined;
  applyTheme("aihub", "");
});

async function until(pred: (f: string) => boolean, tries = 40, label = "") {
  for (let i = 0; i < tries; i++) {
    await new Promise((r) => setTimeout(r, 40));
    await setup!.flush();
    const f = setup!.captureCharFrame();
    if (pred(f)) return f;
  }
  throw new Error(`frame never matched (${label} theme=${activeTheme.name} accent=${activeTheme.accent}):\n` + setup!.captureCharFrame());
}

class ThemeBridge extends MockBridge {
  calls: Array<[string, any]> = [];
  saved = { theme: "aihub", accent: "" };
  override async request(method: string, params: any = {}): Promise<any> {
    this.calls.push([method, params]);
    if (method === "config.get") return { ...(await super.request(method)), ...this.saved };
    if (method === "config.set") {
      Object.assign(this.saved, params.patch);
      return { ...(await super.request("config.get")), ...this.saved };
    }
    return super.request(method);
  }
}

test("a theme and an accent replace the palette; unknown names fall back", () => {
  applyTheme("nord", "orange");
  expect(theme.bg0).toBe(THEMES.nord!.palette.bg0);
  expect(theme.accent).toBe(ACCENTS.orange!.accent);
  expect(logoGradient[2]).toBe(ACCENTS.orange!.accent);
  applyTheme("light", "");
  // On a light canvas the logo runs dark → accent, never towards white.
  expect(logoGradient[3]).toBe(THEMES.light!.palette.accent);
  applyTheme("no-such-theme", "no-such-accent");
  expect(activeTheme).toEqual({ name: "aihub", accent: "" });
  expect(theme.accent).toBe(THEMES.aihub!.palette.accent);
});

test("the saved theme is applied at startup", async () => {
  const bridge = new ThemeBridge();
  bridge.saved = { theme: "gruvbox", accent: "" };
  setup = await testRender(<AppTree client={bridge as unknown as BridgeClient} />, { width: 110, height: 34 });
  await until((f) => f.includes("llama3.2:3b"));
  expect(activeTheme.name).toBe("gruvbox");
});

test("F2 opens the picker: arrows preview live, Esc restores, Enter saves", async () => {
  const bridge = new ThemeBridge();
  setup = await testRender(<AppTree client={bridge as unknown as BridgeClient} />, { width: 110, height: 34 });
  await until((f) => f.includes("llama3.2:3b"));

  setup.mockInput.pressKey("F2");
  await until((f) => f.includes("Tokyo Night") && f.includes("accent"));
  setup.mockInput.pressArrow("down");
  await until(() => activeTheme.name === "tokyo-night", 40, "down");
  setup.mockInput.pressArrow("right");                       // first accent after "theme's own"
  await until(() => activeTheme.accent === "purple", 40, "right");
  expect(theme.bg0).toBe(THEMES["tokyo-night"]!.palette.bg0);
  setup.mockInput.pressEscape();
  await until(() => activeTheme.name === "aihub" && activeTheme.accent === "", 40, "esc");
  expect(bridge.calls.some(([m]) => m === "config.set")).toBe(false);

  setup.mockInput.pressKey("F2");
  await until((f) => f.includes("Tokyo Night"));
  setup.mockInput.pressArrow("down");
  setup.mockInput.pressArrow("down");
  await until(() => activeTheme.name === "catppuccin", 40, "down2");
  setup.mockInput.pressEnter();
  await until((f) => f.includes("Theme → Catppuccin"), 40, "saved");
  expect(bridge.calls).toContainEqual(["config.set", { patch: { theme: "catppuccin", accent: "" } }]);
});

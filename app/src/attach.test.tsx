import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { AppTree, MockBridge } from "./test-tree.tsx";
import type { BridgeClient } from "./bridge/client.ts";

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
const settle = async (n = 5) => {
  for (let i = 0; i < n; i++) {
    await new Promise((r) => setTimeout(r, 25));
    await setup!.flush();
  }
};

const SHOT = { id: "3f2a9c1b7e04.jpg", name: "clipboard.png", width: 800, height: 600, kb: 120 };

class AttachBridge extends MockBridge {
  calls: Array<[string, any]> = [];
  turns: any[] = [];
  vision = true;
  override async request(method: string, params: any = {}): Promise<any> {
    this.calls.push([method, params]);
    switch (method) {
      case "attach.clipboard":
        return { attachment: SHOT };
      case "attach.paste":
        return params.text.includes("missing")
          ? { attachments: [] }
          : { attachments: [{ id: "aaaaaaaaaaaa.png", name: "photo.png", width: 1568, height: 1045, kb: 310 }] };
      case "vision.check":
        return { vision: this.vision };
      default:
        return super.request(method);
    }
  }
  override stream(method: string, params: any) {
    this.turns.push(params);
    return { id: 1, done: Promise.resolve({ messages: [...params.messages, { role: "assistant", content: "A red box." }] }) } as any;
  }
}

async function boot(opts: { image?: boolean; vision?: boolean } = {}) {
  const bridge = new AttachBridge();
  bridge.vision = opts.vision ?? true;
  setup = await testRender(
    <AppTree client={bridge as unknown as BridgeClient} clipboardHasImage={async () => !!opts.image} />,
    { width: 110, height: 34 },
  );
  await until((f) => f.includes("llama3.2:3b") && f.includes("tab menu"));
  return bridge;
}

test("Ctrl+V with an image in the clipboard attaches it; send carries the id", async () => {
  const bridge = await boot({ image: true });
  setup!.mockInput.pressKey("v", { ctrl: true });
  await until((f) => f.includes("▣ clipboard.png · 800×600 · 120 KB"));
  await setup!.mockInput.typeText("what is this?");
  await settle();
  setup!.mockInput.pressEnter();
  const f = await until((x) => bridge.turns.length === 1 && x.includes("2 messages"));
  expect(bridge.turns[0].messages.at(-1)).toEqual({ role: "user", content: "what is this?", images: [SHOT.id] });
  expect(f).toContain("▣ clipboard.png");                 // in the log
  expect(f).not.toContain("⌫ removes the last");            // the pending chip is gone
});

test("a dropped image path attaches instead of pasting text", async () => {
  const bridge = await boot();
  await setup!.mockInput.pasteBracketedText("file:///home/me/Pictures/photo.png");
  await until((f) => f.includes("▣ photo.png · 1568×1045"));
  expect(bridge.calls).toContainEqual(["attach.paste", { text: "file:///home/me/Pictures/photo.png" }]);
  expect(setup!.captureCharFrame()).not.toContain("file:///home");
});

test("a path that isn't an image file is pasted as text", async () => {
  const bridge = await boot();
  await setup!.mockInput.pasteBracketedText("/home/me/missing.png");
  await until((f) => f.includes("/home/me/missing.png"));
  await setup!.mockInput.pasteBracketedText(" hello world");
  await until((f) => f.includes("hello world"));
  expect(bridge.calls.filter(([m]) => m === "attach.paste")).toHaveLength(1);
});

test("backspace in an empty prompt removes the last image; with text it edits text", async () => {
  await boot({ image: true });
  setup!.mockInput.pressKey("v", { ctrl: true });
  await until((f) => f.includes("▣ clipboard.png"));
  await setup!.mockInput.typeText("ab");
  await settle();
  setup!.mockInput.pressBackspace();
  await settle();
  expect(setup!.captureCharFrame()).toContain("▣ clipboard.png");     // removed "b", not the image
  setup!.mockInput.pressBackspace();
  await settle();
  setup!.mockInput.pressBackspace();
  await until((f) => !f.includes("▣ clipboard.png"));
});

test("an image alone can be sent", async () => {
  const bridge = await boot({ image: true });
  setup!.mockInput.pressKey("v", { ctrl: true });
  await until((f) => f.includes("▣ clipboard.png"));
  setup!.mockInput.pressEnter();
  await until((x) => bridge.turns.length === 1 && x.includes("2 messages"));
  expect(bridge.turns[0].messages.at(-1)).toEqual({ role: "user", content: "", images: [SHOT.id] });
});

test("a model that can't see images is flagged before sending", async () => {
  await boot({ image: true, vision: false });
  setup!.mockInput.pressKey("v", { ctrl: true });
  await until((f) => f.includes("llama3.2:3b can't see images"));
});

test("without an image in the clipboard, Ctrl+V pastes text", async () => {
  const bridge = new AttachBridge();
  setup = await testRender(
    <AppTree client={bridge as unknown as BridgeClient} readClipboard={async () => "plain text"} clipboardHasImage={async () => false} />,
    { width: 110, height: 34 },
  );
  await until((f) => f.includes("llama3.2:3b") && f.includes("tab menu"));
  setup!.mockInput.pressKey("v", { ctrl: true });
  await until((f) => f.includes("plain text"));
  expect(bridge.calls.some(([m]) => m === "attach.clipboard")).toBe(false);
});

test("a path that arrives typed (drag and drop without paste, SSH): Enter attaches it", async () => {
  const bridge = await boot();
  await setup!.mockInput.typeText("/home/me/Pictures/photo.png");
  await settle();
  setup!.mockInput.pressEnter();
  await until((f) => f.includes("▣ photo.png · 1568×1045"));
  expect(bridge.calls).toContainEqual(["attach.paste", { text: "/home/me/Pictures/photo.png" }]);
  expect(bridge.turns).toHaveLength(0);                       // nothing sent yet
  expect(setup!.captureCharFrame()).not.toContain("/home/me/Pictures");
});

test("a typed path that isn't an image file goes on as typed", async () => {
  const bridge = await boot();
  await setup!.mockInput.typeText("~/Pictures/missing.png");
  await settle();
  setup!.mockInput.pressEnter();
  await until(() => bridge.turns.length === 1);
  expect(bridge.calls).toContainEqual(["attach.paste", { text: "~/Pictures/missing.png" }]);
  expect(bridge.turns[0].messages.at(-1).content).toBe("~/Pictures/missing.png");
});

/** Knowledge bases in the app: the Knowledge window (F6), /kb in a chat, and
 *  attaching a base to an agent (Agents → k). */
import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { AppTree, MockBridge } from "./test-tree.tsx";
import type { BridgeClient } from "./bridge/client.ts";
import { splitPaths } from "./modals/KnowledgeModal.tsx";

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

const HOME = { name: "home", description: "House notes", model: "embeddinggemma", sources: ["/home/alex/docs"],
               files: 2, chunks: 5, bytes: 40960, updated: 1 };

class KbBridge extends MockBridge {
  calls: Array<[string, any]> = [];
  bases: any[] = [HOME];
  embedReady = true;
  agent = { name: "house", description: "House helper", prompt: "p", tools: ["read_file"], permission: "ask",
            model: "", context: 0, builtin: false, path: "/home/alex/.aihub/agents/house.md" };
  override async request(method: string, params: any = {}): Promise<any> {
    this.calls.push([method, params]);
    switch (method) {
      case "kb.list":
        return { bases: this.bases };
      case "kb.status":
        return { reachable: true, ready: this.embedReady, url: "http://gpu-box.lan:11434", model: "embeddinggemma" };
      case "kb.create": {
        const b = { ...HOME, name: params.name, description: params.description, files: 0, chunks: 0, sources: [] };
        this.bases = [...this.bases, b];
        return b;
      }
      case "kb.search":
        return { hits: [{ base: "home", source: "docs/boiler.md", page: null, title: "docs/boiler.md · Boiler",
                          text: "The boiler pressure should stay between 1.2 and 1.8 bar.", score: 0.82 }] };
      case "kb.delete":
        this.bases = this.bases.filter((b) => b.name !== params.name);
        return { deleted: true };
      case "agents.list":
        return { agents: [this.agent], dir: "/home/alex/.aihub/agents" };
      case "agents.save":
        this.agent = { ...params.agent };
        return { agent: this.agent };
      default:
        return super.request(method);
    }
  }
  override stream(method: string, params: any, handlers: any): { id: number; done: Promise<any> } {
    if (method === "kb.add") {
      this.calls.push([method, params]);
      const done: Promise<any> = (async () => {
        await new Promise((r) => setTimeout(r, 20));
        handlers.onEvent("scan", { files: 2 });
        handlers.onEvent("file", { i: 1, n: 2, path: "docs/manual.pdf", chunks: 4 });
        handlers.onEvent("embed", { path: "docs/manual.pdf", done: 4, total: 4 });
        handlers.onEvent("problem", { path: "docs/scan.pdf", error: "no text in this PDF (a scan? it needs OCR first)" });
        return { files: 1, changed: 2, chunks: 4, added: 4, removed: 0,
                 problems: [{ path: "docs/scan.pdf", error: "no text in this PDF (a scan? it needs OCR first)" }] };
      })();
      return { id: 5, done };
    }
    if (method === "kb.pull") {
      this.calls.push([method, params]);
      const done: Promise<any> = (async () => {
        handlers.onEvent("progress", { status: "pulling", completed: 300e6, total: 620e6 });
        await new Promise((r) => setTimeout(r, 30));
        this.embedReady = true;
        return { model: "embeddinggemma", ready: true };
      })();
      return { id: 6, done };
    }
    if (method === "chat.turn") this.calls.push([method, params]);
    return super.stream(method, params, handlers);
  }
}

async function open() {
  const bridge = new KbBridge();
  setup = await testRender(<AppTree client={bridge as unknown as BridgeClient} />, { width: 110, height: 36 });
  await until((f) => f.includes("llama3.2:3b") && f.includes("tab menu"));
  return bridge;
}

async function openKnowledge() {
  setup!.mockInput.pressKey("F6");
  await until((f) => f.includes("Knowledge") && f.includes("home") && f.includes("embeddings: embeddinggemma"));
}

test("paths can be typed, quoted, escaped or dropped as file:// links", () => {
  expect(splitPaths(`~/docs '/tmp/my notes' /tmp/a\\ b.pdf file:///home/alex/x%20y.docx`)).toEqual([
    "~/docs", "/tmp/my notes", "/tmp/a b.pdf", "/home/alex/x y.docx",
  ]);
  expect(splitPaths(`"C:\\Users\\alex\\Documents"`)).toEqual(["C:\\Users\\alex\\Documents"]);
});

test("F6: a new base, then files indexed with progress and problems shown", async () => {
  const bridge = await open();
  await openKnowledge();
  expect(setup!.captureCharFrame()).toMatch(/home\s+2 files\s+5 chunks\s+40 KB\s+House notes/);
  setup!.mockInput.pressKey("n");
  await until((f) => f.includes("Name (lowercase"));
  await setup!.mockInput.typeText("manuals");
  setup!.mockInput.pressEnter();
  await until((f) => f.includes("What's in manuals?"));
  await settle();
  await setup!.mockInput.typeText("Device manuals");
  await new Promise((r) => setTimeout(r, 250));
  setup!.mockInput.pressEnter();
  await until((f) => f.includes("Add to manuals"));
  expect(bridge.calls).toContainEqual(["kb.create", { name: "manuals", description: "Device manuals" }]);
  await setup!.mockInput.pasteBracketedText("'/home/alex/my docs'");
  await settle();
  await new Promise((r) => setTimeout(r, 250));
  setup!.mockInput.pressEnter();
  await until((f) => f.includes("✓ manuals: 1 files, 4 chunks"));
  expect(setup!.captureCharFrame()).toContain("docs/scan.pdf: no text in this PDF");
  expect(bridge.calls).toContainEqual(["kb.add", { name: "manuals", paths: ["/home/alex/my docs"] }]);
});

test("without the embedding model, the window offers the download and carries on", async () => {
  const bridge = await open();
  bridge.embedReady = false;
  setup!.mockInput.pressKey("F6");
  await until((f) => f.includes("isn't on http://gpu-box.lan:11434 yet — m downloads it"));
  setup!.mockInput.pressKey("a");                                   // add files → needs the model
  await until((f) => f.includes("needs the embedding model embeddinggemma"));
  setup!.mockInput.pressEnter();
  await until((f) => f.includes("Add to home"));                    // downloaded, then straight on
  expect(bridge.calls.some(([m]) => m === "kb.pull")).toBe(true);
});

test("/ searches a base and shows what the model would get", async () => {
  const bridge = await open();
  await openKnowledge();
  setup!.mockInput.pressKey("/");
  await until((f) => f.includes("Search home"));
  await setup!.mockInput.typeText("boiler pressure");
  await new Promise((r) => setTimeout(r, 250));
  setup!.mockInput.pressEnter();
  await until((f) => f.includes("[1] docs/boiler.md · Boiler") && f.includes("0.82"));
  expect(bridge.calls).toContainEqual(["kb.search", { name: "home", query: "boiler pressure", k: 5 }]);
});

test("d deletes a base after a confirmation", async () => {
  const bridge = await open();
  await openKnowledge();
  setup!.mockInput.pressKey("d");
  await until((f) => f.includes("Press d again to delete home"));
  setup!.mockInput.pressKey("d");
  await until((f) => f.includes("Deleted home") && f.includes("No knowledge bases yet"));
  expect(bridge.calls).toContainEqual(["kb.delete", { name: "home" }]);
});

test("/kb home switches the base on for this chat and sends it with each question", async () => {
  const bridge = await open();
  await settle();
  await setup!.mockInput.typeText("/kb home");
  setup!.mockInput.pressEnter();
  await until((f) => f.includes("Using home in this chat") && f.includes("¶ home"));
  await setup!.mockInput.typeText("what boiler pressure?");
  setup!.mockInput.pressEnter();
  await until(() => bridge.calls.some(([m]) => m === "chat.turn"));
  const turn = bridge.calls.find(([m]) => m === "chat.turn")![1];
  expect(turn.knowledge).toEqual(["home"]);
  await setup!.mockInput.typeText("/kb nope");
  setup!.mockInput.pressEnter();
  await until((f) => f.includes("No knowledge base called nope"));
  await setup!.mockInput.typeText("/kb off");
  setup!.mockInput.pressEnter();
  await until((f) => f.includes("Knowledge off for this chat"));
});

test("Agents → k attaches a base to the agent", async () => {
  const bridge = await open();
  setup!.mockInput.pressKey("g", { ctrl: true });
  await until((f) => f.includes("Agents") && f.includes("house"));
  setup!.mockInput.pressArrow("down");                              // past "plain chat"
  await until((f) => f.includes("no knowledge base — k adds one"));
  setup!.mockInput.pressKey("k");
  await until((f) => f.includes("What should house know?") && f.includes("[ ] home"));
  setup!.mockInput.pressKey("t");
  await until((f) => f.includes("[✓] home"));
  setup!.mockInput.pressEnter();
  await until((f) => f.includes("house now answers from home"));
  const saved = bridge.calls.find(([m]) => m === "agents.save")![1].agent;
  expect(saved.tools).toEqual(["read_file", "kb:home"]);
});

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
    await new Promise((r) => setTimeout(r, 50));
    await setup!.flush();
    const f = setup!.captureCharFrame();
    if (pred(f)) return f;
  }
  throw new Error("frame never matched:\n" + setup!.captureCharFrame());
}

async function settle(n = 4) {
  for (let i = 0; i < n; i++) {
    await new Promise((r) => setTimeout(r, 25));
    await setup!.flush();
  }
}

const AGENTS = [
  { name: "coder", description: "Writes and fixes code", prompt: "You code.", tools: ["read_file", "edit_file", "run_terminal"],
    permission: "auto", model: "", context: 0, builtin: true, path: "" },
  { name: "researcher", description: "Searches the web", prompt: "You research.", tools: ["read_file", "search_web"],
    permission: "ask", model: "qwen3:8b", context: 0, builtin: true, path: "" },
];

class AgentBridge extends MockBridge {
  calls: Array<[string, any]> = [];
  agents = [...AGENTS];
  override async request(method: string, params: any = {}): Promise<any> {
    this.calls.push([method, params]);
    switch (method) {
      case "agents.list":
        return { agents: this.agents, dir: "/home/me/.aihub/agents" };
      case "agent.check":
        return { ok: true, context: 14336, context_note: "most that fits in GPU 8 GB (learned)", max_context: 40960 };
      case "agents.draft":
        return { agent: { name: "homeserver-watch", description: "Watches the server", prompt: "You watch home server.\nNever reboot.",
                          tools: ["run_terminal", "read_file"], permission: "ask", model: "", context: 0, builtin: false, path: "" } };
      case "agents.save": {
        const a = { ...params.agent, path: `/home/me/.aihub/agents/${params.agent.name}.md` };
        this.agents.push(a);
        return { agent: a };
      }
      default:
        return super.request(method);
    }
  }
}

async function boot() {
  const bridge = new AgentBridge();
  setup = await testRender(<AppTree client={bridge as unknown as BridgeClient} />, { width: 110, height: 34 });
  await until((f) => f.includes("llama3.2:3b"));
  return bridge;
}

async function openAgents() {
  setup!.mockInput.pressKey("g", { ctrl: true });
  await until((f) => f.includes("Agents") && f.includes("researcher"));
}

test("^G lists chat + agents; picking one sets its context and status", async () => {
  const bridge = await boot();
  await openAgents();
  setup!.mockInput.pressArrow("down");
  await settle();
  setup!.mockInput.pressArrow("down");
  await settle();
  setup!.mockInput.pressEnter();
  const f = await until((x) => x.includes("Agent researcher · build"));
  expect(f).toContain("14k context");
  expect(f).toContain("asks before edits");
  expect(f).toContain("suggests qwen3:8b");
  expect(f).toContain("agent researcher · build");
  expect(bridge.calls).toContainEqual(["agent.check", { model: "llama3.2:3b", backend: "ollama", agent: "researcher" }]);
});

test("p starts an agent in plan mode; choosing chat goes back", async () => {
  await boot();
  await openAgents();
  setup!.mockInput.pressArrow("down");
  await settle();
  setup!.mockInput.pressKey("p");
  await until((x) => x.includes("agent coder · plan"));
  await openAgents();
  setup!.mockInput.pressArrow("up");          // row 0: chat
  await settle();
  setup!.mockInput.pressEnter();
  const f = await until((x) => x.includes("Back to plain chat."));
  expect(f).not.toContain("agent coder · plan");
});

test("n drafts a new agent from a description, review, save", async () => {
  const bridge = await boot();
  await openAgents();
  setup!.mockInput.pressKey("n");
  await until((x) => x.includes("Describe the agent"));
  await setup!.mockInput.typeText("pilnuj mojego serwera");
  await settle();
  setup!.mockInput.pressEnter();
  let f = await until((x) => x.includes("You watch home server."));
  expect(f).toContain("homeserver-watch");
  expect(f).toContain("shell");
  expect(f).toContain("asks first");
  setup!.mockInput.pressKey("a");               // toggle → auto
  await until((x) => x.includes("auto — runs without asking"));
  setup!.mockInput.pressEnter();
  f = await until((x) => x.includes("Saved /home/me/.aihub/agents/homeserver-watch.md"));
  expect(bridge.calls.filter(([m]) => m === "agents.draft")).toHaveLength(1);
  expect(bridge.calls.find(([m]) => m === "agents.save")![1].agent.permission).toBe("auto");
});

test("the chat turn carries the agent's name", async () => {
  const bridge = await boot();
  const turns: any[] = [];
  (bridge as any).stream = (method: string, params: any, handlers: any) => {
    turns.push(params);
    return { id: 1, done: Promise.resolve({ messages: params.messages }) };
  };
  await openAgents();
  setup!.mockInput.pressArrow("down");
  await settle();
  setup!.mockInput.pressArrow("down");
  await settle();
  setup!.mockInput.pressEnter();
  await until((x) => x.includes("agent researcher · build"));
  await setup!.mockInput.typeText("hello");
  setup!.mockInput.pressEnter();
  await settle(8);
  expect(turns[0]).toMatchObject({ agent: true, agent_name: "researcher", submode: "build", context_length: 14336 });
});

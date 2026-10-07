import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { AppTree, MockBridge } from "./test-tree.tsx";
import type { BridgeClient } from "./bridge/client.ts";
import { permissionDetail } from "./modals/PermissionModal.tsx";
import { mcpLabel } from "./widgets/ToolPanel.tsx";

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
  for (let i = 0; i < 5; i++) {
    await new Promise((r) => setTimeout(r, 25));
    await setup!.flush();
  }
};

const GMAIL = {
  name: "gmail", enabled: true, status: "connected", error: "", transport: "stdio",
  command: "/home/me/.aihub/mcp/venvs/workspace-mcp/bin/workspace-mcp --tools gmail --single-user",
  keywords: ["mail", "inbox"],
  tools: [
    { name: "search_gmail_messages", description: "Searches messages.", read_only: true, enabled: true },
    { name: "send_gmail_message", description: "Sends an email.", read_only: false, enabled: true },
    { name: "manage_gmail_filter", description: "Filters.", read_only: false, enabled: false },
  ],
};

class McpBridge extends MockBridge {
  calls: Array<[string, any]> = [];
  servers: any[] = [GMAIL, { ...GMAIL, name: "broken", status: "error", error: "command not found: npx", tools: [] }];
  override async request(method: string, params: any = {}): Promise<any> {
    this.calls.push([method, params]);
    switch (method) {
      case "mcp.list":
        return { servers: this.servers.map((s) => ({ ...s })), config: "/home/me/.aihub/mcp.json" };
      case "mcp.tool_enable":
      case "mcp.enable":
        return { ok: true };
      case "mcp.add":
        return { added: { everything: { ok: true, tools: 13 } } };
      case "mcp.catalog":
        return { items: [
          { id: "github", name: "GitHub", category: "code", description: "Repos, issues, PRs", installed: false, prefill: {},
            fields: [{ key: "token", label: "GitHub token", secret: true, placeholder: "ghp_…" }], steps: ["github.com/settings/tokens"] },
          { id: "gmail", name: "Gmail", category: "google", description: "Mail", installed: true,
            prefill: { client_id: "1-a.apps.googleusercontent.com", client_secret: "GOCSPX-x", email: "me@gmail.com" },
            fields: [{ key: "client_id", label: "Google OAuth Client ID", secret: false, placeholder: "" },
                     { key: "client_secret", label: "Client secret", secret: true, placeholder: "" },
                     { key: "email", label: "Your Google address", secret: false, placeholder: "" }], steps: ["enable the Gmail API"] },
          { id: "fetch", name: "Fetch (web pages)", category: "web", description: "Read a web page", installed: false, prefill: {},
            fields: [], steps: [] },
        ], claude: ["obsidian"] };
      case "mcp.install":
        return { ok: true, name: params.id, tools: params.id === "fetch" ? 1 : 26 };
      case "mcp.import_claude":
        return { added: ["obsidian"], skipped: [] };
      default:
        return super.request(method);
    }
  }
}

async function open() {
  const bridge = new McpBridge();
  setup = await testRender(<AppTree client={bridge as unknown as BridgeClient} />, { width: 110, height: 34 });
  await until((f) => f.includes("llama3.2:3b") && f.includes("tab menu"));
  setup.mockInput.pressKey("F5");
  await until((f) => f.includes("MCP — connected services") && f.includes("gmail"));
  return bridge;
}

test("F5 lists servers with status, tool counts and errors", async () => {
  const bridge = await open();
  const f = setup!.captureCharFrame();
  expect(f).toMatch(/● gmail\s+connected\s+2\/3 tools/);
  expect(f).toContain("offered when you mention: gmail, mail, inbox");
  setup!.mockInput.pressArrow("down");
  await until((x) => x.includes("command not found: npx"));
  expect(bridge.calls.some(([m, p]) => m === "mcp.list" && p.connect)).toBe(true);
});

test("enter shows tools (reads / changes); t switches one off", async () => {
  const bridge = await open();
  setup!.mockInput.pressEnter();
  const f = await until((x) => x.includes("send_gmail_message"));
  expect(f).toMatch(/search_gmail_messages\s+reads/);
  expect(f).toMatch(/send_gmail_message\s+changes/);
  setup!.mockInput.pressKey("t");
  await settle();
  expect(bridge.calls).toContainEqual(["mcp.tool_enable", { name: "gmail", tool: "search_gmail_messages", enabled: false }]);
});

async function openCatalog() {
  setup!.mockInput.pressKey("a");
  await until((x) => x.includes("Import from Claude") && x.includes("Custom server…"));
}

const down = async (n: number) => {
  for (let i = 0; i < n; i++) {
    setup!.mockInput.pressArrow("down");
    await settle();
  }
};

test("a opens the catalog; a server with nothing to fill installs on enter", async () => {
  const bridge = await open();
  await openCatalog();
  const f = setup!.captureCharFrame();
  expect(f).toMatch(/✓ Gmail/);                                          // installed marker
  await down(2);
  expect(setup!.captureCharFrame()).toContain("needs: nothing — enter installs it");
  setup!.mockInput.pressEnter();
  await until((x) => x.includes("Fetch (web pages) connected — 1 tools"));
  expect(bridge.calls).toContainEqual(["mcp.install", { id: "fetch", values: {} }]);
});

test("a server that needs a token asks for it with the steps", async () => {
  const bridge = await open();
  await openCatalog();
  setup!.mockInput.pressEnter();                                         // GitHub
  await until((x) => x.includes("GitHub token (1/1)") && x.includes("github.com/settings/tokens"));
  await setup!.mockInput.typeText("ghp_fake-test-token");
  await settle();
  setup!.mockInput.pressEnter();
  await until((x) => x.includes("GitHub connected — 26 tools"));
  expect(bridge.calls).toContainEqual(["mcp.install", { id: "github", values: { token: "ghp_fake-test-token" } }]);
});

test("Google services reuse the OAuth client already entered", async () => {
  const bridge = await open();
  await openCatalog();
  await down(1);                                                          // Gmail (prefilled)
  setup!.mockInput.pressEnter();
  await until((x) => x.includes("Google OAuth Client ID (1/3)"));
  for (let i = 0; i < 3; i++) {
    setup!.mockInput.pressEnter();
    await new Promise((r) => setTimeout(r, 220));          // a person's pace, not 2 enters in 150 ms
    await settle();
  }
  await until((x) => x.includes("Gmail connected"));
  expect(bridge.calls).toContainEqual(["mcp.install", { id: "gmail", values: {
    client_id: "1-a.apps.googleusercontent.com", client_secret: "GOCSPX-x", email: "me@gmail.com" } }]);
});

test("import from Claude and custom servers are in the catalog too", async () => {
  const bridge = await open();
  await openCatalog();
  await down(3);
  setup!.mockInput.pressEnter();
  await until((x) => x.includes("Imported obsidian"));
  expect(bridge.calls.some(([m]) => m === "mcp.import_claude")).toBe(true);
  await openCatalog();
  await down(4);
  setup!.mockInput.pressEnter();
  await until((x) => x.includes("Paste a server's config"));
  await setup!.mockInput.pasteBracketedText("npx -y @modelcontextprotocol/server-everything");
  await settle();
  setup!.mockInput.pressEnter();
  await until((x) => x.includes("everything: 13 tools"));
});

test("MCP calls read clearly in tool cards and approvals", () => {
  expect(mcpLabel("gmail__send_gmail_message")).toBe("gmail › send_gmail_message");
  expect(mcpLabel("read_file")).toBe("read_file");
  expect(permissionDetail("gmail__send_gmail_message", { to: "anna@x.pl", subject: "Dinner", body: "Hi Anna,\nFriday?" }))
    .toBe("to: anna@x.pl\nsubject: Dinner\nbody:\nHi Anna,\nFriday?");
});

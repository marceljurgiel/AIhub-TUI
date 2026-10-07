import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { AppTree, MockBridge } from "./test-tree.tsx";
import { BridgeClient } from "./bridge/client.ts";
import { sanitizeText } from "./bridge/sanitize.ts";
import { AppKeymapProvider } from "./keymap/AppKeymap.tsx";
import { PermissionModal, permissionDetail, wrapLines } from "./modals/PermissionModal.tsx";

let setup: Awaited<ReturnType<typeof testRender>> | undefined;
afterEach(() => {
  setup?.renderer.destroy();
  setup = undefined;
});

const tick = (ms = 30) => new Promise((r) => setTimeout(r, ms));

async function settle(t: NonNullable<typeof setup>, ms = 30) {
  await tick(ms);
  await t.flush();
  return t.captureCharFrame();
}

async function until(t: NonNullable<typeof setup>, pred: (f: string) => boolean, tries = 40) {
  for (let i = 0; i < tries; i++) {
    const f = await settle(t, 50);
    if (pred(f)) return f;
  }
  throw new Error("frame never matched:\n" + t.captureCharFrame());
}

// ── Terminal control characters ─────────────────────────────────────────────

test("sanitizeText neutralises escape sequences but keeps newlines and tabs", () => {
  expect(sanitizeText("a\x1b]0;title\x07b")).toBe("a␛]0;title␇b");
  expect(sanitizeText("x\x1b[31mred")).toBe("x␛[31mred");
  expect(sanitizeText("c1\x9b31m")).toBe("c1�31m");
  expect(sanitizeText("del\x7f")).toBe("del␡");
  expect(sanitizeText("line1\nline2\tcol")).toBe("line1\nline2\tcol");
  expect(sanitizeText("zażółć ✓")).toBe("zażółć ✓");
});

test("every string from the bridge is sanitised before handlers see it", async () => {
  const client = new BridgeClient();
  const seen: any[] = [];
  const done = new Promise((resolve, reject) =>
    (client as any).pending.set(7, { resolve, reject, handlers: { onEvent: (e: string, d: any) => seen.push([e, d]) } }),
  );
  const h = (msg: unknown) => (client as any).handleLine(JSON.stringify(msg));
  h({ id: 7, event: "text", data: { text: "hi\u001b]52;c;cGF5bG9hZA==\u0007" } });
  h({ id: 7, done: true, data: { messages: [{ role: "tool", content: "\u001b[2Jwiped" }] } });

  expect(seen[0][1].text).toBe("hi␛]52;c;cGF5bG9hZA==␇");
  const result: any = await done;
  expect(result.messages[0].content).toBe("␛[2Jwiped");
});

// ── Permission modal ────────────────────────────────────────────────────────

const LONG_CMD = "echo " + "harmless-looking-output ".repeat(8) + "&& rm -rf ~/important";

test("the full shell command is kept, however long", () => {
  const lines = wrapLines(permissionDetail("run_terminal", { command: LONG_CMD }), 40);
  expect(lines.join("")).toBe(LONG_CMD);
  expect(lines.every((l) => l.length <= 40)).toBe(true);
});

test("control characters in the command are shown, not interpreted", () => {
  const lines = wrapLines(permissionDetail("run_terminal", { command: "ls\r\x1b[8mrm -rf ~" }), 80);
  expect(lines.join("")).toBe("ls\\x0d\\x1b[8mrm -rf ~");
});

async function renderPermission(command: string) {
  const answers: boolean[] = [];
  let closed = false;
  setup = await testRender(
    <AppKeymapProvider>
      <PermissionModal
        tool="run_terminal"
        args={{ command }}
        onAnswer={(a) => answers.push(a)}
        onClose={() => {
          closed = true;
        }}
      />
    </AppKeymapProvider>,
    { width: 100, height: 30 },
  );
  await settle(setup);
  return { t: setup, answers, isClosed: () => closed };
}

test("the modal shows the dangerous tail of a long command", async () => {
  const { t } = await renderPermission(LONG_CMD);
  const frame = t.captureCharFrame();
  expect(frame).toContain("rm -rf ~/important");
  expect(frame).toContain("model wants to run a shell command");
});

test("Enter does not approve; only y does", async () => {
  const { t, answers, isClosed } = await renderPermission("ls");
  t.mockInput.pressEnter();
  await settle(t);
  expect(answers).toEqual([]);
  expect(isClosed()).toBe(false);

  t.mockInput.pressKey("y");
  await settle(t);
  expect(answers).toEqual([true]);
  expect(isClosed()).toBe(true);
});

// ── Chat turns: cancel and abandon ──────────────────────────────────────────

/** Bridge whose chat turns are driven by the test: events and completion are
 *  pushed by hand, so we can deliver them *after* a cancel or a new chat. */
class ControlledBridge extends MockBridge {
  turns: Array<{ id: number; params: any; handlers: any; finish: (d: any) => void }> = [];
  cancelled: number[] = [];
  permissions: Array<[number, boolean]> = [];
  private next = 100;
  override cancel(id?: number) {
    if (id !== undefined) this.cancelled.push(id);
  }
  override permission(id?: number, allow?: boolean) {
    if (id !== undefined) this.permissions.push([id, !!allow]);
  }
  override stream(method: string, params: any, handlers: any) {
    if (method !== "chat.turn") return super.stream(method, params, handlers);
    const id = this.next++;
    let finish!: (d: any) => void;
    const done = new Promise<any>((r) => (finish = r));
    this.turns.push({ id, params, handlers, finish });
    return { id, done };
  }
}

async function bootControlled() {
  const bridge = new ControlledBridge();
  setup = await testRender(<AppTree client={bridge as unknown as BridgeClient} />, { width: 110, height: 34 });
  await setup.waitForFrame((f) => f.includes("llama3.2:3b"), { maxPasses: 40 });
  return { t: setup, bridge };
}

async function send(t: NonNullable<typeof setup>, text: string) {
  await t.mockInput.typeText(text);
  t.mockInput.pressEnter();
  await settle(t);
}

const userMessages = (params: any) =>
  params.messages.filter((m: any) => m.role === "user").map((m: any) => m.content);

test("Esc cancels at once, unlocks input and drops late events", async () => {
  const { t, bridge } = await bootControlled();
  await send(t, "first question");
  const turn1 = bridge.turns[0]!;
  turn1.handlers.onEvent("text", { text: "partial answer" });
  await settle(t);

  t.mockInput.pressEscape();
  await until(t, (f) => f.includes("Stream cancelled."));
  expect(bridge.cancelled).toEqual([turn1.id]);
  // The part already shown stays (assistant bodies render asynchronously).
  let frame = await until(t, (f) => f.includes("partial answer"));

  // A late chunk from the cancelled turn must not render.
  turn1.handlers.onEvent("text", { text: "LATE-CHUNK" });
  frame = await settle(t);
  expect(frame).not.toContain("LATE-CHUNK");

  // Input is usable right away — before the old turn has finished.
  await send(t, "second question");
  expect(bridge.turns.length).toBe(2);

  // The old turn finishing now must not clobber the running one.
  turn1.finish({ messages: [...turn1.params.messages, { role: "assistant", content: "STALE" }], cancelled: true });
  bridge.turns[1]!.handlers.onEvent("text", { text: "fresh reply" });
  frame = await until(t, (f) => f.includes("fresh reply"));
  expect(frame).not.toContain("STALE");
});

test("a cancelled turn's final history is kept when nothing newer started", async () => {
  const { t, bridge } = await bootControlled();
  await send(t, "tell me a story");
  const turn1 = bridge.turns[0]!;
  t.mockInput.pressEscape();
  await until(t, (f) => f.includes("Stream cancelled."));
  turn1.finish({
    messages: [...turn1.params.messages, { role: "assistant", content: "Once upon" }],
    cancelled: true,
  });
  await settle(t);

  await send(t, "go on");
  const history = bridge.turns[1]!.params.messages;
  expect(history.at(-2)).toEqual({ role: "assistant", content: "Once upon" });
  expect(userMessages(bridge.turns[1]!.params)).toEqual(["tell me a story", "go on"]);
});

test("new chat during a reply abandons the turn for good", async () => {
  const { t, bridge } = await bootControlled();
  await send(t, "old conversation");
  const turn1 = bridge.turns[0]!;

  t.mockInput.pressKey("n", { ctrl: true });
  await settle(t);
  expect(bridge.cancelled).toEqual([turn1.id]);

  // Late events and the final result of the abandoned turn are ignored…
  turn1.handlers.onEvent("text", { text: "ZOMBIE" });
  turn1.handlers.onEvent("permission_request", { name: "run_terminal", arguments: { command: "ls" } });
  turn1.finish({ messages: [...turn1.params.messages, { role: "assistant", content: "ZOMBIE" }] });
  const frame = await settle(t, 60);
  expect(frame).not.toContain("ZOMBIE");
  expect(frame).not.toContain("Permission required");
  // …and a stale approval request is answered "no" so the engine can't hang.
  expect(bridge.permissions).toEqual([[turn1.id, false]]);

  await send(t, "fresh start");
  expect(userMessages(bridge.turns[1]!.params)).toEqual(["fresh start"]);
});

// ── Odd text must render, not crash ─────────────────────────────────────────

const ODD_REPLIES = [
  "a[/] b [b]not bold[/b] [red]x",
  "```python\nunclosed fence\nprint(1)",
  "| broken | table\n|---\n| x",
  "**unclosed bold and `unclosed code",
  "<script>alert(1)</script> &amp; <b>html</b>",
  "x".repeat(5000),
  "emoji 🧪👩‍💻 zażółć gęślą jaźń 中文 عربى",
];

test("odd replies (brackets, broken markdown, huge lines) render without crashing", async () => {
  const { t, bridge } = await bootControlled();
  for (const [i, reply] of ODD_REPLIES.entries()) {
    await send(t, `q${i}`);
    const turn = bridge.turns[i]!;
    turn.handlers.onEvent("text", { text: reply });
    turn.handlers.onEvent("round", { round: 0, text: reply, had_tool_calls: false });
    turn.finish({ messages: [...turn.params.messages, { role: "assistant", content: reply }] });
    await settle(t, 60);
  }
  const frame = await until(t, (f) => f.includes("中文"));
  expect(frame).toContain("q6");
});

test("brackets in replies survive rendering (list[str], arr[0])", async () => {
  const { t, bridge } = await bootControlled();
  await send(t, "types?");
  const reply = "Use list[str] and arr[0] or a[/] b.";
  const turn = bridge.turns[0]!;
  turn.handlers.onEvent("text", { text: reply });
  turn.handlers.onEvent("round", { round: 0, text: reply, had_tool_calls: false });
  turn.finish({ messages: [...turn.params.messages, { role: "assistant", content: reply }] });
  const frame = await until(t, (f) => f.includes("Use list"));
  expect(frame).toContain(reply);
});

test("failed and denied tool calls don't look like successes", async () => {
  const { t, bridge } = await bootControlled();
  await send(t, "save notes");
  const turn = bridge.turns[0]!;
  const call = (id: string, name: string) =>
    turn.handlers.onEvent("tool_call", { call_id: id, name, arguments: { path: "notes.txt" } });
  call("c1", "edit_file");
  turn.handlers.onEvent("tool_result", {
    call_id: "c1", name: "edit_file", arguments: {}, duration_ms: 3,
    result: "[Edit Error] File not found: notes.txt", error: "[Edit Error] File not found: notes.txt", denied: false,
  });
  call("c2", "write_file");
  turn.handlers.onEvent("tool_result", {
    call_id: "c2", name: "write_file", arguments: {}, duration_ms: 1,
    result: "[Denied by user] …", error: "Denied by user", denied: true,
  });
  const frame = await until(t, (f) => f.includes("denied by you"));
  expect(frame).toContain("✗");
  expect(frame).toContain("[Edit Error] File not found");
  expect(frame).toContain("⊘");
  expect(frame).not.toMatch(/✓ (edit|write)_file/);
});

test("ready() after the banner still reports the engine version", async () => {
  const client = new BridgeClient();
  (client as any).handleLine(JSON.stringify({ id: null, event: "ready", data: { version: "0.3.24" } }));
  expect(await client.ready()).toEqual({ version: "0.3.24" });   // was "?" → "core ?"
});

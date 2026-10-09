/** Scheduled tasks in the app: the Schedule window (F7), its form, and /schedule. */
import { test, expect, afterEach } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { AppTree, MockBridge } from "./test-tree.tsx";
import type { BridgeClient } from "./bridge/client.ts";
import { formatSlot } from "./schedule/format.ts";
import { TaskQueue } from "./schedule/queue.ts";
import { schedulerTiming } from "./schedule/useScheduler.ts";

let setup: Awaited<ReturnType<typeof testRender>> | undefined;
afterEach(() => {
  setup?.renderer.destroy();
  setup = undefined;
  schedulerTiming.checkMs = 30_000;
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
const pause = (ms = 250) => new Promise((r) => setTimeout(r, ms));

export const DIGEST = {
  name: "mail-digest", agent: "mail", model: "llama3.2:3b", backend: "ollama", stream_model: "llama3.2:3b",
  when: "daily 08:00", prompt: "Summarize today's unread email for alex.", enabled: true,
  created: "2026-10-01T09:00:00", broken: "", path: "/home/alex/.aihub/schedule/mail-digest.md",
  next_run: "2026-10-08T08:00:00", last_run: "2026-10-07T08:00:05", last_status: "ok",
  last_summary: "Three new emails: the Lisbon trip is confirmed.", last_error: "",
  last_session: { model: "llama3.2:3b", filename: "2026-10-07_08-00-05.json" },
};

export class ScheduleBridge extends MockBridge {
  calls: Array<[string, any]> = [];
  tasks: any[] = [{ ...DIGEST }];
  listGate: Promise<void> | null = null;
  saveErrors: string[] = [];
  override async request(method: string, params: any = {}): Promise<any> {
    this.calls.push([method, params]);
    switch (method) {
      case "schedule.list":
        if (this.listGate) await this.listGate;
        return { tasks: this.tasks };
      case "schedule.check":
        return { due: [], missed: [] };
      case "schedule.toggle":
        this.tasks = this.tasks.map((t) => (t.name === params.name ? { ...t, enabled: params.enabled } : t));
        return { task: this.tasks.find((t) => t.name === params.name) };
      case "schedule.delete":
        this.tasks = this.tasks.filter((t) => t.name !== params.name);
        return { ok: true };
      case "schedule.save": {
        const err = this.saveErrors.shift();
        if (err) throw new Error(err);
        const t = { ...DIGEST, ...params.task, last_status: null, last_summary: "", last_session: null };
        this.tasks = [...this.tasks.filter((x) => x.name !== (params.original_name ?? t.name)), t];
        return { task: t };
      }
      case "agents.list":
        return { agents: [
          { name: "coder", description: "Writes code", builtin: true },
          { name: "mail", description: "Reads your mail", builtin: true },
        ] };
      default:
        return super.request(method);
    }
  }
  override stream(method: string, params: any, handlers: any): { id: number; done: Promise<any> } {
    if (method === "schedule.run") {
      this.calls.push([method, params]);
      return { id: 9, done: new Promise(() => {}) };
    }
    return super.stream(method, params, handlers);
  }
}

async function open<B extends ScheduleBridge = ScheduleBridge>(
  bridge: B = new ScheduleBridge() as B,
  ready: (f: string) => boolean = (f) => f.includes("llama3.2:3b") && f.includes("tab menu"),
  size = { width: 110, height: 36 },
): Promise<B> {
  setup = await testRender(<AppTree client={bridge as unknown as BridgeClient} />, size);
  await until(ready);
  return bridge;
}

async function openSchedule() {
  setup!.mockInput.pressKey("F7");
  return until((f) => f.includes("Schedule") && f.includes("mail-digest"));
}

test("slot times read as today / tomorrow / a date", () => {
  const now = new Date(2026, 9, 7, 10, 0);
  expect(formatSlot("2026-10-07T18:30:00", now)).toBe("today 18:30");
  expect(formatSlot("2026-10-08T08:00:00", now)).toBe("tomorrow 08:00");
  expect(formatSlot("2026-10-12T09:00:00", now)).toBe("Mon 12 Oct 09:00");
  expect(formatSlot("2026-10-06T08:00:00", now)).toBe("Tue 6 Oct 08:00");
});

test("F7 opens Schedule with tasks, the last result and the only-while-open note", async () => {
  await open();
  const f = await openSchedule();
  expect(f).toMatch(/\[✓\] mail-digest\s+daily 08:00/);
  expect(f).toContain("ok ·");
  expect(f).toContain("Three new emails: the Lisbon trip is confirmed.");
  expect(f).toContain("Tasks run only while AIhub is open.");
});

test("an 80-column terminal: the hint bar stays one line, every key in it", async () => {
  await open(undefined, (f) => f.includes("New Chat"), { width: 80, height: 24 });
  const all = (await openSchedule()).split("\n");
  const top = all.findIndex((l, i) => l.includes("╭") && all[i + 1]?.includes("Schedule"));
  const col = all[top]!.indexOf("╭");
  const bottom = all.findIndex((l, i) => i > top && l[col] === "╰");
  const bar = all[bottom - 1]!;
  for (const k of ["n", "e", "space", "r", "↵", "d"]) expect(bar).toContain(` ${k} `);
  expect(bar).toMatch(/new.*edit.*on\/off.*run.*delete/);
  expect(all[bottom - 2]).not.toMatch(/ n {2}new/);           // no first half of a wrapped bar
});

test("shows Loading tasks… before the list arrives", async () => {
  const bridge = new ScheduleBridge();
  let release = () => {};
  bridge.listGate = new Promise<void>((r) => (release = r));
  await open(bridge);
  setup!.mockInput.pressKey("F7");
  await until((f) => f.includes("Loading tasks…"));
  expect(setup!.captureCharFrame()).not.toContain("No scheduled tasks");
  release();
  await until((f) => f.includes("mail-digest"));
});

test("space toggles, r runs now, d needs a second press", async () => {
  const bridge = await open();
  await openSchedule();
  setup!.mockInput.pressKey(" ");
  await until((f) => f.includes("[ ] mail-digest") && f.includes("(off)"));
  expect(bridge.calls).toContainEqual(["schedule.toggle", { name: "mail-digest", enabled: false }]);
  setup!.mockInput.pressKey("r");
  await until(() => bridge.calls.some(([m]) => m === "schedule.run"));
  expect(bridge.calls.find(([m]) => m === "schedule.run")![1]).toEqual({ name: "mail-digest" });
  setup!.mockInput.pressKey("d");
  await until((f) => f.includes("Press d again to delete mail-digest."));
  expect(bridge.calls.some(([m]) => m === "schedule.delete")).toBe(false);
  setup!.mockInput.pressKey("d");
  await until((f) => f.includes("No scheduled tasks yet"));
  expect(bridge.calls).toContainEqual(["schedule.delete", { name: "mail-digest" }]);
});

test("n creates a task with the current model; an engine error keeps the form open", async () => {
  const bridge = await open();
  bridge.saveErrors = ["unknown schedule 'tomorrow' — use one of: every 30m · daily 08:00"];
  await openSchedule();
  setup!.mockInput.pressKey("n");
  await until((f) => f.includes("Task name"));
  await settle();
  await setup!.mockInput.typeText("weekly-report");
  await pause();
  setup!.mockInput.pressEnter();
  await until((f) => f.includes("Which agent runs it?") && f.includes("model: llama3.2:3b (current)"));
  setup!.mockInput.pressArrow("down");                                   // coder → mail
  await settle();
  setup!.mockInput.pressEnter();
  await until((f) => f.includes("When?") && f.includes("weekdays 08:00"));
  await settle();
  await setup!.mockInput.typeText("tomorrow");
  await pause();
  setup!.mockInput.pressEnter();
  await until((f) => f.includes("What should mail do?"));
  await settle();
  await setup!.mockInput.typeText("Summarize the week for alex.");
  setup!.mockInput.pressKey("s", { ctrl: true });
  await until((f) => f.includes("unknown schedule 'tomorrow'"));
  expect(setup!.captureCharFrame()).toContain("What should mail do?");   // still in the form
  setup!.mockInput.pressKey("s", { ctrl: true });                        // second save succeeds
  await until((f) => f.includes("weekly-report") && f.includes("Tasks run only while AIhub is open."));
  const saves = bridge.calls.filter(([m]) => m === "schedule.save").map(([, p]) => p);
  expect(saves[1].task).toMatchObject({
    name: "weekly-report", agent: "mail", when: "tomorrow", prompt: "Summarize the week for alex.",
    model: "llama3.2:3b", backend: "ollama", stream_model: "llama3.2:3b", enabled: true,
  });
});

test("e edits the selected task and keeps its name as original_name", async () => {
  const bridge = await open();
  await openSchedule();
  setup!.mockInput.pressKey("e");
  await until((f) => f.includes("Task name"));
  await pause();
  setup!.mockInput.pressEnter();                                         // keep the name
  await until((f) => f.includes("Which agent runs it?") && f.includes("model: llama3.2:3b"));
  setup!.mockInput.pressEnter();                                         // keep mail
  await until((f) => f.includes("When?"));
  await pause();
  setup!.mockInput.pressEnter();                                         // keep daily 08:00
  await until((f) => f.includes("What should mail do?"));
  await settle();
  setup!.mockInput.pressKey("s", { ctrl: true });
  await until((f) => f.includes("Tasks run only while AIhub is open."));
  const save = bridge.calls.find(([m]) => m === "schedule.save")![1];
  expect(save.original_name).toBe("mail-digest");
  expect(save.task).toMatchObject({ name: "mail-digest", agent: "mail", when: "daily 08:00",
                                    prompt: "Summarize today's unread email for alex." });
});

test("/schedule opens the window", async () => {
  await open();
  await settle();
  await setup!.mockInput.typeText("/schedule");
  setup!.mockInput.pressEnter();
  await until((f) => f.includes("Tasks run only while AIhub is open."));
});


// ── The clock, the queue and the missed-run prompt ───────────────────────────

test("TaskQueue: one at a time, no duplicates, never next to a chat turn", () => {
  const q = new TaskQueue();
  expect(q.enqueue("a", "s1")).toBe(true);
  expect(q.enqueue("a", "s2")).toBe(false);                 // already waiting
  expect(q.enqueue("b")).toBe(true);
  expect(q.next(true)).toBeNull();                           // chat is busy
  expect(q.next(false)).toEqual({ name: "a", slot: "s1" });
  q.start("a");
  expect(q.running).toBe("a");
  expect(q.enqueue("a")).toBe(false);                        // running
  expect(q.next(false)).toBeNull();                          // one at a time
  q.finish();
  expect(q.next(false)).toEqual({ name: "b", slot: undefined });
  expect(q.size).toBe(0);
});

/** A bridge whose chat turns and task runs finish when the test says so. */
class ClockBridge extends ScheduleBridge {
  due: Array<{ name: string; slot: string }> = [];
  missed: Array<{ name: string; when: string; slot: string }> = [];
  runs: Array<{ params: any; resolve: (v: any) => void; reject: (e: Error) => void }> = [];
  turns: Array<{ params: any; resolve: () => void }> = [];
  override async request(method: string, params: any = {}): Promise<any> {
    if (method === "schedule.check") {
      this.calls.push([method, params]);
      if (params.startup) return { due: [], missed: this.missed };
      const due = this.due;
      this.due = [];
      return { due, missed: [] };
    }
    if (method === "schedule.skip") {
      this.calls.push([method, params]);
      return { ok: true };
    }
    return super.request(method, params);
  }
  override stream(method: string, params: any, handlers: any): { id: number; done: Promise<any> } {
    if (method === "schedule.run") {
      this.calls.push([method, params]);
      const done = new Promise<any>((resolve, reject) => this.runs.push({ params, resolve, reject }));
      return { id: 70 + this.runs.length, done };
    }
    if (method === "chat.turn") {
      this.calls.push([method, params]);
      const done = new Promise<any>((resolve) =>
        this.turns.push({
          params,
          resolve: () => resolve({ messages: [...params.messages, { role: "assistant", content: "Sure." }] }),
        }),
      );
      return { id: 40 + this.turns.length, done };
    }
    return super.stream(method, params, handlers);
  }
  count(method: string) {
    return this.calls.filter(([m]) => m === method).length;
  }
}

async function boot(bridge: ClockBridge): Promise<ClockBridge> {
  schedulerTiming.checkMs = 50;
  return open(bridge);
}

async function send(text: string) {
  await settle();
  await setup!.mockInput.typeText(text);
  setup!.mockInput.pressEnter();
}

test("a due task waits for the chat turn that is streaming", async () => {
  const bridge = await boot(new ClockBridge());
  await send("hello");
  await until(() => bridge.turns.length === 1);
  bridge.due = [{ name: "mail-digest", slot: "2026-10-07T08:00:00" }];
  await until(() => bridge.count("schedule.check") >= 3);
  expect(bridge.count("schedule.run")).toBe(0);                     // the chat has the model
  bridge.turns[0]!.resolve();
  await until(() => bridge.runs.length === 1);
  expect(bridge.runs[0]!.params).toEqual({ name: "mail-digest", slot: "2026-10-07T08:00:00" });
});

test("a chat message waits for a running task, then goes", async () => {
  const bridge = await boot(new ClockBridge());
  bridge.due = [{ name: "mail-digest", slot: "2026-10-07T08:00:00" }];
  await until(() => bridge.runs.length === 1);
  await until((f) => f.includes("► task mail-digest…"));            // the footer says so
  await send("what's new?");
  await until((f) => f.includes("Waiting for task mail-digest…"));
  expect(bridge.count("chat.turn")).toBe(0);
  bridge.runs[0]!.resolve({ status: "ok", summary: "Two emails.", session: null });
  await until((f) => f.includes("Task mail-digest finished — F7 to see it."));
  await until(() => bridge.turns.length === 1);
  expect(bridge.turns[0]!.params.messages.at(-1)).toMatchObject({ role: "user", content: "what's new?" });
  expect(setup!.captureCharFrame()).not.toContain("► task");
});

test("a failed task says why and points to F7", async () => {
  const bridge = await boot(new ClockBridge());
  bridge.due = [{ name: "mail-digest", slot: "2026-10-07T08:00:00" }];
  await until(() => bridge.runs.length === 1);
  bridge.runs[0]!.reject(new Error("Ollama is offline — start it, then run the task again"));
  await until((f) => f.includes("Task mail-digest failed: Ollama is offline") && f.includes("F7 for details"));
});

test("missed tasks are asked about on startup: Enter runs, s skips", async () => {
  const bridge = new ClockBridge();
  bridge.missed = [
    { name: "mail-digest", when: "daily 08:00", slot: "2026-10-07T08:00:00" },
    { name: "kb-report", when: "weekly Mon 09:00", slot: "2026-10-05T09:00:00" },
  ];
  schedulerTiming.checkMs = 50;
  await open(bridge, (f) => f.includes("Missed while AIhub was closed") && f.includes("mail-digest") && f.includes("daily 08:00"));
  expect(bridge.count("schedule.check")).toBe(1);                   // no periodic checks while asking
  await pause();
  setup!.mockInput.pressEnter();
  await until((f) => f.includes("kb-report") && f.includes("weekly Mon 09:00"));
  await pause();
  setup!.mockInput.pressKey("s");
  await until(() => bridge.calls.some(([m]) => m === "schedule.skip"));
  expect(bridge.calls).toContainEqual(["schedule.skip", { name: "kb-report", slot: "2026-10-05T09:00:00" }]);
  await until(() => bridge.runs.length === 1);
  expect(bridge.runs[0]!.params).toEqual({ name: "mail-digest", slot: "2026-10-07T08:00:00" });
  await until(() => bridge.count("schedule.check") >= 2);           // the clock starts after
});

test("the Schedule window follows a running task: r cancels it, the list refreshes when it ends", async () => {
  const bridge = await boot(new ClockBridge());
  const cancelled: number[] = [];
  bridge.cancel = ((id: number) => cancelled.push(id)) as any;
  await openSchedule();
  bridge.due = [{ name: "mail-digest", slot: "2026-10-07T08:00:00" }];
  await until((f) => f.includes("► running…") && f.includes("r  cancel"));
  setup!.mockInput.pressKey("r");
  await until((f) => f.includes("Cancelled task mail-digest."));
  expect(cancelled).toEqual([71]);
  const lists = bridge.count("schedule.list");
  bridge.runs[0]!.resolve({ status: "cancelled", summary: "", session: null });
  await until((f) => !f.includes("► running…") && bridge.count("schedule.list") > lists);
});

test("quitting while a task runs cancels it and waits for the engine to record it", async () => {
  const bridge = await boot(new ClockBridge());
  const cancelled: number[] = [];
  bridge.cancel = ((id: number) => cancelled.push(id)) as any;
  bridge.due = [{ name: "mail-digest", slot: "2026-10-07T08:00:00" }];
  await until(() => bridge.runs.length === 1);
  setup!.mockInput.pressKey("q", { ctrl: true });
  await until(() => cancelled.length === 1);
  expect(cancelled).toEqual([71]);
  await pause(200);
  expect(setup!.renderer.isDestroyed).toBe(false);                  // still waiting for the engine
  bridge.runs[0]!.resolve({ status: "cancelled", summary: "", session: null });
  for (let i = 0; i < 25 && !setup!.renderer.isDestroyed; i++) await pause(40);
  expect(setup!.renderer.isDestroyed).toBe(true);
  setup = undefined;
});

// ── Final review fixes ───────────────────────────────────────────────────────

test("a held message and the next queued task never run together", async () => {
  const bridge = await boot(new ClockBridge());
  bridge.due = [
    { name: "a", slot: "2026-10-07T08:00:00" },
    { name: "b", slot: "2026-10-07T08:00:00" },
  ];
  await until(() => bridge.runs.length === 1);
  await send("hi");
  await until((f) => f.includes("Waiting for task a…"));
  bridge.runs[0]!.resolve({ status: "ok", summary: "", session: null });
  await until(() => bridge.turns.length === 1);                     // the held message goes first
  await settle();
  await pause(200);
  expect(bridge.runs.length).toBe(1);                               // b waits for the reply
  bridge.turns[0]!.resolve();
  await until(() => bridge.runs.length === 2);
  expect(bridge.runs[1]!.params.name).toBe("b");
});

test("a failing schedule check is said once in the chat, not every 30 s", async () => {
  class Broken extends ClockBridge {
    override async request(method: string, params: any = {}): Promise<any> {
      if (method === "schedule.check") {
        this.calls.push([method, params]);
        throw new Error("schedule.check: can't read ~/.aihub/schedule");
      }
      return super.request(method, params);
    }
  }
  const bridge = await boot(new Broken());
  await until(() => bridge.count("schedule.check") >= 4);
  const f = setup!.captureCharFrame();
  expect(f).toContain("Scheduled tasks can't be checked: schedule.check: can't read");
  expect(f.split("Scheduled tasks can't be checked").length).toBe(2);   // once
});

test("memory learning waits while a task has the model", async () => {
  const bridge = await boot(new ClockBridge());
  await send("hello");
  await until(() => bridge.turns.length === 1);
  bridge.due = [{ name: "mail-digest", slot: "2026-10-07T08:00:00" }];
  await until(() => bridge.count("schedule.check") >= 3);
  bridge.turns[0]!.resolve();                                       // reply done → task starts
  await until(() => bridge.runs.length === 1);
  await pause(400);                                                 // learning is due after 80 ms
  expect(bridge.count("memory.learn")).toBe(0);
  bridge.runs[0]!.resolve({ status: "ok", summary: "", session: null });
  await until(() => bridge.count("memory.learn") === 1);
});

test("a task's result opens without empty reply blocks for tool-only rounds", async () => {
  class HistBridge extends ScheduleBridge {
    override async request(method: string, params: any = {}): Promise<any> {
      if (method === "history.load")
        return {
          messages: [
            { role: "system", content: "sys" },
            { role: "user", content: "List the functions in inventory.py." },
            { role: "assistant", content: "", tool_calls: [{ function: { name: "read_file", arguments: {} } }] },
            { role: "tool", content: "def total_value(items): ..." },
            { role: "assistant", content: "total_value sums the stock." },
          ],
        };
      return super.request(method, params);
    }
  }
  await open(new HistBridge());
  await openSchedule();
  setup!.mockInput.pressEnter();                                    // ↵ result
  const f = await until((x) => x.includes("total_value sums the stock."));
  expect(f.split("\n").filter((l) => l.includes("‹ AIHUB")).length).toBe(1);
  expect(f).toContain("Resumed session — 3 messages.");
});

test("the note follows a run now: running, then finished", async () => {
  let finish: (v: any) => void = () => {};
  class DoneBridge extends ScheduleBridge {
    override stream(method: string, params: any, handlers: any): { id: number; done: Promise<any> } {
      if (method !== "schedule.run") return super.stream(method, params, handlers);
      this.calls.push([method, params]);
      return { id: 9, done: new Promise((r) => (finish = r)) };
    }
  }
  await open(new DoneBridge());
  await openSchedule();
  setup!.mockInput.pressKey("r");
  await until((f) => f.includes("Running mail-digest…"));
  // Ends before the window's next look (a run that fails at once).
  finish({ status: "ok", summary: "Done.", session: null });
  const f = await until((x) => x.includes("mail-digest finished"));
  expect(f).not.toContain("Running mail-digest…");
});

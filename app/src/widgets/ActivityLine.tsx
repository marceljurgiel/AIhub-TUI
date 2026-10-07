import { useEffect, useState } from "react";
import { theme, fit } from "../theme.ts";
import { Spinner } from "../ui/primitives.tsx";

/** What the model is doing right now — drives the live status line. */
export type Phase = "working" | "thinking" | "writing" | "tool" | "approval";

export interface Activity {
  phase: Phase;
  /** Tool being run, for phase "tool". */
  tool?: string;
  /** When the turn started (ms since epoch) — the elapsed counter. */
  startedAt: number;
  /** Tail of the model's current reasoning, for phase "thinking". */
  thought: string;
}

const VERB: Record<Phase, (a: Activity) => string> = {
  working: () => "Working…",
  thinking: () => "Thinking…",
  writing: () => "Writing…",
  tool: (a) => `Running ${a.tool ?? "tool"}…`,
  approval: () => "Waiting for your approval…",
};

/** "8s", "1m 05s" — like Claude Code's counter. */
export function formatElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

/** Last non-empty line of the reasoning, for the one-line preview. */
function lastLine(text: string): string {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  return lines[lines.length - 1] ?? "";
}

/**
 * Live status above the chat input while a reply is in flight:
 *
 *   ⠋ Thinking… (14s · esc to interrupt)
 *     ⎿ The user wants 17*23, so 17*20 = 340 plus 17*3…
 *
 * Before the first token it says "Working…" (loading the model / reading the
 * prompt), so a long silent wait never looks like a hang.
 */
export function ActivityLine({ activity, width }: { activity: Activity; width: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const preview = activity.phase === "thinking" ? lastLine(activity.thought) : "";
  return (
    <box flexDirection="column" paddingLeft={2} flexShrink={0}>
      <text>
        <Spinner color={activity.phase === "approval" ? theme.warn : theme.accent} />
        <span fg={activity.phase === "approval" ? theme.warn : theme.accentSoft}>{` ${VERB[activity.phase](activity)}`}</span>
        <span fg={theme.fg2}>{` (${formatElapsed(now - activity.startedAt)} · esc to interrupt)`}</span>
      </text>
      {preview ? <text fg={theme.fg2}>{`  ⎿ ${fit(preview, Math.max(10, width - 8))}`}</text> : null}
    </box>
  );
}

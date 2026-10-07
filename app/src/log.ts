/** The chat log is a list of render items, kept separate from the model's
 *  `messages` array (which is the raw context sent to the backend) — mirroring
 *  the Textual app's ChatLog vs SessionState.messages split. */
export type LogItem =
  | { kind: "system"; text: string; error?: boolean }
  | { kind: "user"; text: string; images?: string[] }
  | { kind: "assistant"; text: string }
  /** A change the automatic memory made ("✻ Remembered · Editor — VS Code"). */
  | { kind: "memory"; op: "add" | "update" | "forget" | "undo"; topic: string; before?: string | null; after?: string | null }
  /** The model's reasoning for one stretch of thinking, collapsed in the log. */
  | { kind: "thought"; seconds: number; text: string }
  | {
      kind: "tool";
      id: string;
      name: string;
      args: unknown;
      /** "denied": the user declined it in the approval prompt. */
      status: "running" | "done" | "error" | "denied";
      result?: string;
      error?: string | null;
      durationMs?: number;
    };

/** Heuristic port of message_bubble.py: does this text want markdown rendering? */
export function looksLikeMarkdown(text: string): boolean {
  if (!text) return false;
  if (text.includes("```")) return true; // code fence
  if (/\|.*\|/.test(text)) return true; // table row
  if (/\*\*.+\*\*/.test(text)) return true; // bold
  if (/`[^`]+`/.test(text)) return true; // inline code
  for (const line of text.split("\n")) {
    const t = line.trimStart();
    if (/^#{1,6}\s/.test(t)) return true; // heading
    if (/^[-*+]\s/.test(t)) return true; // bullet list
    if (/^\d+\.\s/.test(t)) return true; // numbered list
    if (t.startsWith(">")) return true; // blockquote
  }
  return false;
}

/** Truncate a tool result for the collapsed/expanded panel body. */
export function truncateResult(text: string, max = 4000): string {
  if (!text || text.length <= max) return text;
  return text.slice(0, max) + `\n…(truncated, ${text.length} bytes total)`;
}

/** Short JSON preview of tool arguments for a panel title. */
export function argsPreview(args: unknown, max = 60): string {
  let s: string;
  try {
    s = JSON.stringify(args);
  } catch {
    s = String(args);
  }
  return s.length > max ? s.slice(0, max) + "…" : s;
}

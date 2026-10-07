import { useTerminalDimensions } from "@opentui/react";
import { theme } from "../theme.ts";
import { ModalShell } from "../ui/ModalShell.tsx";
import { Spinner } from "../ui/primitives.tsx";
import { useModalKeys } from "./modalKit.ts";

const VERBS: Record<string, string> = {
  run_terminal: "run a shell command",
  write_file: "write a file",
  edit_file: "edit a file",
};

/** Make control characters visible. The detail is what the user approves, so
 *  an ESC sequence or a bare \r in model-written arguments must not be able to
 *  restyle, hide or overwrite part of it. */
export function visible(text: string): string {
  return text.replace(/[\x00-\x08\x0b-\x1f\x7f]/g, (c) => `\\x${c.charCodeAt(0).toString(16).padStart(2, "0")}`);
}

/** Everything the user is being asked to approve — never truncated for
 *  run_terminal, since a cut-off command could hide its dangerous tail. */
export function permissionDetail(tool: string, args: unknown): string {
  const a = (args ?? {}) as Record<string, unknown>;
  const str = (v: unknown) => (typeof v === "string" ? v : v == null ? "" : JSON.stringify(v));
  if (tool === "run_terminal") return str(a.command);
  if (tool === "edit_file")
    return `${str(a.path)}\n\n- ${str(a.old).replace(/\n/g, "\n- ")}\n+ ${str(a.new).replace(/\n/g, "\n+ ")}`;
  if (tool === "write_file") return `${str(a.path)}\n\n${str(a.content)}`;
  // MCP (a connected service, e.g. Gmail): every argument on its own line —
  // to / subject / body read like the email that will be sent.
  if (tool.includes("__"))
    return Object.entries(a)
      .map(([k, v]) => (str(v).includes("\n") ? `${k}:\n${str(v)}` : `${k}: ${str(v)}`))
      .join("\n") || "(no arguments)";
  try {
    return JSON.stringify(args, null, 2);
  } catch {
    return String(args);
  }
}

/** Hard-wrap to `width` columns so the modal can size itself exactly. */
export function wrapLines(text: string, width: number): string[] {
  const out: string[] = [];
  for (const line of visible(text).split("\n")) {
    if (!line) out.push("");
    for (let i = 0; i < line.length; i += width) out.push(line.slice(i, i + width));
  }
  return out;
}

/**
 * Approval gate for mutating tools — shown in plain chat and agent plan mode.
 * The bridge pauses the stream on a `permission_request` event until
 * chat.permission answers; this modal is that answer's UI.
 */
export function PermissionModal({
  tool,
  args,
  onAnswer,
  onClose,
}: {
  tool: string;
  args: unknown;
  onAnswer: (allow: boolean) => void;
  onClose: () => void;
}) {
  const { width: termW, height: termH } = useTerminalDimensions();
  const answer = (allow: boolean) => {
    onAnswer(allow);
    onClose();
  };

  // Only an explicit `y` allows. Enter is deliberately unbound: a reflexive
  // Enter must not approve a shell command.
  useModalKeys([
    { key: "escape", run: () => answer(false) },
    { key: "y", run: () => answer(true) },
    { key: "n", run: () => answer(false) },
  ]);

  const width = Math.max(40, Math.min(100, termW - 4));
  const inner = width - 4; // border + body padding
  const lines = wrapLines(permissionDetail(tool, args), inner);
  // Chrome: 2 borders + title + rule + verb row (+margin) + body margin + hints.
  const chrome = 8;
  const maxBody = Math.max(3, termH - 2 - chrome);
  const bodyH = Math.min(lines.length, maxBody);
  const scrolls = lines.length > bodyH;
  const hints: Array<[string, string]> = [["y", "allow"], ["n / esc", "deny"]];
  if (scrolls) hints.push(["↑↓", "scroll"]);

  return (
    <ModalShell title="Permission required" width={width} height={bodyH + chrome} hints={hints}>
      <box marginTop={1} flexShrink={0}>
        <text>
          <Spinner color={theme.warn} />
          <span fg={theme.fg2}>
            {`  model wants to ${VERBS[tool] ?? (tool.includes("__") ? `use ${tool.split("__")[0]} →` : "run")} `}
          </span>
          <span fg={theme.accentSoft}>{visible(tool.includes("__") ? tool.split("__").slice(1).join("__") : tool)}</span>
        </text>
      </box>
      <scrollbox marginTop={1} height={bodyH} focused={scrolls}>
        {lines.map((l, i) => (
          <text key={i} fg={theme.fg1} wrapMode="none">
            {l || " "}
          </text>
        ))}
      </scrollbox>
    </ModalShell>
  );
}

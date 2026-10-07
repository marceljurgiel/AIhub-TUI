import { useState } from "react";
import { theme, fit } from "../theme.ts";
import { argsPreview, truncateResult, type LogItem } from "../log.ts";
import { Spinner } from "../ui/primitives.tsx";

type ToolItem = Extract<LogItem, { kind: "tool" }>;

/** A collapsible tool-call panel — mirrors tui/widgets/tool_panel.py.
 *  Collapsed by default; click the header to expand. Running tools spin,
 *  failures go red and denials amber, each with the reason on the header row
 *  so a failed call never reads as a success; completions stay quiet. */
export function ToolPanel({ item }: { item: ToolItem }) {
  const [expanded, setExpanded] = useState(false);

  const preview = argsPreview(item.args);
  const dur = item.durationMs != null ? `${item.durationMs}ms` : "";
  const outcome =
    item.status === "denied"
      ? { text: "denied by you", color: theme.warn }
      : item.status === "error"
        ? { text: fit(item.error || "failed", 36), color: theme.error }
        : null;
  const statusGlyph =
    item.status === "running" ? (
      <Spinner color={theme.warn} />
    ) : item.status === "error" ? (
      <span fg={theme.error}>✗</span>
    ) : item.status === "denied" ? (
      <span fg={theme.warn}>⊘</span>
    ) : (
      <span fg={theme.success}>✓</span>
    );

  return (
    <box
      marginTop={1}
      marginLeft={2}
      marginRight={2}
      flexDirection="column"
      backgroundColor={theme.bg1}
      border
      borderStyle="rounded"
      borderColor={
        item.status === "error" ? theme.error : item.status === "denied" ? theme.warn : theme.border
      }
    >
      <box
        flexDirection="row"
        justifyContent="space-between"
        paddingLeft={1}
        paddingRight={1}
        onMouseDown={() => setExpanded((e) => !e)}
      >
        <text>
          <span fg={theme.fg2}>{`${expanded ? "▾ " : "▸ "}`}</span>
          {statusGlyph}
          <span fg={theme.accentSoft}>{` ${mcpLabel(item.name)}`}</span>
          <span fg={theme.fg2}>{`  ${preview}`}</span>
        </text>
        <text>
          {outcome ? <span fg={outcome.color}>{outcome.text}</span> : null}
          <span fg={theme.fg2}>{outcome && dur ? `  ${dur}` : dur}</span>
        </text>
      </box>

      {expanded ? (
        <box flexDirection="column" paddingLeft={1} paddingRight={1} paddingBottom={1}>
          <text fg={theme.fg2}>{`args: ${argsPreview(item.args, 400)}`}</text>
          {item.result ? (
            <box marginTop={1} flexDirection="column">
              <text fg={theme.fg2}>{"─".repeat(58)}</text>
              <text fg={theme.fg1}>{truncateResult(item.result)}</text>
            </box>
          ) : null}
          {/* The error is usually the result's first line — don't print it twice. */}
          {item.error && !String(item.result ?? "").trim().startsWith(item.error.trim()) ? (
            <text fg={theme.error}>{item.error}</text>
          ) : null}
        </box>
      ) : null}
    </box>
  );
}

/** "gmail__send_gmail_message" → "gmail › send_gmail_message" (MCP tools). */
export function mcpLabel(name: string): string {
  const i = name.indexOf("__");
  return i > 0 ? `${name.slice(0, i)} › ${name.slice(i + 2)}` : name;
}

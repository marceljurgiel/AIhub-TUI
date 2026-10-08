import { memo, useMemo, useState } from "react";
import { SyntaxStyle, getTreeSitterClient } from "@opentui/core";
import { theme } from "../theme.ts";
import { useThemeVersion } from "../state/useTheme.ts";
import type { LogItem } from "../log.ts";
import { ToolPanel } from "./ToolPanel.tsx";
import { Spinner } from "../ui/primitives.tsx";

/**
 * Markdown styles for assistant messages. The names are the tree-sitter
 * captures of @opentui/core's markdown grammars (assets/markdown{,_inline}/
 * highlights.scm): `markup.*` for the text, `punctuation.special` / `conceal`
 * for the `**`, `#` and backtick markers — dimmed, since they stay visible
 * (CONCEAL below). Unknown names resolve to `default`.
 */
function makeMdStyle() {
  return SyntaxStyle.fromStyles({
  default: { fg: theme.fg0 },
  "markup.strong": { fg: theme.fg0, bold: true },
  "markup.italic": { fg: theme.fg1, italic: true },
  "markup.strikethrough": { fg: theme.fg2 },
  "markup.heading": { fg: theme.accentSoft, bold: true },
  "markup.heading.1": { fg: theme.accentSoft, bold: true },
  "markup.heading.2": { fg: theme.accentSoft, bold: true },
  "markup.heading.3": { fg: theme.fg0, bold: true },
  "markup.heading.4": { fg: theme.fg0, bold: true },
  "markup.heading.5": { fg: theme.fg0, bold: true },
  "markup.heading.6": { fg: theme.fg0, bold: true },
  "markup.raw": { fg: theme.accentSoft },
  "markup.raw.block": { fg: theme.fg1 },
  "markup.link": { fg: theme.accentSoft, underline: true },
  "markup.link.url": { fg: theme.accentSoft, underline: true },
  "markup.link.label": { fg: theme.accentSoft },
  "markup.quote": { fg: theme.fg1, italic: true },
  "markup.list": { fg: theme.accent },
  "punctuation.special": { fg: theme.fg2 },
  "punctuation.delimiter": { fg: theme.fg2 },
  "character.special": { fg: theme.fg2 },
  conceal: { fg: theme.fg2 },
  "string.escape": { fg: theme.fg2 },
  label: { fg: theme.fg2 },
  markdown_inline: { fg: theme.fg0 },
  markdown_heading: { fg: theme.fg0, bold: true },
  markdown_strong: { fg: theme.fg0, bold: true },
  markdown_emphasis: { fg: theme.fg1, italic: true },
  markdown_code: { fg: theme.accentSoft },
  markdown_code_span: { fg: theme.accentSoft },
  markdown_link: { fg: theme.accentSoft, underline: true },
  markdown_block_quote: { fg: theme.fg1, italic: true },
  markdown_list: { fg: theme.fg0 },
  markdown_table: { fg: theme.fg1 },
  heading: { fg: theme.fg0, bold: true },
  strong: { fg: theme.fg0, bold: true },
  em: { fg: theme.fg1, italic: true },
  code: { fg: theme.accentSoft },
  link: { fg: theme.accentSoft, underline: true },
  blockquote: { fg: theme.fg1, italic: true },
  str: { fg: theme.success },
  string: { fg: theme.success },
  keyword: { fg: theme.accentSoft },
  comment: { fg: theme.fg2, italic: true },
  number: { fg: theme.warn },
  boolean: { fg: theme.warn },
  function: { fg: theme.fg0 },
  variable: { fg: theme.fg1 },
  default_highlight: { fg: theme.fg0 },
  });
}

/** One SyntaxStyle per theme (it is built from the live palette). */
let mdCache: { v: number; style: SyntaxStyle } | null = null;
function mdStyle(v: number): SyntaxStyle {
  if (!mdCache || mdCache.v !== v) mdCache = { v, style: makeMdStyle() };
  return mdCache.style;
}

/**
 * Markdown renders blank without a tree-sitter client (the parsers are WASM
 * assets shipped inside @opentui/core) — one client, created once, shared by
 * every message body and the live streaming block. Initialize fires now so the
 * worker is warm by the time the first reply streams in; cold-start otherwise
 * leaves the first message blank for a few hundred milliseconds.
 */
const treeSitter = getTreeSitterClient();
void treeSitter.initialize().catch(() => {});

function Role({ glyph, label, color }: { glyph: string; label: string; color: string }) {
  return (
    <text>
      <span fg={color}>{`${glyph} `}</span>
      <span fg={theme.fg2}>{label}</span>
    </text>
  );
}

/**
 * Markdown syntax is styled but NOT concealed. With conceal on, tree-sitter
 * reads any `[x]` as a shortcut link and hides the brackets, so code talk is
 * corrupted: `list[str]` rendered as "liststr", `arr[0]` as "arr0"; a backslash
 * escape doesn't help (it stays visible). Visible `**`/`#` markers are the
 * price of showing the model's text as written.
 */
const CONCEAL = false;

/** Settled assistant body — markdown with the theme's syntax palette. */
const AssistantBody = memo(function AssistantBody({ text }: { text: string }) {
  const v = useThemeVersion();
  return (
    <box paddingLeft={2} flexDirection="column">
      <markdown
        content={text}
        syntaxStyle={mdStyle(v)}
        treeSitterClient={treeSitter}
        fg={theme.fg0}
        conceal={CONCEAL}
        streaming={false}
      />
    </box>
  );
});

/** Built once per theme: a fresh object here would be a new prop on every
 *  streamed token, forcing the scrollbox to re-apply its style each frame. */
function scrollStyle() {
  return {
    rootOptions: { backgroundColor: theme.bg0 },
    viewportOptions: { backgroundColor: theme.bg0 },
    contentOptions: { backgroundColor: theme.bg0 },
  } as const;
}

/** One automatic-memory change, dim like the thought line:
 *    ✻ Remembered · Editor — VS Code  (was: Neovim)   /memory undo */
function MemoryItem({ item }: { item: Extract<LogItem, { kind: "memory" }> }) {
  const verb = item.op === "forget" ? "Forgot" : item.op === "undo" ? "Undid" : "Remembered";
  const value = item.op === "forget" ? "" : ` — ${item.after ?? "(removed)"}`;
  const was = item.before && item.op !== "undo" ? `  (was: ${item.before})` : "";
  return (
    <box marginTop={1}>
      <text>
        <span fg={theme.accentSoft}>{"✻ "}</span>
        <span fg={theme.fg2}>{`${verb} · ${item.topic}${value}${was}`}</span>
        {item.op !== "undo" ? <span fg={theme.border}>{"   /memory undo"}</span> : null}
      </text>
    </box>
  );
}

/** "✻ Thought for 12s" — click to read the reasoning (like Claude Code). */
function ThoughtItem({ seconds, text }: { seconds: number; text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <box marginTop={1} flexDirection="column" onMouseDown={() => setOpen((o) => !o)}>
      <text>
        <span fg={theme.fg2}>{`✻ Thought for ${seconds < 1 ? "<1" : Math.round(seconds)}s`}</span>
        <span fg={theme.border}>{open ? "  ▾" : "  ▸ click to expand"}</span>
      </text>
      {open ? (
        <box paddingLeft={2}>
          <text fg={theme.fg2}>{text.trim()}</text>
        </box>
      ) : null}
    </box>
  );
}

/** Memoised: streaming appends re-render the log every token, but a settled
 *  item never changes. */
const Item = memo(function Item({ item }: { item: LogItem }) {
  useThemeVersion();
  switch (item.kind) {
    case "system":
      return (
        <box marginTop={1}>
          <text>
            <span fg={item.error ? theme.error : theme.border}>{item.error ? "!" : "·"}</span>
            <span fg={item.error ? theme.error : theme.fg2}>{` ${item.text}`}</span>
          </text>
        </box>
      );
    case "user":
      return (
        <box marginTop={1} flexDirection="column">
          <Role glyph="›" label="YOU" color={theme.accent} />
          <box paddingLeft={2} flexDirection="column">
            {item.text ? <text fg={theme.fg1}>{item.text}</text> : null}
            {item.images?.length ? (
              <text fg={theme.accentSoft}>{item.images.map((n) => `▣ ${n}`).join("   ")}</text>
            ) : null}
          </box>
        </box>
      );
    case "assistant":
      return (
        <box marginTop={1} flexDirection="column">
          <Role glyph="‹" label="AIHUB" color={theme.fg1} />
          <AssistantBody text={item.text} />
        </box>
      );
    case "tool":
      return <ToolPanel item={item} />;
    case "thought":
      return <ThoughtItem seconds={item.seconds} text={item.text} />;
    case "memory":
      return <MemoryItem item={item} />;
  }
});

export function ChatLog({
  items,
  streamingText,
}: {
  items: LogItem[];
  streamingText: string;
}) {
  const v = useThemeVersion();
  const style = useMemo(scrollStyle, [v]);
  // Sticky bottom: follows new messages and streamed tokens while the view is
  // at the bottom, and stops following once the user scrolls up to read.
  // (A scrollToBottom() call used to live here — ScrollBox has no such method,
  // so the log never auto-scrolled.)
  return (
    <scrollbox
      stickyScroll
      stickyStart="bottom"
      flexGrow={1}
      paddingLeft={2}
      paddingRight={2}
      style={style}
    >
      {items.map((item, i) => (
        <Item key={i} item={item} />
      ))}
      {streamingText ? (
        <box marginTop={1} flexDirection="column">
          <text>
            <Spinner color={theme.accent} />
            <span fg={theme.fg2}>{" AIHUB"}</span>
          </text>
          <box paddingLeft={2} flexDirection="column">
            <markdown
              content={streamingText}
              syntaxStyle={mdStyle(v)}
              treeSitterClient={treeSitter}
              fg={theme.fg0}
              conceal={CONCEAL}
              streaming
            />
          </box>
        </box>
      ) : null}
    </scrollbox>
  );
}

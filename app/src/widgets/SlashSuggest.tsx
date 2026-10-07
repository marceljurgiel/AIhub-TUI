import { useRef } from "react";
import { theme, fit } from "../theme.ts";
import type { SlashCommand } from "../slash.ts";

const MAX_ROWS = 6;

/** Autocomplete popup shown above the input while typing a "/command".
 *  Presentational — navigation state is owned by ChatInput. A window of
 *  MAX_ROWS follows the highlight, so ↑↓ reach every command; the last line
 *  says how many are above / below. */
export function SlashSuggest({
  commands,
  highlight,
}: {
  commands: SlashCommand[];
  highlight: number;
}) {
  // Scroll only when the highlight leaves the window (wrap-around included).
  const start = useRef(0);
  if (commands.length === 0) return null;
  const maxStart = Math.max(0, commands.length - MAX_ROWS);
  if (highlight < start.current) start.current = highlight;
  if (highlight >= start.current + MAX_ROWS) start.current = highlight - MAX_ROWS + 1;
  start.current = Math.min(Math.max(0, start.current), maxStart);

  const rows = commands.slice(start.current, start.current + MAX_ROWS);
  const above = start.current;
  const below = commands.length - start.current - rows.length;
  // Descriptions line up in one column, like the other lists.
  const cmdW = Math.min(18, Math.max(...commands.map((c) => c.cmd.length)));

  return (
    <box
      border
      borderStyle="rounded"
      borderColor={theme.borderStrong}
      backgroundColor={theme.bg2}
      marginLeft={1}
      marginRight={1}
      flexDirection="column"
      flexShrink={0}
    >
      {rows.map((c, i) => {
        const active = start.current + i === highlight;
        return (
          <box key={c.cmd} backgroundColor={active ? theme.bg3 : undefined}>
            <text>
              <span fg={active ? theme.accent : theme.border}>{"▎"}</span>
              <span fg={active ? theme.fg0 : theme.fg1}>{` ${fit(c.cmd, cmdW).padEnd(cmdW)}`}</span>
              <span fg={theme.fg2}>{`   ${c.desc}`}</span>
            </text>
          </box>
        );
      })}
      {above || below ? (
        <text>
          <span fg={above ? theme.fg2 : theme.border}>{`  ↑ ${above} more`}</span>
          <span fg={theme.borderStrong}>{"  ·  "}</span>
          <span fg={below ? theme.fg2 : theme.border}>{`↓ ${below} more`}</span>
          <span fg={theme.border}>{`   ${highlight + 1}/${commands.length}`}</span>
        </text>
      ) : null}
    </box>
  );
}

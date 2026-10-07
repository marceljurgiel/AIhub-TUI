import { useTerminalDimensions } from "@opentui/react";
import { theme, fit } from "../theme.ts";
import { ModalShell } from "../ui/ModalShell.tsx";
import { SectionLabel, KeyHint } from "../ui/primitives.tsx";
import { ACTIONS, shortKey } from "../keymap/actions.ts";
import { SLASH_COMMANDS } from "../slash.ts";
import { useModalKeys } from "./modalKit.ts";

/** Reference card generated from the live action table + slash registry. */
export function HelpModal({ onClose }: { onClose: () => void }) {
  useModalKeys([{ key: "escape", run: onClose }]);
  const width = 78;
  const chords = ACTIONS.filter((a) => a.key);
  const slash = SLASH_COMMANDS;
  // Two chords per row keeps the left column shorter than the slash list.
  const pairs = chords.reduce<Array<typeof chords>>(
    (rows, a, i) => (i % 2 ? (rows[rows.length - 1]!.push(a), rows) : [...rows, [a]]),
    [],
  );
  const { height: termH } = useTerminalDimensions();
  // Shell 5 + top padding 1 + header 1 + the longer column; never taller than the screen.
  const height = Math.min(7 + Math.max(slash.length, pairs.length + 7), termH);

  return (
    <ModalShell title="Help" width={width} height={height} hints={[["esc", "close"]]}>
      <box flexDirection="row" flexGrow={1} paddingTop={1}>
        <box flexDirection="column" width={Math.floor(width / 2) - 1}>
          <SectionLabel label="keys" width={Math.floor(width / 2) - 2} />
          {pairs.map((pair) => (
            <text key={pair[0]!.id} flexShrink={0}>
              {pair.map((a) => (
                <span key={a.id}>
                  <span fg={theme.fg2}>{`  ${shortKey(a.key!).padEnd(5)}`}</span>
                  <span fg={theme.fg1}>{fit(a.label, 12).padEnd(12)}</span>
                </span>
              ))}
            </text>
          ))}
          <box marginTop={1} flexDirection="column" flexShrink={0}>
            <SectionLabel label="quick nav" width={Math.floor(width / 2) - 2} />
            <text fg={theme.fg2}>
              {`  tab (empty prompt) opens the menu:\n  ↑↓ choose, enter open, esc back;\n  letters jump straight there:`}
            </text>
            <text>
              <span fg={theme.fg2}>{"  "}</span>
              <KeyHint k="n" />
              <span fg={theme.fg1}>{` new   `}</span>
              <KeyHint k="m" />
              <span fg={theme.fg1}>{` models   `}</span>
              <KeyHint k="p" />
              <span fg={theme.fg1}>{` palette`}</span>
            </text>
          </box>
        </box>

        <box flexDirection="column" width={Math.ceil(width / 2) - 1}>
          <SectionLabel label="slash commands" width={Math.ceil(width / 2) - 2} />
          {slash.map((c) => (
            <text key={c.cmd} flexShrink={0}>
              <span fg={theme.accentSoft}>{`  ${fit(c.cmd, 14).padEnd(15)}`}</span>
              <span fg={theme.fg2}>{fit(c.desc, 20)}</span>
            </text>
          ))}
        </box>
      </box>
    </ModalShell>
  );
}

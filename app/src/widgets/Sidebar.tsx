import { memo } from "react";
import { useTerminalDimensions } from "@opentui/react";
import { theme, logoGradient, logoLines } from "../theme.ts";
import { useThemeVersion } from "../state/useTheme.ts";
import { SectionLabel } from "../ui/primitives.tsx";
import {
  SIDEBAR_ACTIONS,
  SIDEBAR_GROUPS,
  shortKey,
  type ActionId,
  type ActionSpec,
} from "../keymap/actions.ts";

export const SIDEBAR_WIDTH = 40;
/** Inside the cards: sidebar − 2×2 margin − 2 border. */
const CARD_INNER = SIDEBAR_WIDTH - 6;

/** One nav row. Memoised: the sidebar re-renders on every streamed token, and
 *  nothing about a row changes unless its own active state does. The open
 *  panel's row gets the same treatment as a selected modal row (ListRow):
 *  surface lift + accent marker — no geometry change. */
const NavRow = memo(function NavRow({
  spec,
  active,
  onAction,
}: {
  spec: ActionSpec;
  active: boolean;
  onAction: (action: ActionId) => void;
}) {
  useThemeVersion();
  return (
    <box
      flexDirection="row"
      justifyContent="space-between"
      paddingRight={1}
      flexShrink={0}
      backgroundColor={active ? theme.bg3 : undefined}
      onMouseDown={() => onAction(spec.id)}
    >
      <text>
        <span fg={theme.accent}>{active ? "▎" : " "}</span>
        <span fg={active ? theme.accent : theme.fg2}>{`${spec.icon ?? "·"}  `}</span>
        <span fg={active ? theme.fg0 : theme.fg1}>{spec.label}</span>
      </text>
      {spec.nav ? (
        // A keycap, like the footer hints — on the lifted row it sinks instead.
        <text>
          <span fg={active ? theme.accentSoft : theme.fg2} bg={active ? theme.bg2 : theme.bg3}>
            {` ${shortKey(spec.nav)} `}
          </span>
        </text>
      ) : null}
    </box>
  );
});

/** The nav, grouped, in a card that matches the model card above it. */
function NavCard({
  activeAction,
  onAction,
  headers,
  tight,
  bare,
  focused,
}: {
  activeAction: ActionId | null;
  onAction: (action: ActionId) => void;
  headers: boolean;
  tight: boolean;
  /** No border: a very short terminal needs those two rows for items. */
  bare: boolean;
  /** The menu has the keyboard (Tab from an empty prompt): accent ring. */
  focused: boolean;
}) {
  return (
    <box
      marginLeft={2}
      marginRight={2}
      marginTop={tight ? 0 : 1}
      {...(bare
        ? { paddingLeft: 1, paddingRight: 1 }
        : { border: true, borderStyle: "rounded" as const, borderColor: focused ? theme.accent : theme.border })}
      backgroundColor={theme.bg2}
      flexDirection="column"
      flexShrink={0}
    >
      {SIDEBAR_GROUPS.map((g) => (
        <box key={g.id} flexDirection="column" flexShrink={0}>
          {headers ? (
            <box paddingLeft={1} flexShrink={0}>
              <SectionLabel label={g.label} width={CARD_INNER - 1} />
            </box>
          ) : null}
          {SIDEBAR_ACTIONS.filter((a) => a.group === g.id).map((spec) => (
            <NavRow key={spec.id} spec={spec} active={spec.id === activeAction} onAction={onAction} />
          ))}
        </box>
      ))}
    </box>
  );
}

/** The signature element: the model card. Connection state, model id and
 *  context size read as one instrument panel; click opens the picker. */
function ModelCard({
  model,
  online,
  ctxK,
  onAction,
  tight,
}: {
  model: string | null;
  online: boolean | null;
  ctxK: number;
  onAction: (a: ActionId) => void;
  tight: boolean;
}) {
  const live = online && !!model;
  const inner = SIDEBAR_WIDTH - 6;
  const name = model
    ? model.length > inner - 14
      ? model.slice(0, inner - 15) + "…"
      : model
    : "choose a model";
  // The state is said in a word, coloured — no status dot.
  const tone = live ? theme.success : online ? theme.warn : online === null ? theme.fg2 : theme.error;
  const word = online ? "CONNECTED" : online === null ? "CONNECTING" : "OFFLINE";

  // Very short terminals: one line, so the whole nav still fits below.
  if (tight)
    return (
      <box marginLeft={2} marginRight={2} flexShrink={0} height={1} onMouseDown={() => onAction("model_picker")}>
        <text>
          {/* One line has no room for the word unless something is wrong. */}
          {live ? null : <span fg={tone}>{`${word} `}</span>}
          <span fg={model ? theme.accentSoft : theme.fg2}>{name}</span>
          <span fg={theme.borderStrong}>{" · "}</span>
          <span fg={live ? theme.fg1 : theme.fg2}>{`${ctxK}K`}</span>
        </text>
      </box>
    );

  return (
    <box
      marginLeft={2}
      marginRight={2}
      marginTop={1}
      flexShrink={0}
      border
      borderStyle="rounded"
      borderColor={live ? theme.borderStrong : theme.border}
      backgroundColor={theme.bg2}
      paddingLeft={1}
      paddingRight={1}
      onMouseDown={() => onAction("model_picker")}
    >
      <text>
        {/* Connected but no model yet (still loading, or none installed) is
            not "offline": yellow word, and the line below says what to do. */}
        <span fg={tone}>{word}</span>
        <span fg={theme.borderStrong}>{" · "}</span>
        <span fg={live ? theme.fg1 : theme.fg2}>{`${ctxK}K CTX`}</span>
      </text>
      <text fg={model ? theme.accentSoft : theme.fg2}>{name}</text>
    </box>
  );
}

export function Sidebar({
  model,
  online,
  ctxK,
  version,
  coreVersion,
  activeAction,
  onAction,
  menuFocused,
}: {
  model: string | null;
  online: boolean | null;
  ctxK: number;
  version: string;
  /** The Python engine's version — different from this UI's, so label both. */
  coreVersion?: string;
  /** The highlighted row: the menu's cursor while it has the keyboard. */
  activeAction: ActionId | null;
  onAction: (action: ActionId) => void;
  menuFocused?: boolean;
}) {
  // The column below the header and status bars. Short terminals give up
  // decoration in order — figlet logo → one-line wordmark → group headers →
  // wordmark → the boxed model card (one line instead) — so the nav itself
  // is never clipped.
  const { height } = useTerminalDimensions();
  const rows = height - 2;
  const NAV = SIDEBAR_ACTIONS.length + 2;          // rows + card borders
  const level =
    rows >= 6 + 5 + NAV + 4 + 1 ? 0 :               // logo, headers
    rows >= 2 + 5 + NAV + 4 + 1 ? 1 :               // wordmark, headers
    rows >= 2 + 5 + NAV + 1 + 1 ? 2 :               // wordmark
    rows >= 5 + NAV + 1 ? 3 :                       // boxed model card + nav
    4;                                              // one-line model card + nav
  const headers = level <= 1;
  const tight = level === 4;
  // The version line goes before the boxed card does (80×24 with every item).
  const showVersion = !tight && (level < 3 || rows >= 5 + NAV + 1 + 1);
  // Shorter still: the nav loses its card border rather than its last rows.
  const bare = tight && rows < 1 + NAV;

  return (
    <box width={SIDEBAR_WIDTH} height="100%" backgroundColor={theme.bg1} flexDirection="column">
      {level === 0 ? (
        // Logo — the figlet wordmark from the Textual edition, one gradient
        // stop per row. Fixed rows rather than <ascii-font> so the mark is
        // identical in both front-ends.
        <box paddingTop={1} paddingLeft={2} flexDirection="column" flexShrink={0}>
          {logoLines.map((line, i) => (
            <text key={i} fg={logoGradient[i % logoGradient.length]}>
              {line}
            </text>
          ))}
        </box>
      ) : level <= 2 ? (
        <box paddingTop={1} paddingLeft={2} flexShrink={0}>
          <text>
            <span fg={theme.accent}>{"◆ "}</span>
            <span fg={logoGradient[0]}>{"AI"}</span>
            <span fg={theme.accentSoft}>{"hub"}</span>
          </text>
        </box>
      ) : null}

      <ModelCard model={model} online={online} ctxK={ctxK} onAction={onAction} tight={tight} />

      {/* Nav — driven by the shared action table, so the labels and shortcut
          letters shown here are the ones the keymap actually binds. */}
      <NavCard
        activeAction={activeAction}
        onAction={onAction}
        headers={headers}
        tight={tight}
        bare={bare}
        focused={!!menuFocused}
      />

      <box flexGrow={1} />
      {!showVersion ? null : (
        <box paddingLeft={2} flexShrink={0}>
          <text fg={theme.fg2}>{`aihub v${version}${coreVersion ? `  ·  core ${coreVersion}` : ""}`}</text>
        </box>
      )}
    </box>
  );
}

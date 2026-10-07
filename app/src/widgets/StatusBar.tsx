import { useEffect, useState } from "react";
import { theme, usageColor, tpsColor, utilColor, humanTokens, fit } from "../theme.ts";
import { Dot, Spinner } from "../ui/primitives.tsx";
import type { SessionState } from "../state/SessionContext.tsx";

function sessionTitle(state: SessionState): string {
  const firstUser = state.messages.find((m) => m.role === "user");
  if (!firstUser) return "new session";
  // A /skill message carries the skill's instructions; title it by the command.
  const raw = String(firstUser.content);
  const skill = /^Use the "([^"]+)" skill for this\./.exec(raw);
  const task = skill ? /\n\nTask: ([^]*)$/.exec(raw)?.[1] ?? "" : "";
  const t = (skill ? `/skill ${skill[1]} ${task}`.trim() : raw).replace(/\n/g, " ");
  return t.length > 42 ? t.slice(0, 41) + "…" : t;
}

const SEP = () => <span fg={theme.borderStrong}>{"  ·  "}</span>;

/** Top header bar — mirrors tui/widgets/status_bar.py StatusBar. */
export function Header({ state }: { state: SessionState }) {
  const title = sessionTitle(state);
  const msgCount = state.messages.filter((m) => m.role === "user" || m.role === "assistant").length;

  const statusNode = state.streaming ? (
    <span fg={theme.warn}>
      <Spinner color={theme.warn} />
      {" streaming"}
    </span>
  ) : state.mode === "agent" ? (
    <span fg={theme.accent}>{`agent ${state.agentName} · ${state.agentSubmode}`}</span>
  ) : title === "new session" ? null : (
    <span fg={theme.fg2}>active session</span>
  );

  const ctxFrac = state.ctxMax > 0 ? state.ctxUsed / state.ctxMax : 0;
  const showGpu = state.vramTotalGb > 0 && state.modelOnGpu !== false;

  return (
    <box
      height={1}
      backgroundColor={theme.bg1}
      flexDirection="row"
      justifyContent="space-between"
      paddingLeft={2}
      paddingRight={2}
      flexShrink={0}
    >
      <text>
        <Dot color={theme.accent} />
        <span fg={theme.fg0}>{` ${title}`}</span>
        {statusNode ? (
          <>
            <SEP />
            {statusNode}
          </>
        ) : null}
        <SEP />
        <span fg={theme.fg2}>{`${msgCount} ${msgCount === 1 ? "message" : "messages"}`}</span>
      </text>
      <text>
        {state.tps > 0 ? (
          <>
            <span fg={tpsColor(state.tps)}>{`${state.tps} tok/s`}</span>
            <SEP />
          </>
        ) : null}
        <span fg={theme.fg2}>ctx </span>
        <span fg={usageColor(ctxFrac)}>{`${humanTokens(state.ctxUsed)}/${humanTokens(state.ctxMax)}`}</span>
        <SEP />
        {showGpu ? (
          <>
            <span fg={theme.fg2}>GPU </span>
            <span fg={utilColor(state.gpuUtil < 0 ? 0 : state.gpuUtil)}>
              {state.gpuUtil < 0 ? "· " : `${Math.round(state.gpuUtil)}% `}
            </span>
            <span fg={theme.fg1}>{`${state.vramUsedGb.toFixed(1)}/${state.vramTotalGb.toFixed(1)}G`}</span>
          </>
        ) : (
          <>
            <span fg={theme.fg2}>CPU </span>
            <span fg={utilColor(state.cpuPercent)}>{`${Math.round(state.cpuPercent)}%`}</span>
          </>
        )}
      </text>
    </box>
  );
}

/** Bottom bar: the session switches, each clickable — the header and the
 *  sidebar already show the model, speed, context and agent. */
export function Footer({
  state,
  onToggleMemory,
  onToggleTools,
  onTemperature,
}: {
  state: SessionState;
  onToggleMemory?: () => void;
  onToggleTools?: () => void;
  onTemperature?: () => void;
}) {
  return (
    <box height={1} backgroundColor={theme.bg1} flexDirection="row" paddingLeft={2} paddingRight={1} flexShrink={0}>
      <text onMouseDown={onToggleMemory}>
        <span fg={state.memoryEnabled ? theme.success : theme.fg2}>{`mem ${state.memoryEnabled ? "✓" : "·"}`}</span>
      </text>
      <text>{"  "}</text>
      <text onMouseDown={onToggleTools}>
        <span fg={state.toolsEnabled ? theme.success : theme.fg2}>{`tools ${state.toolsEnabled ? "✓" : "·"}`}</span>
      </text>
      <text fg={theme.borderStrong}>{"  ·  "}</text>
      <text onMouseDown={onTemperature}>
        <span fg={theme.fg1}>{`T ${state.temperature.toFixed(1)}`}</span>
      </text>
      {state.knowledge.length ? (
        <>
          <text fg={theme.borderStrong}>{"  ·  "}</text>
          {/* Knowledge bases on in this chat (/kb). */}
          <text fg={theme.accentSoft}>{fit(`¶ ${state.knowledge.join(",")}`, 9)}</text>
        </>
      ) : null}
    </box>
  );
}


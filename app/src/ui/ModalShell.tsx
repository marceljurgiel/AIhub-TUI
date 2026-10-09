import { type ReactNode } from "react";
import { useTerminalDimensions } from "@opentui/react";
import { theme } from "../theme.ts";
import { Hints } from "./primitives.tsx";

/**
 * Shared modal frame: centered rounded panel with a title bar and a footer
 * hint strip. Every modal composes this, so the whole app has one modal
 * silhouette. Keyboard handling stays in each modal (they register a
 * LAYER.modal keymap); the shell only draws.
 */
export function ModalShell({
  title,
  width,
  height,
  hints = [],
  children,
}: {
  title: string;
  width: number;
  /** Total panel height including borders; omit to hug content. */
  height?: number;
  hints?: Array<[string, string]>;
  children: ReactNode;
}) {
  // A window never outgrows the terminal: a fixed height on a short screen
  // would push its bottom border and hints out of view.
  const term = useTerminalDimensions();
  width = Math.min(width, term.width);
  if (height !== undefined) height = Math.min(height, term.height);
  return (
    <box
      width={width}
      height={height}
      flexDirection="column"
      border
      borderStyle="rounded"
      borderColor={theme.borderStrong}
      backgroundColor={theme.bg1}
    >
      {/* title bar */}
      <box
        flexDirection="row"
        justifyContent="space-between"
        paddingLeft={1}
        paddingRight={1}
        flexShrink={0}
      >
        <text>
          <span fg={theme.accent}>◆ </span>
          <span fg={theme.fg0}>{title}</span>
        </text>
        <text fg={theme.fg2}>esc close</text>
      </box>
      <box flexShrink={0} paddingLeft={1} paddingRight={1}>
        <text fg={theme.borderStrong}>{"─".repeat(width - 4)}</text>
      </box>

      {/* body — clipped, so content that doesn't fit can never paint over
          the hint bar or outside the frame */}
      <box flexDirection="column" flexGrow={1} flexShrink={1} overflow="hidden" paddingLeft={1} paddingRight={1}>
        {/* Never shrinks below its content: on a short terminal rows are cut
            at the bottom instead of being squeezed onto each other. */}
        <box flexDirection="column" flexGrow={1} flexShrink={0}>
          {children}
        </box>
      </box>

      {/* footer hints */}
      {hints.length ? (
        <box flexShrink={0} paddingLeft={1} paddingRight={1}>
          <Hints items={hints} />
        </box>
      ) : null}
    </box>
  );
}

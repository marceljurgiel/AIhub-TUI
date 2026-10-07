/**
 * AIhub design tokens — shared with the Textual edition's app.tcss so both
 * front-ends speak one visual language.
 *
 * Surfaces climb bg0 → bg3 as elements get "closer" to the reader:
 *   bg0  canvas (chat log, screen backdrop)
 *   bg1  chrome (sidebar, bars, modal panels)
 *   bg2  raised (inputs, tool panels, hover rows)
 *   bg3  selected / active rows
 * Purple is reserved for interactivity — focus rings, selections, brand marks.
 * Green/amber/red are semantic only (connection, speed, errors), never decor.
 */
export const theme = {
  bg0: "#0b0b0f", // canvas
  bg1: "#131318", // chrome
  bg2: "#1b1b22", // raised
  bg3: "#24242d", // selected / active

  border: "#23232b", // hairline rules that shouldn't compete with content
  borderStrong: "#33333e", // dividers that must stay readable

  fg0: "#e6e6e6", // primary text
  fg1: "#a8a8b0", // secondary text
  fg2: "#6b6b73", // dim / muted text

  accent: "#a855f7", // purple — the single brand accent
  accentSoft: "#c084fc", // lighter accent (logo gradient top, hover)

  success: "#22c55e",
  warn: "#ffb454",
  error: "#ff6e6e",
} as const;

/** Vertical gradient used by the sidebar logo. */
export const logoGradient = ["#e9d5ff", "#c084fc", "#a855f7", "#9333ea", "#7e22ce"];

/**
 * The wordmark, carried over verbatim from the Textual edition
 * (`aihub/tui/widgets/sidebar.py`) so both front-ends show the same brand:
 * figlet "standard", one gradient stop per row.
 *
 * Widest row is 37 cells, which clears the 42-cell sidebar with its 2-cell
 * left padding. Keep it that way — `<ascii-font>` would re-flow on resize,
 * these fixed rows will simply clip.
 */
export const logoLines = [
  "  ,---.  ,--.,--.             ,--.  ",
  " /  O  \\ |  ||  ,---. ,--.,--.|  |-.",
  "|  .-.  ||  ||  .-.  ||  ||  || .-. '",
  "|  | |  ||  ||  | |  |'  ''  '| `-' |",
  "`--' `--'`--'`--' `--' `----'  `---' ",
];

// ── Semantic helpers ─────────────────────────────────────────────────────────

/** Color a context-fill percentage: green < 60%, amber < 85%, red otherwise. */
export function usageColor(fraction: number): string {
  if (fraction < 0.6) return theme.success;
  if (fraction < 0.85) return theme.warn;
  return theme.error;
}

/** Color a tokens/sec value: green >= 20, amber >= 8, red below (≈ CPU-slow). */
export function tpsColor(tps: number): string {
  if (tps >= 20) return theme.success;
  if (tps >= 8) return theme.warn;
  return theme.error;
}

/** Color a 0-100 utilization percentage. */
export function utilColor(pct: number): string {
  if (pct < 60) return theme.success;
  if (pct < 85) return theme.warn;
  return theme.error;
}

/** Humanize a token count: 1500 -> "1.5k", 32000 -> "32k". */
export function humanTokens(n: number): string {
  if (!n || n <= 0) return "0";
  if (n < 1000) return String(Math.round(n));
  const k = n / 1000;
  return k >= 10 ? `${Math.round(k)}k` : `${k.toFixed(1)}k`;
}

/** Humanize gigabytes: 0 -> "—", 1.25 -> "1.3 GB". */
export function humanGb(n: number): string {
  if (!n || n <= 0) return "—";
  return `${n >= 10 ? Math.round(n) : n.toFixed(1)} GB`;
}

/** Truncate with ellipsis, keeping the tail anchored at max width. */
export function fit(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, Math.max(1, max - 1)) + "…";
}

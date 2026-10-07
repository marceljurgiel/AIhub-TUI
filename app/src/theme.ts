/**
 * AIhub design tokens — shared with the Textual edition's app.tcss so both
 * front-ends speak one visual language.
 *
 * Surfaces climb bg0 → bg3 as elements get "closer" to the reader:
 *   bg0  canvas (chat log, screen backdrop)
 *   bg1  chrome (sidebar, bars, modal panels)
 *   bg2  raised (inputs, tool panels, hover rows)
 *   bg3  selected / active rows
 * The accent (purple in the default theme) is reserved for interactivity —
 * focus rings, selections, brand marks. Themes and accents: see THEMES below.
 * Green/amber/red are semantic only (connection, speed, errors), never decor.
 */
export interface Palette {
  bg0: string; // canvas
  bg1: string; // chrome
  bg2: string; // raised
  bg3: string; // selected / active
  border: string; // hairline rules that shouldn't compete with content
  borderStrong: string; // dividers that must stay readable
  fg0: string; // primary text
  fg1: string; // secondary text
  fg2: string; // dim / muted text
  accent: string; // the single brand accent
  accentSoft: string; // lighter accent (logo gradient top, hover)
  success: string;
  warn: string;
  error: string;
}

/** Built-in themes. Each brings its own accent; an accent choice overrides it. */
export const THEMES: Record<string, { label: string; palette: Palette }> = {
  aihub: {
    label: "AIhub",
    palette: {
      bg0: "#0b0b0f", bg1: "#131318", bg2: "#1b1b22", bg3: "#24242d",
      border: "#23232b", borderStrong: "#33333e",
      fg0: "#e6e6e6", fg1: "#a8a8b0", fg2: "#6b6b73",
      accent: "#a855f7", accentSoft: "#c084fc",
      success: "#22c55e", warn: "#ffb454", error: "#ff6e6e",
    },
  },
  "tokyo-night": {
    label: "Tokyo Night",
    palette: {
      bg0: "#16161e", bg1: "#1a1b26", bg2: "#24283b", bg3: "#2f334d",
      border: "#24283b", borderStrong: "#3b4261",
      fg0: "#c0caf5", fg1: "#a9b1d6", fg2: "#565f89",
      accent: "#7aa2f7", accentSoft: "#bb9af7",
      success: "#9ece6a", warn: "#e0af68", error: "#f7768e",
    },
  },
  catppuccin: {
    label: "Catppuccin",
    palette: {
      bg0: "#11111b", bg1: "#181825", bg2: "#1e1e2e", bg3: "#313244",
      border: "#313244", borderStrong: "#45475a",
      fg0: "#cdd6f4", fg1: "#bac2de", fg2: "#6c7086",
      accent: "#cba6f7", accentSoft: "#f5c2e7",
      success: "#a6e3a1", warn: "#f9e2af", error: "#f38ba8",
    },
  },
  dracula: {
    label: "Dracula",
    palette: {
      bg0: "#1e1f29", bg1: "#282a36", bg2: "#313341", bg3: "#44475a",
      border: "#343746", borderStrong: "#44475a",
      fg0: "#f8f8f2", fg1: "#c5c8d6", fg2: "#6272a4",
      accent: "#bd93f9", accentSoft: "#ff79c6",
      success: "#50fa7b", warn: "#f1fa8c", error: "#ff5555",
    },
  },
  nord: {
    label: "Nord",
    palette: {
      bg0: "#242933", bg1: "#2e3440", bg2: "#3b4252", bg3: "#434c5e",
      border: "#3b4252", borderStrong: "#4c566a",
      fg0: "#eceff4", fg1: "#d8dee9", fg2: "#7b88a1",
      accent: "#88c0d0", accentSoft: "#8fbcbb",
      success: "#a3be8c", warn: "#ebcb8b", error: "#bf616a",
    },
  },
  gruvbox: {
    label: "Gruvbox",
    palette: {
      bg0: "#1d2021", bg1: "#282828", bg2: "#32302f", bg3: "#3c3836",
      border: "#32302f", borderStrong: "#504945",
      fg0: "#ebdbb2", fg1: "#bdae93", fg2: "#7c6f64",
      accent: "#fe8019", accentSoft: "#fabd2f",
      success: "#b8bb26", warn: "#fabd2f", error: "#fb4934",
    },
  },
  light: {
    label: "Light",
    palette: {
      bg0: "#fafafa", bg1: "#f0f0f3", bg2: "#e6e6eb", bg3: "#dadae2",
      border: "#d4d4dc", borderStrong: "#b8b8c4",
      fg0: "#1f1f24", fg1: "#4a4a55", fg2: "#8a8a95",
      accent: "#7c3aed", accentSoft: "#9333ea",
      success: "#15803d", warn: "#b45309", error: "#dc2626",
    },
  },
};

/** Accent colours that can replace a theme's own ("" = the theme's). */
export const ACCENTS: Record<string, { label: string; accent: string; accentSoft: string }> = {
  purple: { label: "Purple", accent: "#a855f7", accentSoft: "#c084fc" },
  blue: { label: "Blue", accent: "#3b82f6", accentSoft: "#60a5fa" },
  cyan: { label: "Cyan", accent: "#06b6d4", accentSoft: "#22d3ee" },
  green: { label: "Green", accent: "#10b981", accentSoft: "#34d399" },
  amber: { label: "Amber", accent: "#f59e0b", accentSoft: "#fbbf24" },
  orange: { label: "Orange", accent: "#f97316", accentSoft: "#fb923c" },
  pink: { label: "Pink", accent: "#ec4899", accentSoft: "#f472b6" },
  red: { label: "Red", accent: "#ef4444", accentSoft: "#f87171" },
};

export const DEFAULT_THEME = "aihub";

/**
 * The live palette. Components read `theme.x` while rendering, so switching
 * themes mutates this object in place and re-renders (see useThemeVersion).
 */
export const theme: Palette = { ...THEMES[DEFAULT_THEME]!.palette };

/** Vertical gradient used by the sidebar logo, derived from the accent. */
export const logoGradient: string[] = [];

/** What is applied now: theme id and accent id ("" = the theme's own). */
export const activeTheme = { name: DEFAULT_THEME, accent: "" };

function mix(hex: string, to: string, amount: number): string {
  const a = parseInt(hex.slice(1), 16);
  const b = parseInt(to.slice(1), 16);
  const ch = (shift: number) => {
    const x = (a >> shift) & 255;
    const y = (b >> shift) & 255;
    return Math.round(x + (y - x) * amount);
  };
  return "#" + [16, 8, 0].map((sh) => ch(sh).toString(16).padStart(2, "0")).join("");
}

function gradientFor(accent: string, soft: string): string[] {
  return [mix(accent, "#ffffff", 0.7), soft, accent, mix(accent, "#000000", 0.15), mix(accent, "#000000", 0.3)];
}

let version = 0;
const listeners = new Set<() => void>();

/** Switch theme and accent everywhere at once. Unknown names fall back to
 *  the defaults, so a stale config.yaml can't break the app. */
export function applyTheme(name?: string, accent?: string): void {
  const id = name && THEMES[name] ? name : DEFAULT_THEME;
  const acc = accent && ACCENTS[accent] ? accent : "";
  Object.assign(theme, THEMES[id]!.palette);
  if (acc) {
    theme.accent = ACCENTS[acc]!.accent;
    theme.accentSoft = ACCENTS[acc]!.accentSoft;
  }
  logoGradient.splice(0, logoGradient.length, ...gradientFor(theme.accent, theme.accentSoft));
  activeTheme.name = id;
  activeTheme.accent = acc;
  version++;
  for (const fn of listeners) fn();
}

export function subscribeTheme(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function themeVersion(): number {
  return version;
}

applyTheme(DEFAULT_THEME);

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

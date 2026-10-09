/**
 * Every user-facing action, its label, and how it is reached.
 *
 * This table is the single source of truth for four things that drifted apart
 * in the Textual app: the keymap layers, the sidebar nav list, the `/help`
 * output, and (Phase 4) the command palette. Adding an action here is enough
 * to make it bindable, navigable, and documented.
 */
export type ActionId =
  | "new_chat"
  | "agent"
  | "schedule"
  | "skills"
  | "mcp"
  | "model_picker"
  | "history"
  | "memory"
  | "knowledge"
  | "hardware"
  | "settings"
  | "command_palette"
  | "help"
  | "clear_chat"
  | "save_session"
  | "toggle_tools"
  | "temperature"
  | "theme"
  | "terminal"
  | "terminal_close"
  | "cancel_stream"
  | "quit";

export interface ActionSpec {
  id: ActionId;
  label: string;
  /** Chord that fires even while the chat input has focus (keymap "global"). */
  key?: string;
  /** Extra chords bound to the same action but not advertised in help. */
  altKeys?: string[];
  /** Bare letter, live only when no text field is focused (keymap "nav"). */
  nav?: string;
  /** Appears in the sidebar nav, in declaration order. */
  sidebar?: boolean;
  /** Sidebar section and glyph (single-width characters only). */
  group?: "chat" | "models" | "system";
  icon?: string;
}

export const SIDEBAR_GROUPS: ReadonlyArray<{ id: NonNullable<ActionSpec["group"]>; label: string }> = [
  { id: "chat", label: "chat" },
  { id: "models", label: "models" },
  { id: "system", label: "system" },
];

export const ACTIONS: readonly ActionSpec[] = [
  { id: "new_chat", label: "New Chat", key: "ctrl+n", nav: "n", sidebar: true, group: "chat", icon: "+" },
  { id: "agent", label: "Agent", key: "ctrl+g", nav: "a", sidebar: true, group: "chat", icon: "◇" },
  { id: "schedule", label: "Schedule", key: "f7", nav: "j", sidebar: true, group: "chat", icon: "○" },
  { id: "skills", label: "Skills", key: "f4", nav: "k", sidebar: true, group: "chat", icon: "✦" },
  { id: "model_picker", label: "Models", key: "ctrl+o", nav: "m", sidebar: true, group: "models", icon: "◆" },
  { id: "history", label: "History", key: "ctrl+r", nav: "h", sidebar: true, group: "models", icon: "↺" },
  { id: "memory", label: "Memory", key: "ctrl+e", nav: "e", sidebar: true, group: "models", icon: "◉" },
  { id: "knowledge", label: "Knowledge", key: "f6", nav: "b", sidebar: true, group: "models", icon: "¶" },
  { id: "mcp", label: "Connections", key: "f5", nav: "c", sidebar: true, group: "system", icon: "⇄" },
  { id: "hardware", label: "Hardware", key: "ctrl+b", nav: "w", sidebar: true, group: "system", icon: "▣" },
  // F8, the palette, help and /terminal — not the sidebar: one more row there
  // costs the logo at 34 rows and the model card's frame at 24.
  { id: "terminal", label: "Terminal", key: "f8" },
  // Ctrl+, cannot be encoded by a normal terminal — the byte it produces is
  // Ctrl+\ (0x1c), so it arrives as name "\\". F3 is the chord that actually
  // works; ctrl+, is kept as an alias for terminals running the Kitty keyboard
  // protocol, which can disambiguate it.
  { id: "settings", label: "Settings", key: "f3", altKeys: ["ctrl+,"], nav: "s", sidebar: true, group: "system", icon: "≡" },
  { id: "theme", label: "Theme", key: "f2", nav: "t", sidebar: true, group: "system", icon: "▒" },
  { id: "command_palette", label: "Palette", key: "ctrl+p", nav: "p", sidebar: true, group: "system", icon: "⌘" },
  { id: "help", label: "Help", key: "f1", nav: "?", sidebar: true, group: "system", icon: "?" },
  { id: "clear_chat", label: "Clear chat", key: "ctrl+l" },
  { id: "save_session", label: "Save session", key: "ctrl+s" },
  { id: "toggle_tools", label: "Toggle tools", key: "ctrl+t" },
  { id: "temperature", label: "Temperature" },
  { id: "terminal_close", label: "Close terminal" },
  { id: "cancel_stream", label: "Cancel stream", key: "escape" },
  { id: "quit", label: "Quit", key: "ctrl+q" },
];

export const SIDEBAR_ACTIONS = ACTIONS.filter((a) => a.sidebar);

/** "ctrl+o" → "^O", "f1" → "F1", "escape" → "Esc" — status-bar shorthand. */
export function shortKey(key: string): string {
  if (key === "escape") return "Esc";
  if (/^f\d+$/.test(key)) return key.toUpperCase();
  const m = /^ctrl\+(.+)$/.exec(key);
  if (m) return "^" + (m[1]!.length === 1 ? m[1]!.toUpperCase() : m[1]!);
  return key.length === 1 ? key.toUpperCase() : key;
}

/** The `/help` body, generated so it can never contradict the live bindings. */
export function helpText(slashLines: string): string {
  const chords = ACTIONS.filter((a) => a.key)
    .map((a) => `${shortKey(a.key!)} ${a.label}`)
    .join(" · ");
  const nav = ACTIONS.filter((a) => a.nav)
    .map((a) => `${a.nav} ${a.label.toLowerCase()}`)
    .join(" · ");
  return `Keys: ${chords}\nQuick nav (input unfocused): ${nav}\n${slashLines}`;
}

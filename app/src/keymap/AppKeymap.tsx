import { useMemo, useRef, type ReactNode } from "react";
import { useRenderer } from "@opentui/react";
import { createDefaultOpenTuiKeymap } from "@opentui/keymap/opentui";
import { KeymapProvider, useBindings } from "@opentui/keymap/react";
import {
  readClipboard as defaultReadClipboard,
  clipboardHasImage as defaultHasImage,
  imagePaste,
  pasteInto,
} from "../clipboard.ts";
import { debugLog } from "../bridge/client.ts";

/**
 * Owns the app's single `Keymap` and hands it to `@opentui/keymap/react`.
 *
 * The keymap is built from `useRenderer()` rather than at module scope so the
 * same tree works under a real terminal renderer and under `testRender`'s
 * headless one. `createDefaultOpenTuiKeymap` brings the `enabled` and
 * `metadata` layer fields the layers below rely on.
 *
 * The keymap host *prepends* itself to the renderer's keypress listeners, so a
 * bound chord is seen before the focused input consumes it. That is what lets
 * Ctrl+O work while the user is mid-word in the chat box, and it is the
 * framework equivalent of Textual's `priority=True` bindings.
 */
export function AppKeymapProvider({
  children,
  readClipboard = defaultReadClipboard,
  clipboardHasImage = defaultHasImage,
}: {
  children: ReactNode;
  /** Injectable for tests. */
  readClipboard?: () => Promise<string>;
  clipboardHasImage?: () => Promise<boolean>;
}) {
  const renderer = useRenderer();
  const keymap = useMemo(() => createDefaultOpenTuiKeymap(renderer), [renderer]);
  return (
    <KeymapProvider keymap={keymap}>
      <FieldShortcuts read={readClipboard} hasImage={clipboardHasImage} />
      {children}
    </KeymapProvider>
  );
}

/**
 * Text-field shortcuts that work in every field — chat box, settings, model
 * filter, palette, memory editor — above every other layer so they work inside
 * modals too; with no field focused they do nothing.
 *   Ctrl+V  paste the system clipboard
 *   Ctrl+A  select all (OpenTUI's default is emacs line-home; Home still does that)
 */
function FieldShortcuts({ read, hasImage }: { read: () => Promise<string>; hasImage: () => Promise<boolean> }) {
  const renderer = useRenderer();
  const readRef = useRef(read);
  readRef.current = read;
  const hasImageRef = useRef(hasImage);
  hasImageRef.current = hasImage;
  useBindings(
    () => ({
      priority: LAYER.clipboard,
      commands: [
        {
          name: "clipboard.paste",
          run: () => {
            // Capture the target now: focus may move while the clipboard is read.
            const target = renderer.currentFocusedRenderable;
            if (!target) return;
            // An image in the clipboard goes to the chat as an attachment
            // (only the chat prompt takes one); otherwise paste text.
            hasImageRef
              .current()
              .catch(() => false)
              .then((image) => {
                if (image && imagePaste.handler?.()) return;
                return readRef.current().then((text) => {
                  pasteInto(target, text);
                });
              })
              .catch((e) => debugLog(`Ctrl+V paste failed: ${(e as Error).message || e}`));
          },
        },
      ],
      bindings: [{ key: "ctrl+v", cmd: "clipboard.paste" }],
    }),
    [renderer],
  );
  // Ctrl+A only where there is something to select: in the terminal panel it
  // is the shell's (readline: start of line).
  useBindings(
    () => ({
      priority: LAYER.clipboard,
      enabled: () => typeof (renderer.currentFocusedRenderable as { selectAll?: unknown } | null)?.selectAll === "function",
      commands: [
        {
          name: "field.select-all",
          run: () => {
            const target = renderer.currentFocusedRenderable as { selectAll?: () => boolean } | null;
            target?.selectAll?.();
          },
        },
      ],
      bindings: [{ key: "ctrl+a", cmd: "field.select-all" }],
    }),
    [renderer],
  );
  return null;
}

/** Layer priorities. Higher wins; a modal must outrank everything. */
export const LAYER = {
  global: 10,
  nav: 20,
  input: 30,
  modal: 100,
  clipboard: 200,
} as const;

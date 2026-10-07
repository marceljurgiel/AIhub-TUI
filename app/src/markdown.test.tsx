/** Assistant replies render Markdown with the theme's styles (the style names
 *  must match the parser's `markup.*` captures, or nothing gets styled). */
import { expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { TextAttributes } from "@opentui/core";
import { ChatLog } from "./widgets/ChatLog.tsx";

test("bold is bold and inline code is coloured", async () => {
  const t = await testRender(
    <ChatLog items={[{ kind: "assistant", text: "Visit **Belém** and eat `pastel`." }]} streamingText="" />,
    { width: 60, height: 8 },
  );
  let spans: Array<{ text: string; attributes: number; fg: any }> = [];
  for (let i = 0; i < 40; i++) {
    await t.renderOnce();
    spans = t.captureSpans().lines.flatMap((l) => l.spans);
    if (spans.some((s) => s.text.includes("Belém") && s.attributes & TextAttributes.BOLD)) break;
    await new Promise((r) => setTimeout(r, 50));
  }
  const bold = spans.find((s) => s.text.includes("Belém"));
  expect(bold && bold.attributes & TextAttributes.BOLD).toBeTruthy();
  const code = spans.find((s) => s.text.includes("pastel"));
  const plain = spans.find((s) => s.text.includes("Visit"));
  expect(code && plain && JSON.stringify(code.fg) !== JSON.stringify(plain.fg)).toBe(true);
  t.renderer.destroy();
});

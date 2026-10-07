import { test, expect } from "bun:test";
import { BridgeClient } from "./bridge/client.ts";

/** A small model that answers straight away. Thinking models (qwen3…) can
 *  spend minutes reasoning before the first text chunk, and cloud models
 *  (":cloud") leave the machine — both make a poor smoke test. */
function pickTestModel(models: Array<{ name: string }>): string {
  const names = models.map((m) => m.name).filter((n) => !n.endsWith(":cloud"));
  for (const want of ["llama3.2:3b", "gemma3:1b", "tinyllama", "qwen2.5-coder", "llama3", "gemma"]) {
    const hit = names.find((n) => n.startsWith(want));
    if (hit) return hit;
  }
  return names[0] ?? models[0]!.name;
}

// Verifies the TS BridgeClient <-> real Python aihub.bridge integration:
// spawn, NDJSON framing, one-shot request, and a live streaming chat.turn.
test("BridgeClient talks to the real Python bridge", async () => {
  const client = new BridgeClient();
  client.start();
  const ready = await client.ready();
  expect(ready.version).toMatch(/^\d+\.\d+\.\d+$/);

  const status = await client.request("backend.status");
  expect(typeof status.ollama_online).toBe("boolean");

  const inst = await client.request("models.installed");
  expect(Array.isArray(inst.models)).toBe(true);

  // Live streaming chat against a small model, if Ollama is up + has models.
  if (status.ollama_online && inst.models.length > 0) {
    const model = pickTestModel(inst.models);
    const started = await client.request("chat.start", { model, messages: [] });
    const msgs = [...started.messages, { role: "user", content: "Reply with the single word: pong" }];

    let text = "";
    const events: string[] = [];
    const { done } = client.stream(
      "chat.turn",
      { model, stream_model: model, backend: "ollama", messages: msgs, temperature: 0.1, context_length: 2048 },
      { onEvent: (ev, data) => { events.push(ev); if (ev === "text") text += data.text; } },
    );
    const result = await done;
    expect(events).toContain("text");
    expect(events).toContain("final");
    expect(result.messages.length).toBeGreaterThanOrEqual(3);
    console.log(`[integration] model=${model} events=${events.length} reply=${JSON.stringify(text.slice(0, 60))}`);
  } else {
    console.log("[integration] Ollama offline or no models — skipped chat.turn");
  }

  client.destroy();
}, 120000);

// chat.cancel against the real engine: the turn must end promptly with
// cancelled=true and a history that ends in the partial assistant reply.
test("chat.cancel stops a real streaming turn", async () => {
  const client = new BridgeClient();
  client.start();
  await client.ready();
  const status = await client.request("backend.status");
  const inst = await client.request("models.installed");
  if (!status.ollama_online || inst.models.length === 0) {
    console.log("[integration] Ollama offline or no models — skipped cancel");
    client.destroy();
    return;
  }
  const model = pickTestModel(inst.models);
  const started = await client.request("chat.start", { model, messages: [] });
  const msgs = [...started.messages, { role: "user", content: "Write a very long story about a dragon, at least 800 words." }];

  let chunks = 0;
  let cancelledAt = 0;
  const { id, done } = client.stream(
    "chat.turn",
    { model, stream_model: model, backend: "ollama", messages: msgs, temperature: 0.7, context_length: 2048, tools_enabled: false },
    {
      onEvent: (ev) => {
        if (ev !== "text") return;
        chunks++;
        if (chunks === 5) {
          cancelledAt = Date.now();
          client.cancel(id);
        }
      },
    },
  );
  const result = await done;
  const tookMs = Date.now() - cancelledAt;
  expect(result.cancelled).toBe(true);
  expect(result.messages.at(-1).role).toBe("assistant");
  expect(tookMs).toBeLessThan(3000);
  console.log(`[integration] cancel: ${chunks} chunks seen, done ${tookMs}ms after cancel`);
  client.destroy();
}, 120000);

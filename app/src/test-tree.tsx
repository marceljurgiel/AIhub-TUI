import type { ReactNode } from "react";
import { BridgeProvider } from "./state/BridgeContext.tsx";
import { SessionProvider } from "./state/SessionContext.tsx";
import { ModalProvider } from "./state/ModalContext.tsx";
import { AppKeymapProvider } from "./keymap/AppKeymap.tsx";
import { ChatScreen } from "./screens/ChatScreen.tsx";
import type { BridgeClient } from "./bridge/client.ts";

/** Provider stack shared by the tests, mirroring src/index.tsx exactly so a
 *  provider added there can't silently go missing under test. */
export function AppTree({
  client,
  children,
  readClipboard = async () => "",
  clipboardHasImage = async () => false,
}: {
  client: BridgeClient;
  children?: ReactNode;
  /** Tests never read the real system clipboard. */
  readClipboard?: () => Promise<string>;
  clipboardHasImage?: () => Promise<boolean>;
}) {
  return (
    <BridgeProvider client={client}>
      <SessionProvider>
        <AppKeymapProvider readClipboard={readClipboard} clipboardHasImage={clipboardHasImage}>
          <ModalProvider>{children ?? <ChatScreen version="0.2.1" coreVersion="0.3.15" />}</ModalProvider>
        </AppKeymapProvider>
      </SessionProvider>
    </BridgeProvider>
  );
}

/** A bridge that answers startup calls and streams a scripted chat turn. */
export class MockBridge {
  script: Array<{ e: string; d: any }> = [];
  start() {}
  destroy() {}
  cancel() {}
  permission() {}
  async ready() {
    return { version: "0.3.15" };
  }
  async request(method: string): Promise<any> {
    switch (method) {
      case "config.get":
        return {
          project_dir: "",
          memory_enabled: true,
          tools_enabled: true,
          default_context_length: 4096,
          default_chat_model: "llama3.2:3b",
        };
      case "backend.status":
        return { ollama_online: true, llamacpp_online: false, llamacpp_model: "" };
      case "models.installed":
        return { models: [{ name: "llama3.2:3b", size_gb: 2 }], recent: [] };
      case "chat.start":
        return { messages: [{ role: "system", content: "sys" }] };
      default:
        return {};
    }
  }
  stream(method: string, params: any, handlers: any) {
    if (method === "chat.turn" && this.script.length) {
      const done = (async () => {
        await Promise.resolve();
        for (const ev of this.script) handlers.onEvent(ev.e, ev.d);
        return {
          messages: [...params.messages, { role: "assistant", content: "The host is localhost." }],
        };
      })();
      return { id: 42, done };
    }
    return { id: 1, done: Promise.resolve({ messages: [] }) };
  }
}

export function mockClient(script: Array<{ e: string; d: any }> = []): BridgeClient {
  const b = new MockBridge();
  b.script = script;
  return b as unknown as BridgeClient;
}

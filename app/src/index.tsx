import { createCliRenderer } from "@opentui/core";
import { createRoot } from "@opentui/react";
import { useEffect, useState } from "react";
import { BridgeClient } from "./bridge/client.ts";
import { BridgeProvider } from "./state/BridgeContext.tsx";
import { SessionProvider } from "./state/SessionContext.tsx";
import { ModalProvider } from "./state/ModalContext.tsx";
import { AppKeymapProvider } from "./keymap/AppKeymap.tsx";
import { ChatScreen } from "./screens/ChatScreen.tsx";
import { theme } from "./theme.ts";

const bridge = new BridgeClient();
bridge.start();

import pkg from "../package.json" with { type: "json" };

function App() {
  // Two different versions: this UI, and the Python engine behind the bridge.
  // The sidebar used to show only the engine's, so `aihub 0.2.x` reported
  // "v0.3.15" and looked like the wrong app had started.
  const [core, setCore] = useState("…");
  useEffect(() => {
    bridge.ready().then((r) => setCore(r.version)).catch(() => setCore("offline"));
  }, []);

  return (
    <BridgeProvider client={bridge}>
      <SessionProvider>
        <AppKeymapProvider>
          <ModalProvider>
            <ChatScreen version={pkg.version} coreVersion={core} />
          </ModalProvider>
        </AppKeymapProvider>
      </SessionProvider>
    </BridgeProvider>
  );
}

// exitOnCtrlC: false — Ctrl+Q is bound to `quit`, which calls renderer.destroy().
// Never process.exit(): it would leave the terminal in raw mode on the alt screen.
const renderer = await createCliRenderer({ exitOnCtrlC: false });
renderer.setBackgroundColor(theme.bg0);
createRoot(renderer).render(<App />);

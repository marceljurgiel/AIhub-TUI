import { createContext, useContext, type ReactNode } from "react";
import type { BridgeClient } from "../bridge/client.ts";

const BridgeContext = createContext<BridgeClient | null>(null);

export function BridgeProvider({
  client,
  children,
}: {
  client: BridgeClient;
  children: ReactNode;
}) {
  return <BridgeContext.Provider value={client}>{children}</BridgeContext.Provider>;
}

export function useBridge(): BridgeClient {
  const c = useContext(BridgeContext);
  if (!c) throw new Error("useBridge must be used within a BridgeProvider");
  return c;
}

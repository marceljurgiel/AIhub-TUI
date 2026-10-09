import { theme, fit } from "../theme.ts";
import { ModalShell } from "../ui/ModalShell.tsx";
import { useModalKeys } from "./modalKit.ts";

/** At start, when Ollama on this machine has a newer release: update now
 *  (the command runs in the terminal panel, where sudo can ask) or later. */
export function UpdateOllamaModal({
  from,
  to,
  command,
  onClose,
}: {
  from: string;
  to: string;
  command: string;
  onClose: (choice: "update" | "later") => void;
}) {
  useModalKeys([
    { key: "return", run: () => onClose("update") },
    { key: "escape", run: () => onClose("later") },
  ]);
  const width = 72;
  return (
    <ModalShell title="Ollama update" width={width} hints={[["enter", "update"], ["esc", "later"]]}>
      <box flexDirection="column" paddingTop={1} paddingBottom={1}>
        <text fg={theme.fg0}>{`  Update Ollama ${from} → ${to}?`}</text>
        <text fg={theme.fg2}>{"  New models often need it. In the terminal panel this runs:"}</text>
        <text fg={theme.accentSoft}>{`    ${fit(command, width - 10)}`}</text>
        <text fg={theme.fg2}>{"  It restarts Ollama when it's done; sudo may ask for your password."}</text>
      </box>
    </ModalShell>
  );
}

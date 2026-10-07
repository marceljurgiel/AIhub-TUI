import {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  type ReactNode,
} from "react";
import { theme } from "../theme.ts";

/** A modal is rendered by a factory that receives a `close(value)` callback,
 *  mirroring Textual's push_screen/dismiss. */
export type ModalFactory<T> = (close: (value: T) => void) => ReactNode;

interface ModalEntry {
  id: number;
  render: (close: (value: any) => void) => ReactNode;
  resolve: (value: any) => void;
}

interface ModalApi {
  push<T = void>(factory: ModalFactory<T>): Promise<T>;
  depth: number;
  isOpen: boolean;
}

const ModalContext = createContext<ModalApi | null>(null);

let _modalId = 1;

export function ModalProvider({ children }: { children: ReactNode }) {
  const [stack, setStack] = useState<ModalEntry[]>([]);

  const close = useCallback((id: number, value: any) => {
    setStack((s) => {
      const entry = s.find((e) => e.id === id);
      entry?.resolve(value);
      return s.filter((e) => e.id !== id);
    });
  }, []);

  const push = useCallback(<T,>(factory: ModalFactory<T>): Promise<T> => {
    return new Promise<T>((resolve) => {
      const id = _modalId++;
      setStack((s) => [...s, { id, render: factory as any, resolve }]);
    });
  }, []);

  // Memoised: a fresh object here re-renders every consumer (the whole chat
  // screen) on any unrelated state change.
  const api: ModalApi = useMemo(
    () => ({ push, depth: stack.length, isOpen: stack.length > 0 }),
    [push, stack.length],
  );

  return (
    <ModalContext.Provider value={api}>
      <box width="100%" height="100%">
        {children}
        {stack.map((entry, i) => (
          <box
            key={entry.id}
            position="absolute"
            left={0}
            top={0}
            width="100%"
            height="100%"
            backgroundColor={theme.bg0}
            zIndex={100 + i}
            alignItems="center"
            justifyContent="center"
          >
            {entry.render((value) => close(entry.id, value))}
          </box>
        ))}
      </box>
    </ModalContext.Provider>
  );
}

export function useModals(): ModalApi {
  const c = useContext(ModalContext);
  if (!c) throw new Error("useModals must be used within a ModalProvider");
  return c;
}

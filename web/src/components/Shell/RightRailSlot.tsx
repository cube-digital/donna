// Right-rail slot — context-based "portal lite" for the 320px right column.
//
// AppShell renders `<RightRailOutlet/>` exactly once inside the grid.
// Any nested view can call `useRightRail(<node/>)` from a `useEffect`
// (the hook does the wrap for you) to publish its right-rail content;
// the previous occupant is cleared on unmount. Views that don't want a
// right rail simply don't call the hook — Outlet renders an empty
// `<aside/>` with the same chrome the populated rail would have.
//
// We prefer this over `createPortal` because the rightrail is a grid
// child of the shell, not a detached subtree — using a portal would
// break the grid placement.

import {
  createContext,
  ReactNode,
  useContext,
  useEffect,
  useState,
} from "react";

interface RightRailContextValue {
  node: ReactNode;
  setNode: (node: ReactNode) => void;
}

const RightRailContext = createContext<RightRailContextValue | null>(null);

interface RightRailProviderProps {
  children: ReactNode;
}

export function RightRailProvider({ children }: RightRailProviderProps) {
  const [node, setNode] = useState<ReactNode>(null);
  return (
    <RightRailContext.Provider value={{ node, setNode }}>
      {children}
    </RightRailContext.Provider>
  );
}

/**
 * Mount-time registration of the active view's right-rail content.
 *
 * Pass a stable element (memoize upstream if it carries data that
 * changes frequently — otherwise every re-render replaces the slot,
 * which is fine but noisy in devtools).
 *
 * Call with `null` to clear explicitly; cleanup also clears on unmount.
 */
export function useRightRail(node: ReactNode | null): void {
  const ctx = useContext(RightRailContext);
  useEffect(() => {
    if (!ctx) return;
    ctx.setNode(node);
    return () => {
      ctx.setNode(null);
    };
    // Re-fire only when `node` identity changes — ctx is stable from
    // RightRailProvider so listing it would just add noise.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node]);
}

/**
 * Renders the currently-registered right-rail node — always inside the
 * `[grid-area:rightrail]` aside so the grid cell occupies its 320 px
 * column on every route. The previous shape returned the registered
 * node as a bare fragment, which dropped it out of the grid placement
 * and made the column collapse (e.g. on `/personal` the topbar would
 * still be 4 columns wide but the right-rail content rendered outside
 * the dedicated cell).
 */
export function RightRailOutlet() {
  const ctx = useContext(RightRailContext);
  return (
    <aside className="[grid-area:rightrail] bg-bg-1 border-l border-border-soft overflow-y-auto px-3.5 py-3">
      {ctx?.node ?? null}
    </aside>
  );
}

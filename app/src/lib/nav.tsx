import { createContext, useContext } from "react";

export type SettingsTab = "sources" | "providers" | "health" | "docs";

export type Route =
  | { name: "today" }
  | { name: "passions" }
  | { name: "domain"; domain: string; viewId?: string }
  | { name: "inbox" }
  | { name: "create" }
  | { name: "settings"; tab?: SettingsTab };

export type DetailTarget = { domain: string; objectType: string; uid: string };

export type Nav = {
  route: Route;
  navigate: (route: Route, opts?: { replace?: boolean }) => void;
  openDetail: (target: DetailTarget) => void;
  closeDetail: () => void;
  refreshKey: number;
  refresh: () => void;
};

export const NavContext = createContext<Nav | null>(null);

export function useNav(): Nav {
  const ctx = useContext(NavContext);
  if (!ctx) throw new Error("useNav must be used within NavContext");
  return ctx;
}

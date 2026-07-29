import { createContext, useContext } from "react";

export type Route =
  | { name: "home" }
  | { name: "feed" }
  | { name: "review" }
  | { name: "health" }
  | { name: "docs" }
  | { name: "sources" }
  | { name: "domain"; domain: string; viewId?: string };

export type DetailTarget = { domain: string; objectType: string; uid: string };

export type Nav = {
  route: Route;
  navigate: (route: Route) => void;
  openDetail: (target: DetailTarget) => void;
  refreshKey: number;
  refresh: () => void;
};

export const NavContext = createContext<Nav | null>(null);

export function useNav(): Nav {
  const ctx = useContext(NavContext);
  if (!ctx) throw new Error("useNav must be used within NavContext");
  return ctx;
}

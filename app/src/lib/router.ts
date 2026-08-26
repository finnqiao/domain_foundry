// URL <-> Route mapping. This stays a small plain module because the app has
// one flat route union and no route-level loaders or actions.

import type { DetailTarget, Route, SettingsTab } from "./nav";

const SETTINGS_TABS: readonly SettingsTab[] = ["sources", "providers", "health", "docs"];

function isSettingsTab(value: string): value is SettingsTab {
  return (SETTINGS_TABS as readonly string[]).includes(value);
}

export function routeToPath(route: Route): string {
  switch (route.name) {
    case "today":
      return "/";
    case "passions":
      return "/passions";
    case "domain":
      return route.viewId
        ? `/passions/${encodeURIComponent(route.domain)}/${encodeURIComponent(route.viewId)}`
        : `/passions/${encodeURIComponent(route.domain)}`;
    case "inbox":
      return "/inbox";
    case "create":
      return "/create";
    case "foundry":
      return "/foundry";
    case "settings":
      return route.tab ? `/settings/${route.tab}` : "/settings";
  }
}

export function pathToRoute(path: string): Route {
  const segments = path
    .split("/")
    .filter(Boolean)
    .map((segment) => {
      try {
        return decodeURIComponent(segment);
      } catch {
        return segment;
      }
    });

  if (segments.length === 0) return { name: "today" };

  switch (segments[0]) {
    case "passions":
      if (segments.length === 1) return { name: "passions" };
      if (segments.length === 2) return { name: "domain", domain: segments[1] };
      return { name: "domain", domain: segments[1], viewId: segments[2] };
    case "inbox":
      return { name: "inbox" };
    case "create":
      return { name: "create" };
    case "foundry":
      return { name: "foundry" };
    case "settings":
      return segments[1] && isSettingsTab(segments[1])
        ? { name: "settings", tab: segments[1] }
        : { name: "settings" };
    default:
      return { name: "today" };
  }
}

export function detailToSearch(target: DetailTarget | null): string {
  if (!target) return "";
  const value = [target.domain, target.objectType, target.uid]
    .map((part) => encodeURIComponent(part))
    .join("/");
  const params = new URLSearchParams();
  params.set("detail", value);
  return `?${params.toString()}`;
}

export function searchToDetail(search: string): DetailTarget | null {
  const raw = new URLSearchParams(search).get("detail");
  if (!raw) return null;
  const parts = raw.split("/");
  if (parts.length !== 3) return null;
  const decoded = parts.map((part) => {
    try {
      return decodeURIComponent(part);
    } catch {
      return part;
    }
  });
  const [domain, objectType, uid] = decoded;
  if (!domain || !objectType || !uid) return null;
  return { domain, objectType, uid };
}

export function toLocation(route: Route, detail: DetailTarget | null = null): string {
  return routeToPath(route) + detailToSearch(detail);
}

export function fromLocation(
  pathname: string,
  search: string,
): { route: Route; detail: DetailTarget | null } {
  return { route: pathToRoute(pathname), detail: searchToDetail(search) };
}

import { describe, expect, it } from "vitest";
import { detailToSearch, fromLocation, pathToRoute, routeToPath, searchToDetail } from "./router";
import type { Route } from "./nav";

const EVERY_ROUTE: Route[] = [
  { name: "today" },
  { name: "passions" },
  { name: "domain", domain: "sourdough" },
  { name: "domain", domain: "sourdough", viewId: "bakes" },
  { name: "domain", domain: "weird name/slash" },
  { name: "inbox" },
  { name: "create" },
  { name: "foundry" },
  { name: "settings" },
  { name: "settings", tab: "sources" },
  { name: "settings", tab: "providers" },
  { name: "settings", tab: "health" },
  { name: "settings", tab: "docs" },
];

describe("route paths", () => {
  it.each(EVERY_ROUTE.map((route) => [JSON.stringify(route), route] as const))(
    "round-trips %s",
    (_label, route) => expect(pathToRoute(routeToPath(route))).toEqual(route),
  );

  it("lands safely on Today for unknown or malformed paths", () => {
    expect(pathToRoute("/no/such/page")).toEqual({ name: "today" });
    expect(pathToRoute("/settings/nope")).toEqual({ name: "settings" });
    expect(pathToRoute("/passions/%E0%A4%A")).toBeTruthy();
  });
});

describe("detail search parameter", () => {
  it("round-trips a UID containing a slash", () => {
    const target = { domain: "sourdough", objectType: "bake", uid: "co_01/AB" };
    expect(searchToDetail(detailToSearch(target))).toEqual(target);
  });

  it("returns null for absent or malformed values", () => {
    expect(searchToDetail("")).toBeNull();
    expect(searchToDetail("?detail=onlytwo/parts")).toBeNull();
  });

  it("composes a route and detail", () => {
    expect(fromLocation("/passions/sourdough/bakes", "?detail=sourdough/bake/co_1")).toEqual({
      route: { name: "domain", domain: "sourdough", viewId: "bakes" },
      detail: { domain: "sourdough", objectType: "bake", uid: "co_1" },
    });
  });
});

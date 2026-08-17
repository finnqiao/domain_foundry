import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Settings } from "./Settings";
import { NavContext, type Nav, type Route } from "../lib/nav";

const status = {
  config_file: "/tmp/config.json",
  config_file_exists: false,
  provider: "Anthropic",
  mode: "live",
  detected_env_keys: [{ provider: "Anthropic", env: "ANTHROPIC_API_KEY" }],
  routine: { model: "routine-model", base_url: "https://api.example.com", api_key_env: "ANTHROPIC_API_KEY", api_key_present: false, live: false },
  sota: { model: "sota-model", base_url: "https://api.example.com", api_key_env: "ANTHROPIC_API_KEY", api_key_present: true, live: true },
};

const mocks = vi.hoisted(() => ({ providers: vi.fn(), packs: vi.fn() }));
vi.mock("../lib/api", () => ({ api: mocks, ApiError: class ApiError extends Error { status = 500; } }));

const packs = [{ name: "sourdough", title: "Sourdough", description: "Bakes", icon: "🍞", version: "1", objects: ["bake"], views: [], object_count: 0 }];

function Harness() {
  const [route, setRoute] = useState<Route>({ name: "settings", tab: "sources" });
  const nav: Nav = {
    route,
    navigate: (next) => {
      setRoute(next);
    },
    openDetail: vi.fn(),
    closeDetail: vi.fn(),
    refreshKey: 0,
    refresh: vi.fn(),
  };
  return (
    <NavContext.Provider value={nav}>
      <Settings tab={route.name === "settings" ? route.tab : undefined} packs={packs} refreshKey={0} />
    </NavContext.Provider>
  );
}

describe("Settings", () => {
  beforeEach(() => {
    mocks.packs.mockResolvedValue(packs);
  });

  it("renders four tabs and provider status with a dead-tier explanation", async () => {
    mocks.providers.mockResolvedValue(status);
    render(<Harness />);
    expect(screen.getAllByRole("tab")).toHaveLength(4);
    await screen.getByRole("tab", { name: "Providers" }).click();
    expect(await screen.findByText("Anthropic · live")).toBeInTheDocument();
    expect(screen.getByText(/keyword rules/)).toBeInTheDocument();
  });

  it("moves the active tab and DOM focus with arrow keys", async () => {
    mocks.providers.mockResolvedValue(status);
    render(<Harness />);
    const sources = screen.getByRole("tab", { name: "Sources" });
    fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Providers" })).toHaveAttribute("aria-selected", "true");
    expect(sources).toHaveAttribute("tabindex", "-1");
    await waitFor(() => expect(screen.getByRole("tab", { name: "Providers" })).toHaveFocus());
  });
});

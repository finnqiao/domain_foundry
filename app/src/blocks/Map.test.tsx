import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MapBlock } from "./Map";
import type { BlockProps } from "./kit";

const mocks = vi.hoisted(() => ({
  listeners: new Map<string, (...args: unknown[]) => void>(),
  addSource: vi.fn(),
  addLayer: vi.fn(),
  fitBounds: vi.fn(),
  remove: vi.fn(),
  construct: vi.fn(),
}));

vi.mock("maplibre-gl", () => ({
  Map: class {
    constructor(options: unknown) { mocks.construct(options); }
    on(event: string, layerOrHandler: string | ((...args: unknown[]) => void), handler?: (...args: unknown[]) => void) {
      mocks.listeners.set(event, handler ?? layerOrHandler as (...args: unknown[]) => void);
    }
    addSource = mocks.addSource;
    addLayer = mocks.addLayer;
    fitBounds = mocks.fitBounds;
    remove = mocks.remove;
    getCanvas = () => ({ style: { cursor: "" } });
  },
  LngLatBounds: class {
    extend() { return this; }
    isEmpty() { return false; }
  },
}));

const props: BlockProps = {
  domain: "synthetic-venues",
  view: { id: "been-to-map", title: "Been-to map", block: "map" },
  data: {
    rows: [{ object_uid: "venue-1", object_type: "coffee_note", cafe_name: "Synthetic cafe", lat: 51, lng: 0 }],
    features: [{ type: "Feature", geometry: { type: "Point", coordinates: [0, 51] }, properties: { object_uid: "venue-1", object_type: "coffee_note" } }],
    object_types: ["coffee_note"],
  },
};

describe("MapBlock dependency compatibility", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listeners.clear();
  });

  it("loads venue data, preserves detail clicks, and removes the map on unmount", async () => {
    const openDetail = vi.fn();
    const { unmount } = render(<MapBlock {...props} onOpenDetail={openDetail} />);
    await waitFor(() => expect(mocks.listeners.has("load")).toBe(true));
    act(() => mocks.listeners.get("load")?.());
    expect(mocks.addSource).toHaveBeenCalledWith("venues", expect.objectContaining({ type: "geojson" }));
    expect(mocks.addLayer).toHaveBeenCalledWith(expect.objectContaining({ id: "venues-circle" }));
    expect(mocks.fitBounds).toHaveBeenCalled();
    act(() => mocks.listeners.get("click")?.({ features: [{ properties: { object_uid: "venue-1", object_type: "coffee_note" } }] }));
    expect(openDetail).toHaveBeenCalledWith("coffee_note", "venue-1");
    unmount();
    expect(mocks.remove).toHaveBeenCalled();
  });

  it("keeps a usable coordinate-list fallback until the map is ready", async () => {
    const openDetail = vi.fn();
    render(<MapBlock {...props} onOpenDetail={openDetail} />);
    fireEvent.click(screen.getByRole("button", { name: /Synthetic cafe/ }));
    expect(openDetail).toHaveBeenCalledWith("coffee_note", "venue-1");
    await waitFor(() => expect(mocks.construct).toHaveBeenCalled());
    expect(screen.getByLabelText("Venue list fallback")).toBeInTheDocument();
  });

  it("does not initialize a map for empty data", () => {
    render(<MapBlock {...props} data={{ rows: [], skipped_null_geo: 1 }} />);
    expect(screen.getByRole("status")).toHaveTextContent("No geocoded venues yet");
    expect(mocks.construct).not.toHaveBeenCalled();
  });
});

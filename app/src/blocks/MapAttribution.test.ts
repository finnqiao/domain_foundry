import { describe, expect, it, vi } from "vitest";
import { AttributionControl, type Map } from "maplibre-gl";

vi.hoisted(() => {
  // Older MapLibre bundles prepare a worker URL at import time. No worker is
  // launched by these DOM-only control tests.
  if (typeof URL.createObjectURL !== "function") {
    URL.createObjectURL = () => "blob:synthetic-map-worker";
  }
});

function attributionControl(attribution: string) {
  // AttributionControl needs style metadata, not a WebGL map or network tiles.
  const map = {
    style: { tileManagers: {} },
    _getUIString: () => "Toggle attribution",
    getCanvasContainer: () => document.createElement("div"),
    on: vi.fn(),
    off: vi.fn(),
  } as unknown as Map;
  const control = new AttributionControl({ compact: false, customAttribution: attribution });
  const element = control.onAdd(map);
  return { control, element, map };
}

describe("MapLibre attribution security", () => {
  it("removes consecutive dangerous attributes without skipping the next one", () => {
    // Regression for CVE-2026-85061. Values are inert and never executed.
    const { control, element } = attributionControl(
      '<a href="https://example.com/attribution" onload="void 0" onmouseover="void 0">Synthetic attribution</a>',
    );
    expect(element.textContent).toContain("Synthetic attribution");
    for (const child of element.querySelectorAll("*")) {
      expect([...child.attributes].some((attribute) => /^on/i.test(attribute.name))).toBe(false);
    }
    control.onRemove();
  });

  it("preserves safe attribution links and cleans up its event subscriptions", () => {
    const { control, element, map } = attributionControl(
      '<a href="https://example.com/attribution">Synthetic map attribution</a>',
    );
    const link = element.querySelector("a");
    expect(link?.textContent).toBe("Synthetic map attribution");
    expect(link?.getAttribute("href")).toBe("https://example.com/attribution");
    expect(map.on).toHaveBeenCalledTimes(5);
    control.onRemove();
    expect(map.off).toHaveBeenCalledTimes(5);
  });
});

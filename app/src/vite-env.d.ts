/// <reference types="vite/client" />

declare module "maplibre-gl" {
  export class Map {
    constructor(options: Record<string, unknown>);
    on(event: string, ...args: unknown[]): void;
    addSource(id: string, source: Record<string, unknown>): void;
    addLayer(layer: Record<string, unknown>): void;
    fitBounds(bounds: unknown, options?: Record<string, unknown>): void;
    getCanvas(): { style: { cursor: string } };
    remove(): void;
  }
  export class LngLatBounds {
    extend(coord: [number, number]): this;
    isEmpty(): boolean;
  }
}

declare module "maplibre-gl/dist/maplibre-gl.css";

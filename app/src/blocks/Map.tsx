import { useEffect, useMemo, useRef, useState } from "react";
import type { Map as MapLibreMap, MapLayerMouseEvent } from "maplibre-gl";
import type { BlockProps } from "./kit";
import { EmptyState, rowsOf } from "./kit";
import type { Row } from "../lib/types";

type MapFeature = {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: Record<string, unknown>;
};

const TYPE_LABELS: Record<string, string> = {
  coffee_note: "Coffee",
  dining_note: "Dining",
  dining: "Dining",
  drink_note: "Drinks",
};

/**
 * 10th built-in block — been-to map.
 *
 * Uses maplibre-gl when the dependency is installed; otherwise falls back to a
 * coordinate list so the block still works without a heavy frontend install.
 */
export function MapBlock({ data, onOpenDetail }: BlockProps) {
  const rows = rowsOf(data);
  const featuresValue = data["features"] as MapFeature[] | undefined;
  const skipped = Number(data["skipped_null_geo"] ?? 0);
  const objectTypes = (data["object_types"] as string[] | undefined) ?? [];
  const [filter, setFilter] = useState<string | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);

  const filteredRows = useMemo(
    () => (filter ? rows.filter((r) => r["object_type"] === filter) : rows),
    [rows, filter],
  );
  const filteredFeatures = useMemo(
    () => {
      const features = featuresValue ?? [];
      return filter
        ? features.filter((f) => f.properties?.["object_type"] === filter)
        : features;
    },
    [featuresValue, filter],
  );

  useEffect(() => {
    let cancelled = false;
    async function mount() {
      if (!containerRef.current || filteredFeatures.length === 0) {
        setMapReady(false);
        return;
      }
      try {
        const maplibre = await import("maplibre-gl");
        await import("maplibre-gl/dist/maplibre-gl.css");
        if (cancelled || !containerRef.current) return;
        mapRef.current?.remove();
        const map = new maplibre.Map({
          container: containerRef.current,
          style: "https://demotiles.maplibre.org/style.json",
          center: filteredFeatures[0].geometry.coordinates as [number, number],
          zoom: 11,
        });
        mapRef.current = map;
        map.on("load", () => {
          if (cancelled) return;
          const collection = {
            type: "FeatureCollection" as const,
            features: filteredFeatures,
          };
          map.addSource("venues", { type: "geojson", data: collection });
          map.addLayer({
            id: "venues-circle",
            type: "circle",
            source: "venues",
            paint: {
              "circle-radius": 7,
              "circle-color": "#0f766e",
              "circle-stroke-width": 2,
              "circle-stroke-color": "#ffffff",
            },
          });
          const bounds = new maplibre.LngLatBounds();
          for (const f of filteredFeatures) {
            bounds.extend(f.geometry.coordinates as [number, number]);
          }
          if (!bounds.isEmpty()) {
            map.fitBounds(bounds, { padding: 48, maxZoom: 13 });
          }
          map.on("click", "venues-circle", (e: MapLayerMouseEvent) => {
            const props = e.features?.[0]?.properties as Record<string, unknown> | undefined;
            if (!props || !onOpenDetail) return;
            const ot = String(props["object_type"] || "");
            const uid = String(props["object_uid"] || "");
            if (ot && uid) onOpenDetail(ot, uid);
          });
          map.on("mouseenter", "venues-circle", () => {
            map.getCanvas().style.cursor = "pointer";
          });
          map.on("mouseleave", "venues-circle", () => {
            map.getCanvas().style.cursor = "";
          });
          setMapReady(true);
          setMapError(null);
        });
      } catch (err) {
        if (!cancelled) {
          setMapReady(false);
          setMapError(err instanceof Error ? err.message : "maplibre unavailable");
        }
      }
    }
    void mount();
    return () => {
      cancelled = true;
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, [filteredFeatures, onOpenDetail]);

  if (rows.length === 0) {
    return (
      <EmptyState
        title="No geocoded venues yet"
        hint={
          skipped > 0
            ? `${skipped} venue note(s) still need lat/lng — run geocode_venues.py dry-run, then apply with confirmation.`
            : "Capture a coffee/dining note and backfill geo to populate the been-to map."
        }
      />
    );
  }

  return (
    <div className="map-block">
      <div className="map-toolbar" role="group" aria-label="Filter by type">
        <button
          type="button"
          className={`chip${filter === null ? " chip-active" : ""}`}
          onClick={() => setFilter(null)}
        >
          All <span className="count-pill">{rows.length}</span>
        </button>
        {objectTypes.map((ot) => {
          const n = rows.filter((r) => r["object_type"] === ot).length;
          if (!n) return null;
          return (
            <button
              key={ot}
              type="button"
              className={`chip${filter === ot ? " chip-active" : ""}`}
              onClick={() => setFilter(ot)}
            >
              {TYPE_LABELS[ot] || ot} <span className="count-pill">{n}</span>
            </button>
          );
        })}
        {skipped > 0 && (
          <span className="map-skipped" title="Venues without coordinates">
            {skipped} without geo
          </span>
        )}
      </div>

      <div
        className={`map-canvas${mapReady ? " map-canvas-ready" : ""}`}
        ref={containerRef}
        role="img"
        aria-label="Been-to map"
      />

      {(mapError || !mapReady) && (
        <div className="map-fallback" aria-label="Venue list fallback">
          {mapError && (
            <p className="empty-hint">
              MapLibre not loaded ({mapError}). Showing coordinate list — run{" "}
              <code>npm install</code> in <code>app/</code> for the interactive map.
            </p>
          )}
          <ul className="map-pin-list">
            {filteredRows.map((row) => (
              <PinRow key={String(row["object_uid"])} row={row} onOpenDetail={onOpenDetail} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function PinRow({
  row,
  onOpenDetail,
}: {
  row: Row;
  onOpenDetail?: (objectType: string, uid: string) => void;
}) {
  const uid = String(row["object_uid"] || "");
  const ot = String(row["object_type"] || "");
  const title = String(
    row["_title"] || row["place_name"] || row["cafe_name"] || row["restaurant"] || uid,
  );
  return (
    <li>
      <button
        type="button"
        className="map-pin-row"
        disabled={!onOpenDetail || !uid}
        onClick={() => onOpenDetail?.(ot, uid)}
      >
        <span className="map-pin-title">{title}</span>
        <span className="map-pin-meta">
          {TYPE_LABELS[ot] || ot} · {Number(row["lat"]).toFixed(4)}, {Number(row["lng"]).toFixed(4)}
        </span>
      </button>
    </li>
  );
}

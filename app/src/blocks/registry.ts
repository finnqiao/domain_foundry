import { createElement, lazy, Suspense, type ComponentType } from "react";
import type { BlockProps } from "./kit";
import { Timeline } from "./Timeline";
import { ListBlock } from "./ListBlock";
import { Search } from "./Search";
import { Stats } from "./Stats";
import { History } from "./History";
import { Planner } from "./Planner";
import { QuizStats } from "./QuizStats";
import { Gallery } from "./Gallery";
import { Compare } from "./Compare";

export type BlockId =
  | "capture_feed"
  | "list"
  | "timeline"
  | "detail"
  | "search"
  | "stats"
  | "history"
  | "planner"
  | "review_queue"
  | "map"
  | "quiz_stats"
  | "gallery"
  | "compare";

export type BlockMeta = {
  id: BlockId;
  title: string;
  dataContract: string[];
  /** Global surfaces are rendered by the shell, not by a per-domain view. */
  global?: boolean;
};

// Built-in blocks (plan §9.1 + Phase 6 map + Phase 4 quiz_stats).
export const BUILTIN_BLOCKS: BlockMeta[] = [
  { id: "capture_feed", title: "Capture feed", dataContract: ["entries"], global: true },
  { id: "list", title: "List", dataContract: ["object", "columns?", "group_by?"] },
  { id: "timeline", title: "Timeline", dataContract: ["object", "date_field"] },
  { id: "detail", title: "Detail", dataContract: ["object_uid"], global: true },
  { id: "search", title: "Search", dataContract: ["objects", "facets?"] },
  { id: "stats", title: "Stats", dataContract: ["object", "measures"] },
  { id: "history", title: "History", dataContract: ["object", "period"] },
  { id: "planner", title: "Planner", dataContract: ["object", "date_field"] },
  { id: "review_queue", title: "Review queue", dataContract: ["approvals"], global: true },
  { id: "map", title: "Map", dataContract: ["objects", "lat", "lng"] },
  { id: "quiz_stats", title: "Quiz stats", dataContract: ["domain?"] },
  { id: "gallery", title: "Gallery", dataContract: ["object", "media"] },
  { id: "compare", title: "Compare", dataContract: ["object", "metrics"] },
];

// Per-domain data blocks: keyed by the `block` field the API returns.
const DATA_BLOCKS: Record<string, ComponentType<BlockProps>> = {
  timeline: Timeline,
  list: ListBlock,
  search: Search,
  stats: Stats,
  history: History,
  planner: Planner,
  map: MapBoundary,
  quiz_stats: QuizStats,
  gallery: Gallery,
  compare: Compare,
};

// Runtime-registered custom blocks (side-loaded, plan §9.3).
const CUSTOM_BLOCKS: Record<string, ComponentType<BlockProps>> = {};

// MapLibre is already an async dependency inside Map.tsx. Keeping the block
// itself lazy means views that do not need a map never load its import trigger.
const LazyMap = lazy(() => import("./Map").then((module) => ({ default: module.MapBlock })));

function MapBoundary(props: BlockProps) {
  return createElement(
    Suspense,
    { fallback: createElement("p", { className: "muted" }, "Loading map…") },
    createElement(LazyMap, props),
  );
}

export function registerBlock(id: string, component: ComponentType<BlockProps>): void {
  CUSTOM_BLOCKS[id] = component;
}

export function resolveBlock(id: string | undefined): ComponentType<BlockProps> | null {
  if (!id) return null;
  return CUSTOM_BLOCKS[id] ?? DATA_BLOCKS[id] ?? null;
}

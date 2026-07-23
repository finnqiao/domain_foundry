import type { ComponentType } from "react";
import type { BlockProps } from "./kit";
import { Timeline } from "./Timeline";
import { ListBlock } from "./ListBlock";
import { Search } from "./Search";
import { Stats } from "./Stats";
import { History } from "./History";
import { Planner } from "./Planner";
import { MapBlock } from "./Map";
import { QuizStats } from "./QuizStats";

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
  | "quiz_stats";

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
];

// Per-domain data blocks: keyed by the `block` field the API returns.
const DATA_BLOCKS: Record<string, ComponentType<BlockProps>> = {
  timeline: Timeline,
  list: ListBlock,
  search: Search,
  stats: Stats,
  history: History,
  planner: Planner,
  map: MapBlock,
  quiz_stats: QuizStats,
};

// Runtime-registered custom blocks (side-loaded, plan §9.3).
const CUSTOM_BLOCKS: Record<string, ComponentType<BlockProps>> = {};

export function registerBlock(id: string, component: ComponentType<BlockProps>): void {
  CUSTOM_BLOCKS[id] = component;
}

export function resolveBlock(id: string | undefined): ComponentType<BlockProps> | null {
  if (!id) return null;
  return CUSTOM_BLOCKS[id] ?? DATA_BLOCKS[id] ?? null;
}

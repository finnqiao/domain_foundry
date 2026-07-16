/** Block registry — full catalog lands in P5. */
export type BlockId =
  | "capture_feed"
  | "list"
  | "timeline"
  | "detail"
  | "search"
  | "stats"
  | "history"
  | "planner"
  | "review_queue";

export type BlockMeta = {
  id: BlockId;
  title: string;
  dataContract: string[];
};

export const BUILTIN_BLOCKS: BlockMeta[] = [
  { id: "capture_feed", title: "Capture feed", dataContract: ["entries"] },
  { id: "list", title: "List", dataContract: ["object", "columns?"] },
  { id: "timeline", title: "Timeline", dataContract: ["object", "date_field"] },
  { id: "detail", title: "Detail", dataContract: ["object_uid"] },
  { id: "search", title: "Search", dataContract: ["objects", "facets?"] },
  { id: "stats", title: "Stats", dataContract: ["object", "measures"] },
  { id: "history", title: "History", dataContract: ["object", "period"] },
  { id: "planner", title: "Planner", dataContract: ["object", "date_field"] },
  { id: "review_queue", title: "Review queue", dataContract: ["approvals"] },
];

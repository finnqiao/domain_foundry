import { describe, expect, it } from "vitest";
import { describeReceipt } from "./receipts";
import type { CaptureReceipt, PackCard } from "./types";

const packs: PackCard[] = [
  {
    name: "sourdough",
    title: "Sourdough",
    description: "Bakes",
    icon: "🍞",
    version: "1",
    objects: ["bake"],
    views: [],
    object_count: 1,
  },
  {
    name: "plants",
    title: "Plants",
    description: "Care",
    icon: "🌱",
    version: "1",
    objects: ["plant"],
    views: [],
    object_count: 1,
  },
];

function receipt(status: CaptureReceipt["status"], domain: string | null = "sourdough"): CaptureReceipt {
  return {
    entry_id: "entry-1",
    capture_event_id: "capture-1",
    status,
    routed: [{ domain, object_type: "bake", operation: "create", disposition: status, confidence: 0.9 }],
    projection_status: "n/a",
    idempotent_replay: false,
  };
}

describe("plain receipts", () => {
  it("describes a saved object", () => {
    expect(describeReceipt(receipt("applied"), packs).headline).toBe("Saved to Sourdough as a bake");
  });

  it("describes a vowel-leading fallback as an entry", () => {
    const next = receipt("applied");
    next.routed[0].object_type = null;
    expect(describeReceipt(next, packs).headline).toBe("Saved to Sourdough as an entry");
  });

  it("offers a repair for uncertain captures", () => {
    expect(describeReceipt(receipt("review"), packs).repair).toEqual({ kind: "review" });
    expect(describeReceipt(receipt("unfiled", null), packs).repair).toEqual({ kind: "refile", entryId: "entry-1" });
  });

  it("explains degraded routing without exposing internals", () => {
    const next = receipt("applied");
    next.llm_error = "provider unavailable";
    expect(describeReceipt(next, packs).detail).toContain("Settings → Providers");
  });
});

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FoundryStudio } from "./FoundryStudio";
import type { FoundryCompletionResponse, FoundryProposalResponse } from "../lib/types";

const mocks = vi.hoisted(() => ({
  foundryGoldens: vi.fn(),
  foundryGolden: vi.fn(),
  foundryPropose: vi.fn(),
  foundryComplete: vi.fn(),
}));

vi.mock("../lib/api", () => ({ api: mocks }));

const concepts = ["bench", "timeline", "coach"].map((id, index) => ({
  id,
  title: ["Practice Bench", "Living Timeline", "Decision Coach"][index],
  thesis: `Thesis ${index + 1}`,
  primary_loop: `Loop ${index + 1}`,
  primary_affordance: `Affordance ${index + 1}`,
  differentiator: `Difference ${index + 1}`,
  feature_boundary: ["Inside", "Outside"],
  tradeoffs: ["One tradeoff"],
  workflow_ids: [`workflow-${index + 1}`],
  evidence_ids: ["evidence-1"],
}));

const proposed: FoundryProposalResponse = {
  proposal_id: "01K00000000000000000000000",
  candidate_sources: 8,
  sources: [],
  proposal: {
    id: "trail-map-room",
    title: "Trail Map Room",
    goal: "Understand a trail-map collection",
    artifacts: ["photo folder"],
    constraints: ["offline"],
    research: {
      interest: "vintage trail maps",
      desired_outcome: "Understand where, when, and why every map matters.",
      practice: ["Acquire maps", "Compare editions"],
      existing_artifacts: ["photo folder"],
      constraints: ["offline"],
      first_value: "Add one map and place it in its edition lineage.",
    },
    source_ids: ["source-1", "source-2", "source-3"],
    source_snapshots: [],
    principle_ids: ["DE-01", "DE-02", "UX-01", "UX-02", "SE-01", "SE-03"],
    evidence: [{ id: "evidence-1", source_id: "source-1", claim: "Maps have editions.", use: "fact" }],
    concepts,
  },
};

const completed = {
  proposal_id: proposed.proposal_id,
  spec: {
    ...proposed.proposal,
    domain: {
      entities: [{ id: "map", title: "Map", kind: "canonical", description: "One edition", identity: ["map_id"] }],
      relationships: [],
      workloads: [{ id: "compare", question: "How do editions differ?", acceptance: "Shows both." }],
    },
    experience: {
      visual_world: { id: "archive", name: "Map archive", mood: "Field notes", tokens: { background: "#ffffff", accent: "#885522" } },
      navigation: { topology: "canvas", primary_view: "archive" },
      views: [{ id: "archive", title: "Archive", purpose: "Place maps", layout: "canvas" }],
    },
    evaluation: { cases: [{ id: "task", kind: "task", input: "Add map", expected: "Placed", authored_by: "user" }] },
  },
  owned_app_html: "<!doctype html><title>Trail Map Room</title>",
  app_url: "/api/foundry/apps/01K00000000000000000000000",
  artifacts: { app: "app.html", schema: "schema.sql" },
} as FoundryCompletionResponse;

describe("FoundryStudio", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.foundryGoldens.mockResolvedValue([]);
    mocks.foundryPropose.mockResolvedValue(proposed);
    mocks.foundryComplete.mockResolvedValue(completed);
  });

  it("retains user-authored tasks through concept selection and exact-app compilation", async () => {
    const user = userEvent.setup();
    render(<FoundryStudio />);

    await user.type(screen.getByLabelText("Interest and desired outcome"), "Understand my trail maps");
    const actions = screen.getAllByLabelText("What will you do?");
    const results = screen.getAllByLabelText("What observable result means it worked?");
    await user.type(actions[0], "Add a map");
    await user.type(results[0], "See its edition lineage");
    await user.type(actions[1], "Compare two editions");
    await user.type(results[1], "See their differences");
    await user.click(screen.getByRole("button", { name: "Research and propose three cuts" }));

    expect(await screen.findByRole("heading", { name: "Choose a loop, then splice deliberately." })).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(3);
    await user.click(screen.getByRole("radio", { name: /Living Timeline/ }));
    await user.type(screen.getByLabelText("Your decision"), "The chronology matches how I compare maps.");
    await user.click(screen.getByRole("button", { name: "Compile this remix" }));

    await waitFor(() => expect(mocks.foundryComplete).toHaveBeenCalled());
    expect(await screen.findByRole("heading", { name: "Trail Map Room" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open the exact compiled app" }));
    expect(await screen.findByTitle("Trail Map Room application")).toHaveAttribute(
      "srcdoc",
      expect.stringContaining("Trail Map Room"),
    );
  });
});

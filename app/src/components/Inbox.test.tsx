import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Inbox } from "./Inbox";
import { NavContext, type Nav } from "../lib/nav";
import type { PackCard, ReviewItem } from "../lib/types";

const mocks = vi.hoisted(() => ({
  review: vi.fn(),
  query: vi.fn(),
  refileEntry: vi.fn(),
  correct: vi.fn(),
  resolve: vi.fn(),
  bulkResolve: vi.fn(),
}));

vi.mock("../lib/api", () => ({
  api: mocks,
  ApiError: class ApiError extends Error {
    status = 500;
  },
}));

const packs: PackCard[] = [
  { name: "sourdough", title: "Sourdough", description: "Bakes", icon: "🍞", version: "1", objects: ["bake"], views: [], object_count: 0 },
  { name: "plants", title: "Plants", description: "Care", icon: "🌱", version: "1", objects: ["plant"], views: [], object_count: 0 },
];

const reviewItem: ReviewItem = {
  approval_id: "approval-1",
  change_request_id: 1,
  decision_status: "pending",
  application_status: "pending",
  domain: "sourdough",
  operation: "create",
  object_type: "bake",
  object_uid: "uid-1",
  summary: "a country loaf",
  confidence: 0.7,
  created_at: "2026-08-10T00:00:00Z",
  age_seconds: 20,
  diff: { operation: "create", object_uid: "uid-1", is_new: true, fields: [] },
};

const nav: Nav = {
  route: { name: "inbox" },
  navigate: vi.fn(),
  openDetail: vi.fn(),
  closeDetail: vi.fn(),
  refreshKey: 0,
  refresh: vi.fn(),
};

function renderInbox() {
  return render(
    <NavContext.Provider value={nav}>
      <Inbox packs={packs} refreshKey={0} onChanged={vi.fn()} />
    </NavContext.Provider>,
  );
}

describe("Inbox", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.review.mockResolvedValue([reviewItem]);
    mocks.query.mockResolvedValue([
      {
        id: "entry-1",
        capture_event_id: "capture-1",
        status: "unfiled",
        domain: null,
        object_type: null,
        operation: null,
        routing_confidence: null,
        fallback_tier: null,
        summary: null,
        raw_text: "a note I cannot place",
        channel: "web",
        created_at: "2026-08-10T00:00:00Z",
        updated_at: "2026-08-10T00:00:00Z",
      },
    ]);
    mocks.refileEntry.mockResolvedValue({ applied: true, entry_id: "entry-1", domain: "sourdough", status: "applied" });
  });

  it("renders review and unfiled sections with one repair button per passion", async () => {
    renderInbox();
    expect(await screen.findByRole("heading", { name: "Waiting for your OK" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Couldn’t file these" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sourdough" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Plants" })).toBeInTheDocument();
  });

  it("refiles an unfiled entry when a passion is chosen", async () => {
    const user = userEvent.setup();
    renderInbox();
    await user.click(await screen.findByRole("button", { name: "Sourdough" }));
    await waitFor(() => expect(mocks.refileEntry).toHaveBeenCalledWith("entry-1", "sourdough"));
  });

  it("shows the quiet empty state when both sources are clear", async () => {
    mocks.review.mockResolvedValue([]);
    mocks.query.mockResolvedValue([]);
    renderInbox();
    expect(await screen.findByText("Nothing needs your attention")).toBeInTheDocument();
  });
});

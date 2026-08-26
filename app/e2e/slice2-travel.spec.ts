import { expect, test } from "@playwright/test";

test("travel packing uses the declarative apply action and pack accent", async ({ page }) => {
  await page.goto("/");

  let packed = false;
  const applied: Record<string, unknown>[] = [];
  await page.route("**/api/blocks/travel/packing/data*", async (route) => {
    const row = {
      object_uid: "travel:packing_item:01",
      object_type: "packing_item",
      name: "Passport",
      category: "Essentials",
      packed,
    };
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        block: "list",
        object_type: "packing_item",
        group_by: "category",
        rows: [row],
        groups: { Essentials: [row] },
      }),
    });
  });
  await page.route("**/api/apply", async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    applied.push(body);
    packed = Boolean((body.fields as Record<string, unknown>).packed);
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ ok: true, applied: true }) });
  });

  await page.getByRole("button", { name: "Your passions", exact: true }).click();
  await page.locator(".catalog-card").filter({ hasText: "Travel Planner" }).getByRole("button", { name: "Install" }).click();
  await expect(page).toHaveURL(/\/passions\/travel(?:\/trips)?$/);
  await page.getByRole("tab", { name: "Packing" }).click();
  await expect(page.getByRole("button", { name: "Passport", exact: true })).toBeVisible();
  await expect(page.locator(".domain-view")).toHaveAttribute("style", /--domain-accent/);
  await page.getByRole("button", { name: "Packed: not packed" }).click();
  await expect(page.getByRole("button", { name: "Packed: packed" })).toHaveAttribute("aria-pressed", "true");
  expect(applied).toEqual([
    expect.objectContaining({
      domain: "travel",
      operation: "update",
      object_type: "packing_item",
      object_uid: "travel:packing_item:01",
      fields: { packed: true },
    }),
  ]);
});

test("Sources shows a Roamboard preview table and shadow streak", async ({ page }) => {
  let committed = false;
  await page.route("**/api/import/roamboard/shadow", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        available: true,
        report: { zero_diff: false },
        streak: { days: 3, target: 7, complete: false, source: null, human_gate: true },
      }),
    });
  });
  await page.route("**/api/import/roamboard/preview", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        phase: "preview",
        feed_path: "/tmp/feed.json",
        content_fingerprint: "abcdef0123456789",
        source_total: 1,
        accounted_for: 1,
        complete: true,
        created: 1,
        updated: 0,
        skipped: 0,
        conflict: 0,
        error: 0,
        records: [{ entity: "trip", source_ref: "trip-1", source_id: "trip-1", outcome: "created", reason: null }],
        raw_adapter_payload: { import_report: { source_total: 1 } },
        preview_token: "one-shot-token",
      }),
    });
  });
  await page.route("**/api/import/roamboard/commit", async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    expect(body.preview_token).toBe("one-shot-token");
    committed = true;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        phase: "commit",
        feed_path: "/tmp/feed.json",
        content_fingerprint: "abcdef0123456789",
        source_total: 1,
        accounted_for: 1,
        complete: true,
        created: 1,
        updated: 0,
        skipped: 0,
        conflict: 0,
        error: 0,
        records: [{ entity: "trip", source_ref: "trip-1", source_id: "trip-1", outcome: "created", reason: null }],
        raw_adapter_payload: { import_report: { source_total: 1 } },
      }),
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("tab", { name: "Sources" }).click();
  await page.getByLabel("Feed JSON path").fill("/tmp/feed.json");
  await page.getByRole("button", { name: "Preview import" }).click();
  await expect(page.getByTestId("roamboard-report")).toContainText("trip");
  await expect(page.getByTestId("roamboard-report")).toContainText("created");
  await expect(page.locator(".shadow-progress")).toHaveAttribute("value", "3");
  await page.getByRole("button", { name: "Commit reviewed feed" }).click();
  expect(committed).toBeTruthy();
  await expect(page.getByTestId("roamboard-report")).toContainText("Committed.");
});

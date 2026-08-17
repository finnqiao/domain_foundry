import { expect, test } from "@playwright/test";

test("the primary IA keeps Today, passions, Inbox, and Settings reachable", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Today" })).toBeVisible();

  await page.getByRole("button", { name: "Your passions", exact: true }).click();
  await expect(page).toHaveURL(/\/passions$/);
  await expect(page.getByRole("heading", { name: "Your passions" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create your own" })).toBeVisible();

  await page.getByRole("button", { name: "Inbox", exact: true }).click();
  await expect(page).toHaveURL(/\/inbox$/);
  await expect(page.getByRole("heading", { name: "Inbox" })).toBeVisible();

  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await page.getByRole("tab", { name: "Providers" }).click();
  await expect(page).toHaveURL(/\/settings\/providers$/);
  await expect(page.getByRole("heading", { name: "Providers" })).toBeVisible();
  await expect(page.locator(".settings-tabs").getByRole("tab", { name: "Providers" })).toHaveAttribute("aria-selected", "true");
});

test("Ask returns the honest search-backed answer state when no model is available", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("tab", { name: "Ask" }).click();
  await page.getByLabel("Ask a question").fill("What do my saved records say about this?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();

  await expect(page.getByRole("region", { name: "Answer" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Answer" }).getByText(/search-only|saved record/i)).toBeVisible();
});

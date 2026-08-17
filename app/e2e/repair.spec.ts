import { expect, test } from "@playwright/test";
import { openSourdough } from "./helpers";

test("Inbox exposes a one-click passion choice for an unfiled capture", async ({ page }) => {
  await openSourdough(page);

  const rawText = "a note about an unrelated blue umbrella and a quiet afternoon";
  const capture = await page.request.post("/api/capture", {
    data: { text: rawText, channel: "web" },
  });
  expect(capture.ok()).toBeTruthy();

  await page.getByRole("button", { name: "Inbox", exact: true }).click();
  const row = page.locator(".attention-row").filter({ hasText: rawText });
  await expect(row).toBeVisible();
  const refile = row.locator(".refile-actions").getByRole("button", { name: "Sourdough Journey", exact: true });
  await expect(refile).toBeVisible();
  const refileResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/entries/") &&
      response.url().endsWith("/refile") &&
      response.request().method() === "POST",
  );
  await refile.click();

  const response = await refileResponse;
  expect(response.ok()).toBeTruthy();
  await expect(row).toHaveCount(0);
});

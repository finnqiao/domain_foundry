import { expect, test } from "@playwright/test";
import { openSourdough } from "./helpers";

test("a deep passion URL survives a browser refresh", async ({ page }) => {
  await openSourdough(page);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Sourdough Journey" })).toBeVisible();
});

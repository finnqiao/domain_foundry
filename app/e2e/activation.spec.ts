import { expect, test, type Page } from "@playwright/test";

// Activation journey carried forward through the Slice 1 shell:
// Today → Your passions → in-domain capture → detail/correction → Inbox.

const CAPTURE_A = "baked a 75% hydration country loaf, bulk 5h, came out great";
const CAPTURE_B = "baked a 68% hydration seeded rye loaf, bulk 4h";

async function capture(page: Page, text: string) {
  await page.getByLabel("Log text").fill(text);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".capture-receipt")).toBeVisible();
}

test("activation journey: install → capture → correct → review", async ({ page }) => {
  // 1. Open / — Today teaches the first useful action.
  await page.goto("/");
  await expect(page.getByText("Describe a passion and get an app")).toBeVisible();

  // 2. Open Your passions and install sourdough from the starter catalog.
  await page.getByRole("button", { name: "Your passions", exact: true }).click();
  const sourdoughCard = page
    .locator(".catalog-card")
    .filter({ hasText: "Sourdough Journey" });
  await sourdoughCard.getByRole("button", { name: "Install" }).click();

  // 3. Installation lands in the passion with a scoped composer.
  await expect(page).toHaveURL(/\/passions\/sourdough(?:\/bakes)?$/);
  await expect(page.locator(".composer-scope")).toContainText("Sourdough Journey");
  await expect(page.locator(".side-domains")).toContainText("Sourdough Journey");

  // 4. Capture inside the passion; the receipt shows it was filed.
  await capture(page, CAPTURE_A);
  await expect(page.locator(".capture-receipt")).toContainText("Saved to Sourdough Journey as a bake");

  // 5. Open the entry's detail view.
  await page.locator(".side-domains").getByText("Sourdough Journey").click();
  const firstCard = page.locator(".timeline-card").first();
  await expect(firstCard).toBeVisible();
  await firstCard.click();
  const detail = page.getByRole("dialog", { name: "Object detail" });
  await expect(detail).toBeVisible();
  await expect(detail).toContainText("75");

  // 6. Correct a field (hydration 75 → 80); the revision becomes visible.
  await detail.getByRole("button", { name: "Correct" }).click();
  const correct = page.getByRole("dialog", { name: "Correct", exact: true });
  await expect(correct).toBeVisible();
  const hydration = correct
    .locator(".field-row")
    .filter({ hasText: "Hydration" })
    .locator("input");
  await hydration.fill("80");
  await correct.getByRole("button", { name: "Apply correction" }).click();
  await expect(detail).toContainText("Revision 1");
  await expect(detail).toContainText("80");
  await page.keyboard.press("Escape"); // close the detail modal

  // 7. Force a review item: capture a second bake, then merge it into the
  //    first — merge is review-gated by packs/sourdough/policy.yaml.
  //    The UIDs come from the rendered timeline, keeping this journey on the
  //    same user-facing read path as the detail interaction above.
  await page.getByRole("button", { name: "Today", exact: true }).click();
  await capture(page, CAPTURE_B);

  await page.locator(".side-domains").getByText("Sourdough Journey").click();
  const bakeCards = page.locator('.timeline-card[data-object-uid]');
  await expect(bakeCards).toHaveCount(2);
  const survivorUid = String(await bakeCards.nth(0).getAttribute("data-object-uid"));
  const duplicateUid = String(await bakeCards.nth(1).getAttribute("data-object-uid"));
  const merge = await page.request.post("/api/correct", {
    data: {
      object_uid: duplicateUid,
      action: "merge",
      merge_into_uid: survivorUid,
      channel: "web",
    },
  });
  expect(merge.ok()).toBeTruthy();

  // 8. Resolve it from the Review queue.
  await page.getByRole("button", { name: "Inbox", exact: true }).click();
  const attentionItem = page.locator(".attention-row").first();
  await expect(attentionItem).toBeVisible();
  const resolveResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/review/") &&
      response.url().endsWith("/resolve") &&
      response.request().method() === "POST",
  );
  await attentionItem.getByRole("button", { name: "Save it", exact: true }).click();
  expect((await (await resolveResponse).json()).applied).toBeTruthy();
  await expect(page.getByText("Nothing needs your attention")).toBeVisible();
});

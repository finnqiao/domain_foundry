import { expect, test } from "@playwright/test";
import { openCreateYourOwn } from "./helpers";

const GOAL = "i collect pokemon cards";
const PULL = "pulled a holographic Charizard from a 151 booster, NM";
const DOMAIN_URL = /\/passions\/[^/]*(cards?|pokemon|collection)/i;

test("create your own: pokemon cards → look → build → capture", async ({ page }) => {
  test.setTimeout(120_000);

  await openCreateYourOwn(page);

  await page.getByLabel("What would you like an app for?").fill(GOAL);
  await page.getByRole("button", { name: "Continue" }).click();

  const cardIdea = page.locator(".atlas-idea").filter({ hasText: /Card dex|card/i }).first();
  await expect(cardIdea).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "What would you like to do with this?" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Show schema" })).toHaveCount(0);
  await cardIdea.click();

  await expect(page.locator(".look-frame, .look-card").first()).toBeVisible({ timeout: 45_000 });
  await expect(page.locator(".look-card header")).not.toContainText(/media_dex|hero_job|event_log/i);

  const critique = page.getByPlaceholder("What should change? e.g. darker or denser…");
  if (await critique.isVisible()) {
    await critique.fill("make the gallery denser");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.locator(".look-frame, .look-card").first()).toBeVisible({ timeout: 45_000 });
  }

  await page.getByRole("button", { name: "Use this direction" }).click();

  const note = page.getByPlaceholder("Write it as you would on a normal day…");
  await expect(note).toBeVisible({ timeout: 30_000 });
  await note.fill(PULL);
  await page.getByRole("button", { name: "Use this note" }).click();
  await expect(page.getByRole("heading", { name: "Add a second note" })).toBeVisible({ timeout: 30_000 });
  await page.getByPlaceholder("Write it as you would on a normal day…").fill("opened a 151 booster and added the holo to my binder");
  await page.getByRole("button", { name: "Use this note" }).click();

  await expect(page.getByRole("heading", { name: "Try your first note" })).toBeVisible({ timeout: 90_000 });
  await page.getByPlaceholder(/Write one real note/).fill(PULL);
  await page.getByRole("button", { name: "Save note" }).click();
  await expect(page.getByText("Went to the right place")).toBeVisible({ timeout: 45_000 });
  await page.getByRole("button", { name: "Done for now" }).click();

  await expect(page).toHaveURL(DOMAIN_URL);
});

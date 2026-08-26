import { expect, type Page } from "@playwright/test";

export async function openCreateYourOwn(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Your passions", exact: true }).click();
  await page.getByRole("button", { name: "Create your own" }).click();
  await expect(page).toHaveURL(/\/create$/);
  await expect(page.getByRole("heading", { name: "Create your own" })).toBeVisible();
}

export async function openSourdough(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Your passions", exact: true }).click();

  const installed = page.locator(".domain-card").filter({ hasText: "Sourdough Journey" }).first();
  const install = page
    .locator(".catalog-card")
    .filter({ hasText: "Sourdough Journey" })
    .getByRole("button", { name: "Install" });
  // Pack state loads after the route renders. A synchronous count can observe
  // neither branch and then wait forever for the catalog card even when the
  // installed card appears a moment later.
  await expect(installed.or(install)).toBeVisible();
  if (await installed.isVisible()) {
    await installed.click();
  } else {
    await install.click();
  }

  await expect(page).toHaveURL(/\/passions\/sourdough(?:\/bakes)?$/);
}

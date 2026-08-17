import { expect, type Page } from "@playwright/test";

export async function openSourdough(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Your passions", exact: true }).click();

  const installed = page.locator(".domain-card").filter({ hasText: "Sourdough Journey" });
  if (await installed.count() === 0) {
    await page.locator(".catalog-card").filter({ hasText: "Sourdough Journey" }).getByRole("button", { name: "Install" }).click();
  } else {
    await installed.first().click();
  }

  await expect(page).toHaveURL(/\/passions\/sourdough(?:\/bakes)?$/);
}

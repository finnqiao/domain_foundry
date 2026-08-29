// Drive the review page in a real headless browser and keep what Save hands back.
//
// The page is opened from disk, exactly as a person opens it. Everything here
// is done with the keyboard where the page allows it, because that is the floor
// the page has to meet. The saved file is written where the caller asked, and
// a one line JSON summary goes to stdout.
//
// Run: node review_marks_roundtrip.cjs <page.html> <output-dir>
// Needs NODE_PATH to point at a node_modules that has playwright.

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

async function main() {
  const pagePath = process.argv[2];
  const outDir = process.argv[3];
  if (!pagePath || !outDir) {
    throw new Error("usage: node review_marks_roundtrip.cjs <page.html> <output-dir>");
  }
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch();
  const context = await browser.newContext({ acceptDownloads: true });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on("pageerror", (error) => consoleErrors.push(String(error)));

  await page.goto("file://" + path.resolve(pagePath));

  const conceptIds = await page.$$eval(".card[data-concept]", (cards) =>
    cards.map((card) => card.getAttribute("data-concept"))
  );
  if (conceptIds.length < 2) throw new Error("the page shows fewer than two concepts");
  const chosen = conceptIds[1];
  const other = conceptIds[0];

  // Pick a concept with the keyboard: focus its radio, press space.
  const radio = page.locator(`input[name="chosen"][value="${chosen}"]`);
  await radio.focus();
  await page.keyboard.press("Space");
  const picked = await radio.isChecked();
  if (!picked) throw new Error("the keyboard could not pick a concept");

  // A focused control has to be visible as focused.
  const focusOutline = await page.evaluate(() => {
    const active = document.activeElement;
    if (!active) return "";
    return getComputedStyle(active).outlineStyle + " " + getComputedStyle(active).outlineWidth;
  });

  const card = page.locator(`.card[data-concept="${chosen}"]`);
  // The look controls sit behind a summary you open, so open it the way a
  // person would.
  await card.locator("summary", { hasText: "Change the look of this one" }).click();
  await card.locator("[data-token='accent']").fill("#E39A2D");
  await card.locator("[data-field='density_scale']").selectOption("dense");
  await card.locator("[data-field='topology']").selectOption("workflow");

  // Pin a note without a mouse.
  await card.locator("[data-pin-add]").click();
  await card.locator("[data-pin-list] input").first().fill("the timer belongs first");

  // Borrow a piece from the concept we are not building.
  const otherCard = page.locator(`.card[data-concept="${other}"]`);
  await otherCard.locator("[data-borrow]").fill("the big Feed now button");
  await otherCard.locator("[data-borrow-reason]").fill("it is the only thing I want at 6am");

  await page.locator("#extra-notes").fill("I open this one handed");

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator("#save").click(),
  ]);
  const target = path.join(outDir, download.suggestedFilename());
  await download.saveAs(target);
  const status = await page.locator("#status").textContent();

  // The page must also work when it is only 320 pixels wide.
  await page.setViewportSize({ width: 320, height: 720 });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth
  );

  await browser.close();
  process.stdout.write(
    JSON.stringify({
      saved: target,
      suggested: download.suggestedFilename(),
      chosen,
      other,
      status,
      focus_outline: focusOutline,
      overflows_at_320: overflow,
      page_errors: consoleErrors,
    }) + "\n"
  );
}

main().catch((error) => {
  process.stderr.write(String((error && error.stack) || error) + "\n");
  process.exit(1);
});

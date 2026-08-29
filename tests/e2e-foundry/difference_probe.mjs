// Browser half of the difference gate (release proof #2).
//
// Takes a JSON job on argv: { pages: [{ id, path }], outDir }.
// For each compiled app.html it records a desktop and a 390px screenshot,
// runs axe, checks for horizontal overflow at 320px, and reports the DOM
// landmark counts. Writes one JSON report and exits 0. Judging is the Python
// gate's job; this only measures.
//
//   node tests/e2e-foundry/difference_probe.mjs '<json>'
//
// Playwright and axe come from app/node_modules, which is where the repo
// installs them.

import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import path from "node:path";

const require = createRequire(new URL("../../app/package.json", import.meta.url));
const { chromium } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default ?? require("@axe-core/playwright");

const DESKTOP = { width: 1280, height: 900 };
const PHONE = { width: 390, height: 844 };
const NARROW = { width: 320, height: 800 };

const job = JSON.parse(process.argv[2]);
mkdirSync(job.outDir, { recursive: true });

const browser = await chromium.launch();
const report = { pages: [] };

for (const target of job.pages) {
  const context = await browser.newContext({ viewport: DESKTOP });
  const page = await context.newPage();
  await page.goto(pathToFileURL(target.path).href, { waitUntil: "load" });
  await page.waitForTimeout(250);

  const desktopShot = path.join(job.outDir, `${target.id}-desktop.png`);
  await page.screenshot({ path: desktopShot, fullPage: false });

  const structure = await page.evaluate(() => {
    const tag = (name) => document.querySelectorAll(name).length;
    const attribute = (name) =>
      [...document.querySelectorAll(`[${name}]`)].map((node) => node.getAttribute(name));
    const root = getComputedStyle(document.documentElement);
    const body = getComputedStyle(document.body);
    const token = (name) => root.getPropertyValue(name).trim();
    return {
      topology: document.body.getAttribute("data-topology"),
      regionKinds: attribute("data-region-kind"),
      landmarks: {
        nav: tag("nav"),
        aside: tag("aside"),
        main: tag("main"),
        section: tag("section"),
        header: tag("header"),
        table: tag("table"),
        svg: tag("svg"),
        form: tag("form"),
        article: tag("article"),
      },
      roles: attribute("role"),
      tokens: {
        background: token("--bg"),
        surface: token("--surface"),
        ink: token("--ink"),
        accent: token("--accent"),
        accentAlt: token("--accent-alt"),
        border: token("--border"),
        radius: token("--radius"),
      },
      fontFamily: body.fontFamily,
      bodyBackground: body.backgroundColor,
    };
  });

  const accessibility = await new AxeBuilder({ page }).analyze();
  const violations = accessibility.violations
    .filter((item) => ["serious", "critical"].includes(item.impact ?? ""))
    .map((item) => ({ id: item.id, impact: item.impact, nodes: item.nodes.length }));

  await page.setViewportSize(PHONE);
  await page.waitForTimeout(150);
  const phoneShot = path.join(job.outDir, `${target.id}-phone.png`);
  await page.screenshot({ path: phoneShot, fullPage: false });

  await page.setViewportSize(NARROW);
  await page.waitForTimeout(150);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );

  report.pages.push({
    id: target.id,
    desktopShot,
    phoneShot,
    structure,
    axeViolations: violations,
    overflowAt320: overflow,
  });

  await context.close();
}

await browser.close();
writeFileSync(path.join(job.outDir, "probe.json"), `${JSON.stringify(report, null, 2)}\n`);
process.stdout.write(`${JSON.stringify(report)}\n`);

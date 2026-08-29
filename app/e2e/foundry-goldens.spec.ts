import { readFile } from "node:fs/promises";

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const OWNED_APPS = [
  ["sourdough-lab", "Sourdough Lab"],
  ["card-collector", "Card Collector"],
  ["japanese-study-coach", "Japanese Study Coach"],
] as const;

test("foundry golden: evidence → model → exact owned app", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Foundry", exact: true }).click();
  await expect(page).toHaveURL(/\/foundry$/);
  await expect(page.getByRole("heading", { name: "Build around the practice, not the prompt." })).toBeVisible();

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(
    accessibility.violations.filter((item) => ["serious", "critical"].includes(item.impact ?? "")),
  ).toEqual([]);

  await page.getByRole("button", { name: /Sourdough Lab/ }).click();
  await expect(page.getByRole("heading", { name: "Sourdough Lab" })).toBeVisible();
  await expect(page.getByText("6 domain entities")).toBeVisible();
  await expect(page.getByText(/relationship/).first()).toBeVisible();
  await page.getByRole("button", { name: "Open the exact compiled app" }).click();

  const ownedApp = page.frameLocator('iframe[title="Sourdough Lab application"]');
  await expect(ownedApp.getByRole("heading", { name: "Sourdough Lab", exact: true }).first()).toBeVisible();
  await ownedApp.getByRole("button", { name: "Why this app" }).click();
  await expect(ownedApp.getByRole("dialog").getByRole("heading", { name: "Why this app" })).toBeVisible();
  await ownedApp.getByRole("button", { name: "Close" }).click();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: /Owned app/ })).toBeVisible();
  const hasHorizontalPageScroll = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(hasHorizontalPageScroll).toBe(false);
});

for (const [id, title] of OWNED_APPS) {
  test(`owned golden app: ${title} passes its accessible local shell`, async ({ page }) => {
    const response = await page.request.get(`/api/foundry/goldens/${id}`);
    expect(response.ok()).toBe(true);
    const spec = await response.json();
    await page.goto("/");
    await page.setContent(spec.owned_app_html, { waitUntil: "load" });

    await expect(page.getByRole("heading", { name: title, exact: true }).first()).toBeVisible();

    if (id === "sourdough-lab") {
      await expect(page.locator(".kind-chart svg")).toHaveCount(1);
      await page.getByRole("button", { name: "Experiment Table", exact: true }).click();
      await expect(page.locator(".kind-comparison table")).toHaveCount(1);
    } else if (id === "card-collector") {
      await expect(page.locator(".kind-canvas .slot")).toHaveCount(8);
    } else {
      const session = page.locator(".kind-session");
      await expect(session.locator(".cue")).toBeVisible();
      await session.getByRole("button", { name: "Reveal answer" }).click();
      await expect(session.locator(".session-answer")).toBeVisible();
      await expect(page.getByRole("status")).toContainText("No review outcome was recorded");
    }

    await page.getByRole("button", { name: "Why this app" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByRole("button", { name: "Close" }).click();

    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(
      accessibility.violations.filter((item) => ["serious", "critical"].includes(item.impact ?? "")),
    ).toEqual([]);

    await page.setViewportSize({ width: 320, height: 800 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
      ),
    ).toBe(false);
  });

  test(`owned golden backup: ${title} preserves data, receipts, and derivations`, async ({
    page,
  }) => {
    const response = await page.request.get(`/api/foundry/goldens/${id}`);
    expect(response.ok()).toBe(true);
    const spec = await response.json();
    await page.goto("/");
    await page.setContent(spec.owned_app_html, { waitUntil: "load" });

    await page.locator('[data-operation="create"]').first().click();
    const dialog = page.locator("#capture-dialog");
    await expect(dialog).toBeVisible();

    const required = dialog.locator("input[required], select[required], textarea[required]");
    for (let index = 0; index < (await required.count()); index += 1) {
      const control = required.nth(index);
      const tag = await control.evaluate((element) => element.tagName.toLowerCase());
      const type = await control.getAttribute("type");
      if (tag === "select") {
        await control.selectOption({ index: 1 });
      } else if (type === "number") {
        await control.fill("1");
      } else if (type === "date") {
        await control.fill("2026-08-19");
      } else if (type === "datetime-local") {
        await control.fill("2026-08-19T12:00");
      } else {
        await control.fill(`Release proof ${index + 1}`);
      }
    }
    await dialog.getByRole("button", { name: /^Save / }).click();
    await expect(page.getByRole("status")).toContainText("saved locally");

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Export backup" }).click(),
    ]);
    expect(download.suggestedFilename()).toBe(`${id}-backup.json`);
    const path = await download.path();
    expect(path).not.toBeNull();
    const payload = JSON.parse(await readFile(path!, "utf-8")) as {
      spec_id: string;
      spec_version: string;
      exported_at: string;
      records: Record<string, Array<Record<string, unknown>>>;
      receipts: Array<{ object_uid: string; spec_id: string }>;
      derivations: Array<{ output_path: string }>;
      foundry_spec: { id: string };
      evidence: { sources: Array<{ id: string }> };
    };
    expect(payload.spec_id).toBe(id);
    expect(payload.spec_version).toBe(spec.spec_version);
    expect(Number.isNaN(Date.parse(payload.exported_at))).toBe(false);
    const exportedRecords = Object.values(payload.records).flat();
    expect(exportedRecords).toHaveLength(1);
    expect(payload.receipts).toHaveLength(1);
    expect(payload.receipts[0].spec_id).toBe(id);
    expect(payload.receipts[0].object_uid).toBe(exportedRecords[0].object_uid);
    expect(payload.derivations.length).toBeGreaterThan(0);
    expect(payload.foundry_spec.id).toBe(id);
    expect(payload.evidence.sources.length).toBeGreaterThan(0);
    await expect(page.getByRole("status")).toContainText("history, receipts, spec, and evidence");
  });
}

// Lane B: the spec's experience fields reach pixels. Each golden asks for a
// different layout, type stack, density and set of signature elements, so the
// three apps have to come out structurally different, not just recoloured.

const TOPOLOGY_SHAPE = {
  hub: ".hub-overview .hub-card",
  workflow: ".workflow-track .workflow-stage",
  split: ".split .split-detail",
  canvas: ".canvas-board .canvas-tile",
  session: ".session-stage",
} as const;

const EXPECTED_LOOK = {
  "sourdough-lab": {
    topology: "hub",
    density: "bench",
    typeStack: "rounded_humanist",
    signatures: [".signature-comparison", ".signature-timeline"],
  },
  "card-collector": {
    topology: "split",
    density: "dense",
    typeStack: "data_sans",
    signatures: [".signature-gap-grid"],
  },
  "japanese-study-coach": {
    topology: "session",
    density: "airy",
    typeStack: "reading_serif",
    signatures: [".signature-progress", ".signature-timeline"],
  },
} as const;

for (const [id, title] of OWNED_APPS) {
  test(`owned golden app: ${title} renders its own layout, type, density and motifs`, async ({
    page,
  }) => {
    const expected = EXPECTED_LOOK[id];
    const response = await page.request.get(`/api/foundry/goldens/${id}`);
    expect(response.ok()).toBe(true);
    const spec = await response.json();
    await page.goto("/");
    await page.setContent(spec.owned_app_html, { waitUntil: "load" });

    await expect(page.locator("body")).toHaveAttribute("data-topology", expected.topology);
    await expect(page.locator("body")).toHaveAttribute("data-density", expected.density);
    await expect(page.locator("body")).toHaveAttribute("data-type-stack", expected.typeStack);

    // The layout for this topology, and only this topology.
    expect(await page.locator(TOPOLOGY_SHAPE[expected.topology]).count()).toBeGreaterThan(0);
    for (const [name, selector] of Object.entries(TOPOLOGY_SHAPE)) {
      if (name === expected.topology) continue;
      expect(await page.locator(selector).count()).toBe(0);
    }

    for (const selector of expected.signatures) {
      await expect(page.locator(selector).first()).toBeVisible();
    }

    // The type stack and the density both reach the page, not just the markup.
    const applied = await page.evaluate(() => {
      const root = getComputedStyle(document.documentElement);
      return {
        font: root.fontFamily,
        rootSize: root.fontSize,
        gap: root.getPropertyValue("--gap").trim(),
      };
    });
    expect(applied.font.length).toBeGreaterThan(0);
    expect(applied.gap.length).toBeGreaterThan(0);

    // Regions carry the order the spec's small-screen sentence asked for.
    const orders = await page.evaluate(() =>
      [...document.querySelectorAll(".region")].map((element) =>
        (element as HTMLElement).style.getPropertyValue("--collapse-order").trim(),
      ),
    );
    expect(orders.every((value) => value !== "")).toBe(true);

    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(
      accessibility.violations.filter((item) => ["serious", "critical"].includes(item.impact ?? "")),
    ).toEqual([]);

    await page.setViewportSize({ width: 320, height: 800 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
      ),
    ).toBe(false);
  });
}

// No golden asks for workflow or canvas yet, so these two are checked by
// pointing a golden's build at them. Only the DOM shape is asserted: the
// stylesheet in a real build carries the layout for its own topology.
for (const topology of ["workflow", "canvas"] as const) {
  test(`owned app topology: ${topology} builds its own structure`, async ({ page }) => {
    const response = await page.request.get("/api/foundry/goldens/sourdough-lab");
    expect(response.ok()).toBe(true);
    const spec = await response.json();
    const patched = (spec.owned_app_html as string).replaceAll(
      '"topology": "hub"',
      `"topology": "${topology}"`,
    );
    await page.goto("/");
    await page.setContent(patched, { waitUntil: "load" });

    expect(await page.locator(TOPOLOGY_SHAPE[topology]).count()).toBeGreaterThan(0);
    expect(await page.locator(TOPOLOGY_SHAPE.hub).count()).toBe(0);
    await expect(page.getByRole("heading", { name: "Sourdough Lab", exact: true }).first()).toBeVisible();
  });
}

test("two goldens for different interests come out structurally different", async ({ page }) => {
  const shapes: Array<{ id: string; look: string; skeleton: string }> = [];
  for (const id of ["card-collector", "japanese-study-coach"]) {
    const response = await page.request.get(`/api/foundry/goldens/${id}`);
    expect(response.ok()).toBe(true);
    const spec = await response.json();
    await page.goto("/");
    await page.setContent(spec.owned_app_html, { waitUntil: "load" });
    const shape = await page.evaluate(() => {
      const body = document.body;
      const skeleton = [...document.querySelectorAll("#app *")]
        .slice(0, 60)
        .map((element) => `${element.tagName.toLowerCase()}.${element.className}`)
        .join("|");
      return {
        look: [
          body.dataset.topology,
          body.dataset.density,
          body.dataset.typeStack,
          [...document.querySelectorAll(".signature")].map((item) => item.className).join(","),
        ].join(" "),
        skeleton,
      };
    });
    shapes.push({ id, ...shape });
  }
  expect(shapes[0].look).not.toBe(shapes[1].look);
  expect(shapes[0].skeleton).not.toBe(shapes[1].skeleton);
});

test("owned app corrections preserve history and restore into the exact spec", async ({ page }) => {
  const response = await page.request.get("/api/foundry/goldens/sourdough-lab");
  expect(response.ok()).toBe(true);
  const spec = await response.json();
  await page.goto("/");
  await page.setContent(spec.owned_app_html, { waitUntil: "load" });

  await page.getByRole("button", { name: "Feed now" }).click();
  const create = page.locator("#capture-dialog");
  const required = create.locator("input[required], select[required], textarea[required]");
  for (let index = 0; index < (await required.count()); index += 1) {
    const control = required.nth(index);
    const tag = await control.evaluate((element) => element.tagName.toLowerCase());
    const type = await control.getAttribute("type");
    if (tag === "select") await control.selectOption({ index: 1 });
    else if (type === "number") await control.fill("1");
    else if (type === "datetime-local") await control.fill("2026-08-20T09:00");
    else await control.fill(`Correction proof ${index + 1}`);
  }
  await create.getByRole("button", { name: "Save feeding" }).click();

  await page.getByRole("button", { name: "Correct feeding" }).click();
  const correction = page.locator("#capture-dialog");
  await correction.locator('[name="flour_mass_g"]').fill("2");
  await correction.getByRole("button", { name: "Save correction" }).click();
  await expect(page.getByRole("status")).toContainText("prior version remains");

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export backup" }).click(),
  ]);
  const path = await download.path();
  expect(path).not.toBeNull();
  const payload = JSON.parse(await readFile(path!, "utf-8"));
  const versions = payload.records.feeding;
  expect(versions).toHaveLength(2);
  expect(versions[0]._superseded_by).toBe(versions[1]._record_uid);
  expect(versions[1]._supersedes).toBe(versions[0]._record_uid);
  expect(payload.receipts.map((receipt: { operation: string }) => receipt.operation)).toEqual([
    "create",
    "correct",
  ]);
  expect(
    payload.active_records.feeding.filter(
      (record: { object_uid: string }) => record.object_uid === versions[0].object_uid,
    ),
  ).toEqual([expect.objectContaining({ flour_mass_g: 2 })]);

  await page.evaluate(() => localStorage.clear());
  await page.setContent(spec.owned_app_html, { waitUntil: "load" });
  page.once("dialog", (dialog) => dialog.accept());
  await page.locator("#restore-file").setInputFiles(path!);
  await expect(page.getByRole("status")).toContainText("Backup restored");
  expect(
    await page.evaluate(() => {
      const key = Object.keys(localStorage).find((item) => item.startsWith("foundry-app:"));
      return key ? JSON.parse(localStorage.getItem(key) || "{}").records.feeding.length : 0;
    }),
  ).toBe(2);
});

test("owned app restore rejects foreign state and renders imported text inertly", async ({ page }) => {
  const response = await page.request.get("/api/foundry/goldens/japanese-study-coach");
  expect(response.ok()).toBe(true);
  const spec = await response.json();
  await page.goto("/");
  await page.setContent(spec.owned_app_html, { waitUntil: "load" });

  const foreign = {
    backup_format: "foundry-owned-app",
    runtime_schema_version: 2,
    spec_id: "another-app",
    spec_version: "1.0",
    store: { records: {}, receipts: [], sample_overrides: {} },
  };
  await page.locator("#restore-file").setInputFiles({
    name: "foreign.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(foreign)),
  });
  await expect(page.getByRole("alert")).toContainText("another-app");
  expect(await page.evaluate(() => localStorage.length)).toBe(0);

  const cue = '<img src=x onerror="window.__foundryPwned=true">見守る';
  const owned = {
    backup_format: "foundry-owned-app",
    runtime_schema_version: 2,
    spec_id: "japanese-study-coach",
    spec_version: "1.0",
    store: {
      records: {
        prompt: [
          {
            prompt_id: "prompt-imported-security",
            note_id: "note-mimamoru",
            direction: "recognition",
            cue,
            answer: "to watch over",
            phase: "review",
            created_at: "2026-08-20T10:00:00-10:00",
            object_uid: "prompt-security-object",
            captured_at: "2026-08-20T10:00:00-10:00",
            updated_at: "2026-08-20T10:00:00-10:00",
            _record_uid: "prompt-security-version-1",
            _version: 1,
          },
        ],
      },
      receipts: [],
      sample_overrides: {},
    },
  };
  page.once("dialog", (dialog) => dialog.accept());
  await page.locator("#restore-file").setInputFiles({
    name: "owned.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(owned)),
  });
  await expect(page.getByRole("status")).toContainText("Backup restored");
  await expect(page.locator(".cue")).toHaveText(cue);
  expect(await page.locator(".cue img").count()).toBe(0);
  expect(await page.evaluate(() => (window as typeof window & { __foundryPwned?: boolean }).__foundryPwned)).toBeUndefined();
});

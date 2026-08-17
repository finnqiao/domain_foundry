import { defineConfig } from "@playwright/test";

// Chromium-only: one engine, deterministic CI. The webServer script builds a
// hermetic DOMAIN_FOUNDRY_HOME and serves the built SPA from FastAPI —
// exactly what `domain-foundry serve` ships — so this suite tests the real
// artifact, not the Vite dev server.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  // The hermetic server owns one DOMAIN_FOUNDRY_HOME per run, so tests must
  // not mutate the same ledger and pack directory concurrently.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://127.0.0.1:8790",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
  webServer: {
    command: "bash ../scripts/e2e_server.sh",
    url: "http://127.0.0.1:8790/health",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});

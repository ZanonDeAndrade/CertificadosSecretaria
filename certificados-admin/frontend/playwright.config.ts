import { defineConfig, devices } from "@playwright/test";

/**
 * E2E configuration.
 *
 * Both servers are started by Playwright itself so `npx playwright test` is a
 * single command: a mock admin API (no database or Drive credentials needed)
 * and a static server for the built SPA that performs the history fallback real
 * deployments do.
 */
export default defineConfig({
  testDir: "./e2e/specs",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 30_000,
  use: {
    baseURL: "http://localhost:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "mobile", use: { ...devices["Pixel 5"] } },
  ],
  webServer: [
    {
      command: "node e2e/mock-api.mjs",
      port: 8000,
      reuseExistingServer: true,
      stdout: "ignore",
    },
    {
      command: "node e2e/serve-dist.mjs",
      port: 4173,
      reuseExistingServer: true,
      stdout: "ignore",
    },
  ],
});

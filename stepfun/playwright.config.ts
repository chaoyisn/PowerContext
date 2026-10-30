import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 300_000,
  workers: 1,
  expect: { timeout: 15_000 },
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:5174",
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "node scripts/dev.mjs",
    url: "http://127.0.0.1:5174",
    timeout: 60_000,
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    { name: "edge", use: { browserName: "chromium", channel: "msedge" } },
    { name: "chrome", use: { browserName: "chromium", channel: "chrome" } },
  ],
});

import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "live-integration.spec.ts",
  outputDir: "../output/playwright/live-results",
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
  },
  projects: [{ name: "live-desktop", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "node e2e/support/start-live-backend.mjs",
      cwd: ".",
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: false,
    },
    {
      command: "pnpm dev --host 127.0.0.1 --port 5173",
      cwd: ".",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: false,
    },
  ],
});

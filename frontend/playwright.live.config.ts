import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "live-integration.spec.ts",
  outputDir: "../output/playwright/live-results",
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:5180",
    trace: "retain-on-failure",
  },
  projects: [{ name: "live-desktop", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "TAME_INK_E2E_API_PORT=8010 node e2e/support/start-live-backend.mjs",
      cwd: ".",
      url: "http://127.0.0.1:8010/api/health",
      reuseExistingServer: false,
    },
    {
      command: "TAME_INK_API_TARGET=http://127.0.0.1:8010 pnpm dev --host 127.0.0.1 --port 5180 --strictPort",
      cwd: ".",
      url: "http://127.0.0.1:5180",
      reuseExistingServer: false,
    },
  ],
});

import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/web.spec.ts",
  timeout: 45000,
  fullyParallel: false,
  use: { baseURL: "http://127.0.0.1:8765", trace: "retain-on-failure" },
  projects: [
    {
      name: "desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 1000 },
      },
    },
    {
      name: "mobile",
      use: { ...devices["iPhone 13"], defaultBrowserType: "chromium" },
    },
  ],
  webServer: {
    command:
      "python -m uvicorn services.api.main:app --host 127.0.0.1 --port 8765",
    url: "http://127.0.0.1:8765/v1/health",
    reuseExistingServer: false,
  },
});

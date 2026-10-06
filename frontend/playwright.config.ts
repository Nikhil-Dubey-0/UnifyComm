import { defineConfig, devices } from "@playwright/test";

const API = process.env.API_URL ?? "http://localhost:8000";
const WEB = process.env.WEB_URL ?? "http://localhost:3000";
const reuse = !process.env.CI;

export default defineConfig({
  testDir: "./src/e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: WEB,
    // The installed Microsoft Edge avoids a browser download on the dev laptop.
    channel: process.env.PW_CHANNEL ?? "msedge",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "edge", use: { ...devices["Desktop Edge"], viewport: { width: 1440, height: 900 } } }],
  // Reuses already-running processes; otherwise starts the api, worker and web app.
  webServer: [
    {
      command: "uv run uvicorn app.main:app --port 8000",
      cwd: "../backend",
      url: `${API}/api/health`,
      reuseExistingServer: reuse,
      timeout: 60_000,
    },
    {
      command: "uv run python -m app.worker",
      cwd: "../backend",
      url: `${API}/api/health`,
      reuseExistingServer: reuse,
      timeout: 60_000,
    },
    {
      command: "npm run dev",
      url: `${WEB}/login`,
      reuseExistingServer: reuse,
      timeout: 120_000,
    },
  ],
});

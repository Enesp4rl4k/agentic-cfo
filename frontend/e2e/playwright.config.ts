import { defineConfig, devices } from "@playwright/test";

/**
 * Browser test of the pilot's core flow, against the real stack.
 *
 * Starts (or, locally, attaches to) the API on SQLite and the Next.js app. There is no LLM key,
 * no Redis, no SMTP: the product's deterministic paths answer, and the e-mail outbox is read, not
 * delivered. One worker, Chromium only: the journey is one story told in order.
 *
 * CI builds the frontend first (`npm run build`) and runs `next start`; locally `next dev` is used
 * unless E2E_FRONTEND_MODE=start. E2E_REUSE=1 attaches to servers that are already up.
 */
const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const reuse = process.env.E2E_REUSE === "1";
const frontendCommand =
  process.env.E2E_FRONTEND_MODE === "start" || process.env.CI
    ? "npx next start -p 3000"
    : "npx next dev -p 3000";

export default defineConfig({
  testDir: ".",
  testMatch: /.*\.spec\.ts/,
  outputDir: "../test-results",
  timeout: 15 * 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: process.env.CI
    ? [["list"], ["html", { outputFolder: "../playwright-report", open: "never" }]]
    : [["list"]],
  use: {
    baseURL: WEB,
    locale: "tr-TR",
    timezoneId: "Europe/Istanbul",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 20_000,
    navigationTimeout: 60_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "python e2e/support/llm_stub.py",
      cwd: "..",
      url: "http://127.0.0.1:8099",
      reuseExistingServer: reuse,
      timeout: 120_000,
    },
    {
      command: "python e2e/support/start_backend.py",
      cwd: "..",
      url: `${API}/api/v1/system/health`,
      reuseExistingServer: reuse,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      // The same API with a model behind it, on its own port, for the one step that needs one.
      command: "python e2e/support/start_backend.py",
      cwd: "..",
      url: "http://localhost:8001/api/v1/system/health",
      reuseExistingServer: reuse,
      timeout: 300_000,
      env: { E2E_WITH_MODEL: "1", E2E_API_PORT: "8001" },
    },
    {
      command: frontendCommand,
      cwd: "..",
      url: `${WEB}/auth/login`,
      reuseExistingServer: reuse,
      timeout: 240_000,
      env: {
        NEXTAUTH_URL: WEB,
        NEXTAUTH_SECRET: process.env.NEXTAUTH_SECRET ?? "e2e-nextauth-throwaway-secret-0123456789abcdef",
        NEXT_PUBLIC_API_URL: API,
        NEXT_TELEMETRY_DISABLED: "1",
      },
    },
  ],
});

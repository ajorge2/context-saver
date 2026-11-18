import { defineConfig } from "@playwright/test";
import path from "node:path";

export default defineConfig({
  testDir: ".",
  testMatch: "*.spec.js",
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  outputDir: path.join(process.env.CONTEXT_SAVER_TEST_REPORTS || "test-results", "browser"),
  use: {
    browserName: "chromium",
    viewport: { width: 1280, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});

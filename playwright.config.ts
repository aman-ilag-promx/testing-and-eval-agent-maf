import { defineConfig, devices } from "@playwright/test";
import dotenv from "dotenv";
import path from "node:path";
import { fileURLToPath } from "node:url";

const currentFilePath = fileURLToPath(import.meta.url);
const projectRoot = path.dirname(currentFilePath);

dotenv.config({
  path: path.resolve(projectRoot, ".env"),
});

function parseBoolean(value: string | undefined, defaultValue: boolean): boolean {
  if (value === undefined || value.trim() === "") {
    return defaultValue;
  }

  const normalizedValue = value.trim().toLowerCase();

  if (normalizedValue === "true") {
    return true;
  }

  if (normalizedValue === "false") {
    return false;
  }

  throw new Error(
    `Invalid boolean environment variable value: "${value}". Expected "true" or "false".`,
  );
}

function parsePositiveInteger(
  value: string | undefined,
  defaultValue: number,
  variableName: string,
): number {
  if (value === undefined || value.trim() === "") {
    return defaultValue;
  }

  const parsedValue = Number.parseInt(value, 10);

  if (!Number.isInteger(parsedValue) || parsedValue <= 0) {
    throw new Error(
      `${variableName} must be a positive integer. Received: "${value}".`,
    );
  }

  return parsedValue;
}

function parseNonNegativeInteger(
  value: string | undefined,
  defaultValue: number,
  variableName: string,
): number {
  if (value === undefined || value.trim() === "") {
    return defaultValue;
  }

  const parsedValue = Number.parseInt(value, 10);

  if (!Number.isInteger(parsedValue) || parsedValue < 0) {
    throw new Error(
      `${variableName} must be a non-negative integer. Received: "${value}".`,
    );
  }

  return parsedValue;
}

function getBrowserProject(browserName: string) {
  switch (browserName.trim().toLowerCase()) {
    case "chromium":
      return {
        name: "chromium",
        use: {
          ...devices["Desktop Chrome"],
        },
      };

    case "firefox":
      return {
        name: "firefox",
        use: {
          ...devices["Desktop Firefox"],
        },
      };

    case "webkit":
      return {
        name: "webkit",
        use: {
          ...devices["Desktop Safari"],
        },
      };

    default:
      throw new Error(
        `Unsupported PLAYWRIGHT_BROWSER value: "${browserName}". ` +
          'Supported values are "chromium", "firefox", and "webkit".',
      );
  }
}

const baseURL = process.env.TARGET_BASE_URL?.trim() || "http://localhost:3000";

const headless = parseBoolean(process.env.PLAYWRIGHT_HEADLESS, true);

const timeout = parsePositiveInteger(
  process.env.PLAYWRIGHT_TIMEOUT_MS,
  30_000,
  "PLAYWRIGHT_TIMEOUT_MS",
);

const expectTimeout = parsePositiveInteger(
  process.env.PLAYWRIGHT_EXPECT_TIMEOUT_MS,
  5_000,
  "PLAYWRIGHT_EXPECT_TIMEOUT_MS",
);

const retries = parseNonNegativeInteger(
  process.env.PLAYWRIGHT_RETRIES,
  0,
  "PLAYWRIGHT_RETRIES",
);

const workers = parsePositiveInteger(
  process.env.PLAYWRIGHT_WORKERS,
  1,
  "PLAYWRIGHT_WORKERS",
);

const saveScreenshotsOnFailure = parseBoolean(
  process.env.SAVE_SCREENSHOTS_ON_FAILURE,
  true,
);

const saveTraceOnFailure = parseBoolean(
  process.env.SAVE_TRACE_ON_FAILURE,
  true,
);

const saveVideoOnFailure = parseBoolean(
  process.env.SAVE_VIDEO_ON_FAILURE,
  false,
);

const browserName = process.env.PLAYWRIGHT_BROWSER?.trim() || "chromium";

export default defineConfig({
  testDir: path.resolve(projectRoot, "tests"),

  testMatch: [
    "smoke/**/*.spec.ts",
    "integration/**/*.spec.ts",
    "ui/**/*.spec.ts",
  ],

  testIgnore: [
    "generated/**/*.spec.ts",
    "**/*.draft.spec.ts",
  ],

  outputDir: path.resolve(projectRoot, "test-results"),

  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries,
  workers,

  timeout,

  expect: {
    timeout: expectTimeout,
  },

  reporter: [
    ["list"],
    [
      "html",
      {
        outputFolder: path.resolve(projectRoot, "playwright-report"),
        open: "never",
      },
    ],
    [
      "json",
      {
        outputFile: path.resolve(
          projectRoot,
          "reports",
          "playwright-results.json",
        ),
      },
    ],
  ],

  use: {
    baseURL,
    headless,

    actionTimeout: timeout,
    navigationTimeout: timeout,

    screenshot: saveScreenshotsOnFailure ? "only-on-failure" : "off",
    trace: saveTraceOnFailure ? "retain-on-failure" : "off",
    video: saveVideoOnFailure ? "retain-on-failure" : "off",

    ignoreHTTPSErrors: false,

    contextOptions: {
      reducedMotion: "reduce",
    },
  },

  projects: [getBrowserProject(browserName)],
});
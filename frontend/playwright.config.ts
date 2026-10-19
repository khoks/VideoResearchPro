import { defineConfig, devices } from '@playwright/test';

// Device-emulation screenshot tests for the reading pages (S-8.12.1,
// T-8.12.1.4). Hermetic: every /api/v1 call is served from
// tests/fixtures/api, so only the Vite dev server runs. The proxy target is
// a closed port so nothing can reach a real backend by accident.
//
//   npm run test:mobile            # compare with the checked-in baselines
//   npm run test:mobile:update     # re-record them after an intended change
//
// Emulation is not a device: no real keyboard, no Safari chrome, host CPU.
// A pass on one real phone is still part of calling a mobile change done.
const PORT = 5181;

export default defineConfig({
  testDir: './tests',
  // One baseline per project, no OS suffix: they are reviewed as images, and
  // small cross-engine drift is tolerated below.
  snapshotPathTemplate: '{testDir}/__screenshots__/{projectName}/{arg}{ext}',
  fullyParallel: true,
  reporter: [['list']],
  expect: {
    toHaveScreenshot: { maxDiffPixelRatio: 0.02, animations: 'disabled', scale: 'css' },
  },
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `npm run dev -- --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      VITE_API_BASE_URL: '/api/v1',
      VITE_PROXY_TARGET: 'http://127.0.0.1:9',
    },
  },
  projects: [
    // Phone projects: the reading pages and the manifest (S-8.12.x).
    { name: 'iphone-13', testIgnore: /(palette|graph)\.spec\.ts/, use: { ...devices['iPhone 13'] } },
    { name: 'pixel-7', testIgnore: /(palette|graph)\.spec\.ts/, use: { ...devices['Pixel 7'] } },
    // Desktop: the keyboard-driven command palette (S-8.2.2) and the library
    // map's keyboard model (S-8.9.2), which sets its own narrow viewport.
    { name: 'desktop-chromium', testMatch: /(palette|graph)\.spec\.ts/, use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } } },
    {
      name: 'narrow-320',
      testIgnore: /(palette|graph)\.spec\.ts/,
      use: {
        browserName: 'chromium',
        viewport: { width: 320, height: 640 },
        deviceScaleFactor: 2,
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
});

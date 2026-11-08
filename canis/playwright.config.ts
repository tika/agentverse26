import { defineConfig } from '@playwright/test';

// Uses the locally installed Google Chrome (channel "chrome"), so no browser download is needed.
export default defineConfig({
  testDir: 'e2e',
  timeout: 60_000,
  use: { baseURL: 'http://localhost:5178', channel: 'chrome', viewport: { width: 1680, height: 1000 } },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5178',
    reuseExistingServer: true,
    timeout: 60_000,
  },
});

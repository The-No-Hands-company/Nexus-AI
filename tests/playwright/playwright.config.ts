import { defineConfig, devices } from '@playwright/test';

const managedServerCommand = process.env.PLAYWRIGHT_SERVER_COMMAND || '';
const shouldManageServer = process.env.PLAYWRIGHT_MANAGE_SERVER === '1' || Boolean(managedServerCommand);

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [['html', { outputFolder: 'playwright-report' }], ['line']] : 'list',
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8000',
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  ...(shouldManageServer
    ? {
        webServer: {
          command: managedServerCommand || 'python main.py',
          url: process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8000/health',
          reuseExistingServer: true,
          timeout: 90_000,
        },
      }
    : {}),
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});

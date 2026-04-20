# Playwright UI Tests

These tests exercise real browser flows for chat streaming, operator dashboards, and in-browser tooling.

## Local run (existing backend)

1. Start the Nexus AI server:
   python main.py
2. Install Playwright dependencies:
   cd tests/playwright && npm install
3. Install Chromium:
   npx playwright install --with-deps chromium
4. Run tests:
   PLAYWRIGHT_BASE_URL=http://127.0.0.1:8000 npx playwright test

## Managed backend run (CI-friendly)

If you want Playwright to start Nexus automatically, enable managed-server mode:

1. Install dependencies:
   cd tests/playwright && npm install
2. Ensure Python dependencies are available in your shell.
3. Run:
   PLAYWRIGHT_MANAGE_SERVER=1 PLAYWRIGHT_SERVER_COMMAND="python main.py" npm run test:ci

`PLAYWRIGHT_SERVER_COMMAND` can be overridden for custom startup wrappers.

The specs intercept backend requests so they validate browser behavior deterministically without depending on live providers.

File naming follows product behavior, not roadmap or inventory section labels.


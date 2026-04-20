import { test, expect, type Page } from '@playwright/test';

async function bootstrapApp(page: Page) {
  await page.route('**/session', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ session_id: 'pw-session-001' }),
    });
  });

  await page.route('**/providers', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        providers: [{ provider: 'llm7', label: 'LLM7', status: 'healthy', available: true, healthy: true }],
      }),
    });
  });

  await page.route('**/providers/health', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ providers: [{ id: 'llm7', label: 'LLM7', status: 'healthy', cooldown_until: null }] }),
    });
  });

  await page.route('**/safety/profiles', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ active: 'standard', profiles: { standard: {}, strict: {} } }),
    });
  });

  await page.route('**/settings', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          provider: 'auto',
          model: '',
          temperature: 0.2,
          safety_profile: 'standard',
          strict_mode_profile: 'strict',
          strict_no_guess_mode: true,
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, strict_mode_profile: 'strict', provider: 'auto', temperature: 0.2, safety_profile: 'standard' }),
    });
  });

  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForURL('**/');
  await expect(page.locator('#task')).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  await bootstrapApp(page);
});

test('streams chat output progressively in the main conversation view', async ({ page }) => {
  await page.route('**/agent/stream', async (route) => {
    const sse = [
      'data: {"type":"token","in_tokens":2,"out_tokens":0,"elapsed_s":0.1}\n\n',
      'data: {"type":"token_chunk","delta":"Hello "}\n\n',
      'data: {"type":"token_chunk","delta":"world"}\n\n',
      'data: {"type":"done","content":"Hello world","provider":"LLM7","model":"demo","confidence":0.93,"input_tokens":2,"output_tokens":2}\n\n',
    ].join('');
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      headers: {
        'cache-control': 'no-cache',
        connection: 'keep-alive',
      },
      body: sse,
    });
  });

  const streamRequest = page.waitForResponse((response) => response.url().includes('/agent/stream') && response.request().method() === 'POST');
  await page.locator('#task').fill('Say hello');
  await page.locator('#send-btn').click();
  await streamRequest;

  await expect(page.locator('.msg-row.user .bubble')).toContainText('Say hello');
  await expect(page.locator('.msg-row.agent .bubble').last()).toContainText('Hello world');
  await expect(page.locator('#tok-in')).toContainText('2 tokens');
  await expect(page.locator('.confidence-badge').last()).toContainText('93%');
});

test('opens benchmark and fine-tuning dashboards and renders API data', async ({ page }) => {
  await page.route('**/benchmark/results', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        results: [{ provider: 'ollama', model: 'nexus-prime', probe: 'chat', ok: true, latency_ms: 123.4 }],
      }),
    });
  });

  await page.route('**/benchmark/history?limit=200', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        results: [{ provider: 'ollama', model: 'nexus-prime', task_type: 'chat', quality_score: 0.92, latency_ms: 130.1 }],
        summary: { avg_latency_ms: 130.1, trend: 'up' },
      }),
    });
  });

  await page.route('**/finetune/jobs?limit=200', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        count: 1,
        items: [{ id: 'ftjob-1', status: 'queued', model: 'nexus-prime', training_file: 'file-1', created_at: 'now', finished_at: '' }],
      }),
    });
  });

  await page.locator('#overflow-btn').click();
  await page.getByRole('button', { name: /model benchmark dashboard/i }).click();
  await expect(page.locator('#benchmark-dashboard-panel')).toBeVisible();
  await expect(page.locator('#bd-latest')).toContainText('nexus-prime');

  await page.locator('#overflow-btn').click();
  await page.getByRole('button', { name: /fine-tuning jobs/i }).click();
  await expect(page.locator('#finetune-dashboard-panel')).toBeVisible();
  await expect(page.locator('#ft-rows')).toContainText('ftjob-1');
});

test('opens corpus and admin workflows and executes sandboxed code', async ({ page }) => {
  await page.route('**/rag/documents?limit=300', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        count: 1,
        items: [{ id: 'doc-1', preview: 'Corpus preview', metadata: { source: 'spec-doc.md', org_id: 'org-1' } }],
      }),
    });
  });

  await page.route('**/admin/users', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ users: [{ username: 'admin', role: 'admin', email: 'admin@example.com' }] }),
    });
  });

  await page.route('**/admin/quota', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [{ username: 'admin', daily_limit_tokens: 1000, weekly_limit_tokens: 7000, monthly_limit_tokens: 30000 }] }),
    });
  });

  await page.route('**/usage?days=7', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ per_user: [{ username: 'admin', calls: 3, in_tok: 20, out_tok: 40, cost_usd: 0.1234 }] }),
    });
  });

  await page.locator('#overflow-btn').click();
  await page.getByRole('button', { name: /rag corpus browser/i }).click();
  await expect(page.locator('#rag-corpus-panel')).toBeVisible();
  await expect(page.locator('#rc-rows')).toContainText('doc-1');

  await page.locator('#overflow-btn').click();
  await page.getByRole('button', { name: /multi-user admin dashboard/i }).click();
  await expect(page.locator('#admin-dashboard-panel')).toBeVisible();
  await expect(page.locator('#ad-users')).toContainText('admin@example.com');

  await page.locator('#overflow-btn').click();
  await page.getByRole('button', { name: /code sandbox runner/i }).click();
  await expect(page.locator('#code-runner-panel')).toBeVisible();
  await page.locator('#cr-code').fill('console.log("sandbox ok")');
  await page.getByRole('button', { name: /^run$/i }).click();
  const frame = page.frameLocator('#cr-frame');
  await expect(frame.locator('#out')).toContainText('sandbox ok');
});
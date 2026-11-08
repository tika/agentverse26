import { expect, test, type Page } from '@playwright/test';

async function noHorizontalScroll(page: Page) {
  const [sw, cw] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(sw).toBeLessThanOrEqual(cw);
}

test.describe('offline framework (default)', () => {
  test('shows FRAMEWORK · OFFLINE with no clock and every feed not configured', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('mode-chip')).toHaveText('FRAMEWORK · OFFLINE');
    await expect(page.getByTestId('elapsed')).toHaveCount(0);
    await expect(page.getByTestId('replay-banner')).toHaveCount(0);
    await expect(page.locator('.feed-chip')).toHaveCount(6);
    for (const chip of await page.locator('.feed-chip').all()) await expect(chip).toContainText('NOT CONFIGURED');
    await expect(page.getByTestId('static-reference')).toContainText('STATIC REFERENCE · NOT LIVE');
  });

  test('keeps sensor and mission fields unavailable', async ({ page }) => {
    await page.goto('/');
    const sensorStates = await page.locator('[data-testid="sensor-table"] [data-state]').evaluateAll((els) => els.map((e) => e.getAttribute('data-state')));
    expect(sensorStates).toEqual(['missing', 'missing', 'missing', 'missing', 'missing', 'not_supplied']);
    await expect(page.getByTestId('robot-status').locator('[data-state="missing"]')).toHaveCount(8);
    await expect(page.getByTestId('mission-progress')).toContainText('0 inspected · 0 seen');
    for (const cam of ['rgb', 'depth', 'lwir']) await expect(page.getByTestId(`camera-${cam}`)).toContainText('no frame');
    await expect(page.getByTestId('alerts-empty')).toBeVisible();
  });

  test('loads all 420 inventory records, uninspected, searchable', async ({ page }) => {
    await page.goto('/?tab=inspection');
    await expect(page.getByTestId('inventory-count')).toContainText('420 drums · 0 inspected · 0 seen');
    await expect(page.locator('[data-testid="drum-table"] tbody tr')).toHaveCount(420);
    await expect(page.locator('[data-testid="drum-table"] tbody td.ist-unseen')).toHaveCount(420);
    await page.getByLabel('Search by drum ID or printed location code').fill('A-L-01-T1');
    await expect(page.locator('[data-testid="drum-table"] tbody tr').first()).toContainText('D01');
    await page.getByLabel('Search by drum ID or printed location code').fill('');
    await page.getByLabel('Waste class').selectOption('ILW');
    await expect(page.getByTestId('row-count')).toHaveText('84 shown');
    await page.getByLabel('Tier').selectOption('2');
    await expect(page.getByTestId('row-count')).toHaveText('28 shown');
  });

  test('drum detail separates inventory, observations, evidence and assessment', async ({ page }) => {
    await page.goto('/?tab=inspection');
    await page.locator('[data-testid="drum-table"] tbody tr', { hasText: 'D01' }).first().click();
    const detail = page.getByTestId('drum-detail');
    await expect(detail).toContainText('1 · Known inventory');
    await expect(detail).toContainText('2 · Observations');
    await expect(detail).toContainText('3 · Supporting evidence');
    await expect(detail).toContainText('4 · Findings & assessments');
    await expect(detail).toContainText('/World/Drums/D01');
    await expect(detail).toContainText('no assessment service connected');
  });

  test('map stack selection resolves the tier', async ({ page }) => {
    await page.goto('/?tab=inspection');
    await page.locator('g.stack').first().click();
    const picker = page.getByRole('dialog', { name: 'Choose tier' });
    await expect(picker.locator('.tier-btn')).toHaveCount(3);
    await picker.locator('.tier-btn', { hasText: 'T3' }).click();
    await expect(page.getByTestId('drum-detail')).toContainText('T3 of 3');
  });

  test('every tab renders and arrow keys move between tabs', async ({ page }) => {
    await page.goto('/');
    for (const [name, text] of [['Inspection', 'Inspection memory'], ['Sensors', 'Sensor reading history'], ['Alerts', 'Findings'], ['Logs', 'Public map loaded'], ['Simulation', 'Simulation (third-person)']]) {
      await page.getByRole('tab', { name: new RegExp(`^${name}`, 'i') }).click();
      await expect(page.getByRole('tabpanel')).toContainText(text);
    }
    await page.getByRole('tab', { name: /^Simulation/i }).focus();
    await page.keyboard.press('ArrowRight');
    await expect(page.getByRole('tab', { name: /^Inspection/i })).toHaveAttribute('aria-selected', 'true');
  });

  test('logs can be exported without payload values', async ({ page }) => {
    await page.goto('/?tab=logs');
    const download = page.waitForEvent('download');
    await page.getByTestId('export-logs').click();
    const file = await download;
    const text = await (await file.createReadStream()).toArray().then((c) => Buffer.concat(c).toString());
    expect(text).toContain('"category":"map"');
    expect(text).not.toMatch(/physical_inventory|internal_c"/);
  });

  test('narrow layout has no horizontal scroll', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    for (const tab of ['', '?tab=inspection', '?tab=sensors', '?tab=alerts', '?tab=logs']) {
      await page.goto(`/${tab}`);
      await expect(page.locator('.panel').first()).toBeVisible();
      await noHorizontalScroll(page);
    }
  });
});

test.describe('demo replay', () => {
  test('is labelled throughout and demonstrates each state', async ({ page }) => {
    await page.goto('/?mode=replay&tick=60');
    await expect(page.getByTestId('replay-banner')).toContainText('DEMO REPLAY · FICTIONAL FIXTURE DATA');
    await expect(page.getByTestId('mode-chip')).toHaveText('DEMO REPLAY');
    await expect(page.getByTestId('elapsed')).toContainText('REPLAY CLOCK');
    const h2 = page.locator('[data-channel="h2"] [data-state]');
    await expect(h2).toHaveAttribute('data-state', 'below_detection');
    await expect(h2).toContainText('< 2 ppm · BELOW DETECTION');
    await expect(page.locator('[data-channel="dose"] [data-state="stale"]')).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId('replay-banner')).toBeVisible();
    await expect(page.locator('.alert', { hasText: 'PROPOSED · NOT SENT' })).toBeVisible();
    await expect(page.locator('.alert .badge-fixture').first()).toContainText('DEMO FIXTURE');
    await expect(page.locator('[data-channel="dose"] [data-state="value"]')).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId('mission-progress')).toContainText(/\d inspected · \d seen/);
  });

  test('pause, resume and reset are deterministic', async ({ page }) => {
    await page.goto('/?mode=replay&tick=80&at=5');
    // Auto-pauses at t = 5 s and stays there.
    await expect(page.getByRole('button', { name: 'Resume replay' })).toBeVisible();
    await expect(page.getByTestId('elapsed')).toContainText('00:00:05');
    await page.waitForTimeout(500);
    await expect(page.getByTestId('elapsed')).toContainText('00:00:05');
    await page.getByRole('button', { name: 'Resume replay' }).click();
    await expect(page.getByTestId('elapsed')).not.toContainText('00:00:05');
    await page.getByRole('button', { name: 'Pause replay' }).click();
    const paused = await page.getByTestId('elapsed').textContent();
    await page.waitForTimeout(400);
    await expect(page.getByTestId('elapsed')).toHaveText(paused!);
    await page.getByRole('button', { name: 'Reset replay' }).click();
    await expect(page.getByTestId('elapsed')).toContainText('00:00:00');
    await expect(page.getByRole('button', { name: 'Resume replay' })).toBeVisible();
    await page.getByRole('tab', { name: /^Logs/i }).click();
    await expect(page.getByRole('tabpanel')).toContainText('DEMO REPLAY reset to t=0');
  });

  test('switching back to offline clears fixture data', async ({ page }) => {
    await page.goto('/?mode=replay&tick=60');
    await expect(page.getByTestId('mission-progress')).toContainText('seen', { timeout: 10_000 });
    await page.getByLabel('Data mode').selectOption('offline');
    await expect(page.getByTestId('mode-chip')).toHaveText('FRAMEWORK · OFFLINE');
    await expect(page.getByTestId('replay-banner')).toHaveCount(0);
    await expect(page.getByTestId('mission-progress')).toContainText('0 inspected · 0 seen');
    await expect(page.getByTestId('elapsed')).toHaveCount(0);
  });
});

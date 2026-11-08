import { test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

// Run from canis/ (npm run screenshots).
const out = resolve(process.cwd(), '../docs/canis/screenshots');
mkdirSync(out, { recursive: true });

test.describe('handoff screenshots', () => {
  test.skip(!process.env.CANIS_SCREENSHOTS, 'set CANIS_SCREENSHOTS=1 (npm run screenshots)');

  test('desktop offline', async ({ page }) => {
    await page.setViewportSize({ width: 1680, height: 1050 });
    await page.goto('/');
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${out}/desktop-offline.png`, fullPage: true });
  });

  test('desktop replay', async ({ page }) => {
    await page.setViewportSize({ width: 1680, height: 1050 });
    await page.goto('/?mode=replay&tick=40&at=28');
    await page.getByRole('button', { name: 'Resume replay' }).waitFor({ timeout: 20_000 });
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${out}/desktop-replay.png`, fullPage: true });
  });

  test('desktop inspection with drum detail', async ({ page }) => {
    await page.setViewportSize({ width: 1680, height: 1050 });
    await page.goto('/?tab=inspection');
    await page.locator('[data-testid="drum-table"] tbody tr', { hasText: 'D01' }).first().click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${out}/desktop-inspection-detail.png` });
  });

  test('narrow offline', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${out}/narrow-offline.png`, fullPage: true });
  });

  test('narrow replay', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/?mode=replay&tick=40&at=36');
    await page.getByRole('button', { name: 'Resume replay' }).waitFor({ timeout: 20_000 });
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${out}/narrow-replay.png`, fullPage: true });
  });
});

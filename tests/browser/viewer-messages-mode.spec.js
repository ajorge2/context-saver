import { test, expect } from '@playwright/test';
import { appOrigin, getViewerFixtureAsset } from './viewer-fixture-assets.js';

test.use({ reducedMotion: 'reduce', serviceWorkers: 'block' });

function payload(query = '', filters = []) {
  const layers = Object.fromEntries(['subject', 'broad_topic', 'specific_topic'].map((layer, index) => [layer,
    ['Alpha', 'Beta'].map((name) => ({ id: `${name}-${index}`, layer, title: `${name} ${layer}` })),
  ]));
  layers.specific_message = ['Alpha', 'Beta']
    .filter((name) => filters.every((id) => id.startsWith(name)))
    .map((name) => ({ id: `message:${name}`, layer: 'specific_message', title: `${name} saved message` }));
  return {
    query, project: { id: 'project-one', title: 'Project One' }, layers,
    edges: ['Alpha', 'Beta'].flatMap((name) => [
      { child_id: `${name}-1`, parent_id: `${name}-0` },
      { child_id: `${name}-2`, parent_id: `${name}-1` },
      { child_id: `message:${name}`, parent_id: `${name}-2` },
    ]),
    messagePage: query ? null : { offset: 0, limit: 36, total: layers.specific_message.length, hasNext: false, hasPrevious: false },
  };
}

async function boot(page, delayedSearch) {
  const requests = [];
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    const asset = getViewerFixtureAsset(url);
    if (asset) return route.fulfill({ path: asset });
    if (url.origin !== appOrigin) return route.abort();
    if (url.pathname === '/api/threads') return route.fulfill({ json: [{ id: 'project-one', title: 'Project One' }] });
    if (url.pathname === '/api/connections/refresh-status') return route.fulfill({ json: { state: 'idle' } });
    if (url.pathname === '/favicon.ico') return route.fulfill({ status: 204 });
    if (url.pathname === '/api/explore') {
      const query = url.searchParams.get('q') || '';
      const filters = url.searchParams.getAll('browse_node');
      requests.push({ query, filters });
      if (query && delayedSearch) await delayedSearch;
      return route.fulfill({ json: payload(query, filters) });
    }
    return route.abort();
  });
  await page.goto(appOrigin);
  await expect(page.locator('[data-hero-combobox] .combobox-option')).toHaveCount(1);
  if (await page.locator('[data-hero-combobox] [data-combobox-value]').textContent() !== 'Project One') {
    await page.getByRole('combobox', { name: 'Select project', exact: true }).click();
    await page.getByRole('option', { name: 'Project One', exact: true }).click();
  }
  await expect(section(page, 4).locator('.feature-card')).toHaveCount(2);
  return requests;
}

const toggle = (page) => page.locator('[data-message-search-toggle]');
const search = (page) => page.locator('[data-spotlight-input]');
const hero = (page) => page.locator('.slide-down-button--hero');
const section = (page, index) => page.locator(`[data-section="${index}"]`);
const dot = (page, index) => page.locator(`[data-section-index="${index}"]`);
async function changeMode(page) {
  await currentSlide(page, 0);
  await search(page).focus();
  await toggle(page).click();
}
async function currentSlide(page, index) {
  await expect(dot(page, index)).toHaveClass(/is-active/);
  await expect.poll(() => page.evaluate((target) => Math.abs(
    window.scrollY - document.querySelector(`[data-section="${target}"]`).offsetTop,
  ), index)).toBeLessThan(1);
}

async function expectTwoSlides(page) {
  await expect(page.locator('[data-section]:not([hidden])')).toHaveCount(2);
  await expect(page.getByRole('navigation', { name: 'Page sections' }).getByRole('button')).toHaveCount(2);
  for (const index of [1, 2, 3]) {
    await expect(section(page, index)).toBeHidden();
    await expect(section(page, index)).toHaveJSProperty('inert', true);
  }
}

test('messages-only has two slides with direct arrows, inert semantics and no hidden navigation route', async ({ page }) => {
  await boot(page);
  await changeMode(page);
  await expectTwoSlides(page);
  await expect(hero(page)).toHaveAttribute('data-scroll-to', '4');
  await hero(page).click();
  await currentSlide(page, 4);
  const up = section(page, 4).getByRole('button', { name: 'Go to previous slide', exact: true });
  await expect(up).toHaveAttribute('data-scroll-to', '0');
  await up.click();
  await currentSlide(page, 0);
  await expect.poll(() => page.evaluate(() => document.querySelector('[data-scroll-spacer]').offsetHeight / window.innerHeight)).toBe(2);
  await dot(page, 1).evaluate((button) => button.click());
  await currentSlide(page, 0);
  await section(page, 1).locator('.combobox-trigger').evaluate((button) => button.focus());
  await expect(section(page, 1).locator('.combobox-trigger')).not.toBeFocused();
  for (const key of ['ArrowDown', 'PageDown', 'End', 'Space']) await page.keyboard.press(key);
  await currentSlide(page, 0);
  await changeMode(page);
  await expect(page.locator('[data-section]:not([hidden])')).toHaveCount(5);
  await expect(page.getByRole('navigation', { name: 'Page sections' }).getByRole('button')).toHaveCount(5);
  await expect(hero(page)).toHaveAttribute('data-scroll-to', '1');
  await hero(page).click();
  await currentSlide(page, 1);
  await expect(section(page, 4).locator('.slide-up-button')).toHaveAttribute('data-scroll-to', '3');
});

test('hidden filters clear without submitting a draft or losing committed query and message selection', async ({ page }) => {
  const requests = await boot(page);
  await search(page).fill('release');
  await search(page).press('Enter');
  await expect(hero(page)).toHaveAccessibleName('View results');
  await dot(page, 1).click();
  await section(page, 1).getByRole('button', { name: 'Add Alpha subject filter', exact: true }).click();
  await expect(section(page, 4).locator('.feature-card')).toHaveCount(1);
  await dot(page, 0).click();
  await search(page).fill('unsubmitted revision');
  const before = requests.length;
  await changeMode(page);
  await expect(search(page)).toHaveValue('unsubmitted revision');
  await expect(hero(page)).toHaveAccessibleName('View results');
  await expect(section(page, 4).locator('.feature-card')).toHaveCount(2);
  await expect(section(page, 1).locator('[data-combobox-value]')).toHaveText('Select subject...');
  expect(requests).toHaveLength(before);
  // Navigating away commits the draft and locks navigation until it finishes.
  // Finish that submission explicitly before selecting a message on its slide.
  await search(page).press('Enter');
  await expect(hero(page)).toBeEnabled();
  await expect.poll(() => requests.at(-1)?.query).toBe('unsubmitted revision');
  await dot(page, 4).click();
  await currentSlide(page, 4);
  await section(page, 4).getByRole('button', { name: 'Add Beta saved message filter', exact: true }).click();
  await dot(page, 0).click();
  await changeMode(page);
  await expect(section(page, 4).locator('.feature-card h3')).toHaveText('Beta saved message');
  await expect(section(page, 4).locator('[data-combobox-value]')).toHaveText('Beta saved message');
  await expect(search(page)).toHaveValue('unsubmitted revision');
});

test('entering messages-only reloads browse evidence without its now-hidden topic filter', async ({ page }) => {
  const requests = await boot(page);
  await dot(page, 1).click();
  await section(page, 1).getByRole('button', { name: 'Add Alpha subject filter', exact: true }).click();
  await expect(section(page, 4).locator('.feature-card')).toHaveCount(1);
  await dot(page, 0).click();
  await changeMode(page);
  await expect(section(page, 4).locator('.feature-card')).toHaveCount(2);
  expect(requests.at(-1)).toEqual({ query: '', filters: [] });
});

test('mode switches retain pending-search navigation guards and reload returns to Welcome', async ({ page }) => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  await boot(page, gate);
  try {
    await search(page).fill('release');
    await search(page).press('Enter');
    await expect(hero(page)).toHaveClass(/is-loading/);
    await toggle(page).click();
    await expectTwoSlides(page);
    for (const button of await page.locator('[data-section-index]:not([hidden])').all()) await expect(button).toBeDisabled();
    await dot(page, 4).evaluate((button) => button.click());
    await currentSlide(page, 0);
  } finally { release(); }
  await expect(hero(page)).toHaveAccessibleName('View results');
  await hero(page).click();
  await currentSlide(page, 4);
  await page.reload();
  await currentSlide(page, 0);
});

test('changing mode cancels a smooth scroll toward a semantic slide', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await boot(page);
  for (let round = 0; round < 4; round += 1) {
    if (round) await toggle(page).evaluate((button) => button.click());
    await dot(page, 1).click();
    if (round % 2) await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(0);
    await toggle(page).evaluate((button) => button.click());
    await currentSlide(page, 0);
    // Observe real animation frames, including the compositor's pending frame,
    // rather than accepting an instant zero followed by a stale scroll delta.
    const offsets = await page.evaluate(() => new Promise((resolve) => {
      const positions = [];
      const frame = () => {
        positions.push(scrollY);
        if (positions.length === 3) resolve(positions);
        else requestAnimationFrame(frame);
      };
      requestAnimationFrame(frame);
    }));
    expect(offsets).toEqual([0, 0, 0]);
    await expectTwoSlides(page);
  }
  await dot(page, 4).click();
  await currentSlide(page, 4);
});

test('a newer arrow action wins over deferred mode reconciliation', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await boot(page);
  // Both actions can arrive before the next visual frame. The mode callback
  // must not later pull this newer user navigation back to Welcome.
  await page.evaluate(() => {
    document.querySelector('[data-message-search-toggle]').click();
    document.querySelector('.slide-down-button--hero').click();
  });
  await expectTwoSlides(page);
  await currentSlide(page, 4);
});

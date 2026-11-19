import { test, expect } from '@playwright/test';
import { appOrigin, getViewerFixtureAsset } from './viewer-fixture-assets.js';

test.use({ reducedMotion: 'no-preference', serviceWorkers: 'block' });
const layerKeys = ['subject', 'broad_topic', 'specific_topic', 'specific_message'];
const section = (page, index) => page.locator(`[data-section="${index}"]`);
const down = (page, index) => section(page, index).locator('.slide-down-button');
const up = (page, index) => section(page, index).locator('.slide-up-button:not(.slide-down-button)');

async function boot(page, count = 2) {
  const layers = Object.fromEntries(layerKeys.map((key, layer) => [key,
    Array.from({ length: count }, (_, index) => ({ id: `node-${layer}-${index}`, layer: key,
      title: `Layer ${layer + 1} item ${index + 1}`, summary: 'Synthetic conversation evidence', memberCount: 1, sourceChatCount: 1 })),
  ]));
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    const asset = getViewerFixtureAsset(url);
    if (asset) return route.fulfill({ path: asset });
    if (url.origin !== appOrigin) return route.abort();
    if (url.pathname === '/favicon.ico') return route.fulfill({ status: 204 });
    if (url.pathname === '/api/threads') return route.fulfill({ json: [{ id: 'fixture-project', title: 'Navigation fixture' }] });
    if (url.pathname === '/api/connections/refresh-status') return route.fulfill({ json: { state: 'idle' } });
    if (url.pathname === '/api/explore') return route.fulfill({ json: { project: { id: 'fixture-project' }, query: '', layers,
      edges: layerKeys.slice(1).flatMap((_, layer) => layers[layerKeys[layer + 1]].map((node, index) => ({
        child_id: node.id, parent_id: layers[layerKeys[layer]][index].id,
      }))),
    } });
    if (url.pathname.startsWith('/api/node/')) return route.fulfill({ json: { display_title: 'Conversation details',
      overview: [{ label: 'Question', text: 'How do we keep navigation available?' }], message_count: 1, source_chat_count: 1,
      sources: [{ verified: true, text: 'Keep the arrows usable after closing this card.', chat_title: 'Synthetic navigation chat' }],
    } });
    return route.abort();
  });
  await page.goto(appOrigin);
  await expect(section(page, 1).locator('.feature-card')).toHaveCount(Math.min(count, 9));
  return errors;
}

async function geometry(page, index) {
  return page.evaluate(index => {
    const rect = document.querySelector(`[data-section="${index}"]`).getBoundingClientRect();
    const arrows = [...document.querySelectorAll('.slide-up-button')].map(button => {
      const r = button.getBoundingClientRect(), style = getComputedStyle(button);
      return { section: Number(button.closest('[data-section]').dataset.section), top: r.top, bottom: r.bottom,
        visible: !button.hidden && r.width > 0 && r.height > 0 && r.top >= 0 && r.bottom <= innerHeight
          && Number(style.opacity) > .8 && style.pointerEvents !== 'none' };
    });
    return { top: rect.top, scrollY, viewport: innerHeight, arrows,
      nested: [...document.querySelectorAll('.sections-viewport,.scroll-page')].map(el => [el.className, el.scrollTop]) };
  }, index);
}

async function expectAlignedAndNavigable(page, index) {
  await expect.poll(async () => Math.abs((await geometry(page, index)).top)).toBeLessThan(1);
  const arrows = section(page, index).locator('.slide-up-button:not([hidden])');
  await expect.poll(async () => arrows.evaluateAll(buttons => buttons.every(button => {
    const style = getComputedStyle(button);
    return !button.classList.contains('is-leaving') && Number(style.opacity) > .8 && style.pointerEvents !== 'none';
  }))).toBe(true);
  const g = await geometry(page, index);
  expect(g.arrows.filter(arrow => arrow.visible).map(arrow => arrow.section)).toEqual(Array(index === 0 || index === 4 ? 1 : 2).fill(index));
}

async function navigate(page, index) {
  await page.getByRole('button', { name: `Go to ${['Welcome', 'Subjects', 'Broad Topics', 'Specific Topics', 'Specific Messages'][index]}` }).click();
  await expectAlignedAndNavigable(page, index);
}

for (const closeMethod of ['Escape', 'Done', 'backdrop']) {
  test(`closing metadata with ${closeMethod} keeps lower-slide arrows aligned and usable`, async ({ page }) => {
    const errors = await boot(page);
    await navigate(page, 2);
    for (let round = 0; round < 3; round++) {
      await section(page, 2).locator('.feature-card__body').nth(round % 2).click();
      await expect(page.locator('[data-node-detail-overlay]')).toBeVisible();
      if (closeMethod === 'Escape') await page.keyboard.press('Escape');
      else if (closeMethod === 'Done') await page.locator('[data-node-detail-done]').click();
      else await page.locator('[data-node-detail-overlay]').click({ position: { x: 5, y: 5 } });
      await expect(page.locator('[data-node-detail-overlay]')).toBeHidden();
      await expectAlignedAndNavigable(page, 2);
    }
    await down(page, 2).click(); await expectAlignedAndNavigable(page, 3);
    await up(page, 3).click(); await expectAlignedAndNavigable(page, 2);
    expect(errors).toEqual([]);
  });
}

test('a card opened as its slide arrives cannot strand faded arrows between slides', async ({ page }) => {
  const errors = await boot(page);
  await navigate(page, 2);
  await down(page, 2).click();
  await expect(down(page, 2)).toHaveClass(/is-leaving/);
  // A card can be clicked as it enters the viewport, before smooth scrolling settles.
  await expect.poll(async () => {
    const bounds = await section(page, 3).locator('.feature-card__body').first().boundingBox();
    return bounds && bounds.y > 0 && bounds.y + bounds.height < 900;
  }).toBe(true);
  const bounds = await section(page, 3).locator('.feature-card__body').first().boundingBox();
  await page.mouse.click(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await expect(page.locator('[data-node-detail-overlay]')).toBeVisible();
  await page.keyboard.press('Escape');
  await expectAlignedAndNavigable(page, 3);
  await up(page, 3).click(); await expectAlignedAndNavigable(page, 2);
  expect(errors).toEqual([]);
});

test('closing a low card in a scrolling grid preserves page and list position', async ({ page }) => {
  const errors = await boot(page, 9);
  await page.setViewportSize({ width: 900, height: 680 });
  await navigate(page, 3);
  const list = section(page, 3).locator('.feature-list');
  await list.evaluate(el => { el.scrollTop = el.scrollHeight; });
  const before = await list.evaluate(el => el.scrollTop);
  await section(page, 3).locator('.feature-card__body').last().click();
  await page.locator('[data-node-detail-done]').click();
  await expectAlignedAndNavigable(page, 3);
  expect(await list.evaluate(el => el.scrollTop)).toBeCloseTo(before, 0);
  await down(page, 3).click(); await expectAlignedAndNavigable(page, 4);
  expect(errors).toEqual([]);
});

test('resizing a lower slide with metadata open restores only that slide on close', async ({ page }) => {
  const errors = await boot(page);
  await navigate(page, 2);
  await section(page, 2).locator('.feature-card__body').first().click();
  await page.setViewportSize({ width: 1100, height: 740 });
  await page.keyboard.press('Escape');
  await expectAlignedAndNavigable(page, 2);
  await down(page, 2).click(); await expectAlignedAndNavigable(page, 3);
  expect(errors).toEqual([]);
});

test('the fixed page viewport cannot become a second scroller after closing a card', async ({ page }) => {
  const errors = await boot(page);
  await navigate(page, 2);
  await section(page, 2).locator('.feature-card__body').first().click();
  await expect(page.locator('[data-node-detail-overlay]')).toBeVisible();
  // Browser focus/scroll-into-view may try scrolling a clipping ancestor.
  // This must never move the track separately from the page's slide position.
  await page.locator('[data-sections-viewport]').evaluate(viewport => { viewport.scrollTop = 36; });
  await page.locator('[data-node-detail-done]').click();
  await expectAlignedAndNavigable(page, 2);
  expect(await page.locator('[data-sections-viewport]').evaluate(viewport => viewport.scrollTop)).toBe(0);
  await down(page, 2).click(); await expectAlignedAndNavigable(page, 3);
  expect(errors).toEqual([]);
});

test('interrupted navigation cannot leave the current arrows faded forever', async ({ page }) => {
  const errors = await boot(page);
  await navigate(page, 2);
  await down(page, 2).click();
  await expect(down(page, 2)).toHaveClass(/is-leaving/);
  // Native focus or a modal can cancel a native smooth scroll. Reproduce
  // cancellation before the destination becomes the active section.
  await page.evaluate(() => {
    const current = document.querySelector('[data-section="2"]');
    window.scrollTo({ top: current.offsetTop, behavior: 'instant' });
    current.querySelector('.feature-card__body').click();
  });
  await expect(page.locator('[data-node-detail-overlay]')).toBeVisible();
  await page.keyboard.press('Escape');
  await expectAlignedAndNavigable(page, 2);
  await down(page, 2).click(); await expectAlignedAndNavigable(page, 3);
  expect(errors).toEqual([]);
});


test('messages-only metadata close preserves the direct return arrow to Welcome', async ({ page }) => {
  const errors = await boot(page);
  await page.locator('[data-spotlight-input]').focus();
  await page.locator('[data-message-search-toggle]').click();
  await expect(page.locator('[data-section]:not([hidden])')).toHaveCount(2);
  await down(page, 0).click(); await expectAlignedAndNavigable(page, 4);
  await section(page, 4).locator('.feature-card__body').first().click();
  await page.locator('[data-node-detail-done]').click();
  await expectAlignedAndNavigable(page, 4);
  await expect(up(page, 4)).toHaveAttribute('data-scroll-to', '0');
  await up(page, 4).click(); await expectAlignedAndNavigable(page, 0);
  expect(errors).toEqual([]);
});

test('a native scroll cancelled before halfway settles its intended slide without a modal', async ({ page }) => {
  const errors = await boot(page);
  await navigate(page, 2);
  await down(page, 2).click();
  const cancellation = await page.evaluate(async () => {
    const source = document.querySelector('[data-section="2"]').offsetTop;
    const target = document.querySelector('[data-section="3"]').offsetTop;
    const deadline = performance.now() + 2000;
    while (scrollY <= source + 2 && performance.now() < deadline) {
      await new Promise(requestAnimationFrame);
    }
    const before = scrollY;
    window.scrollTo({ top: source + 1, behavior: 'instant' });
    return { source, target, before };
  });
  expect(cancellation.before).toBeGreaterThan(cancellation.source);
  expect(cancellation.before).toBeLessThan((cancellation.source + cancellation.target) / 2);
  await expectAlignedAndNavigable(page, 3);
  await up(page, 3).click(); await expectAlignedAndNavigable(page, 2);
  expect(errors).toEqual([]);
});

test('resizing during an incoming slide preserves the intended destination over the nearer source', async ({ page }) => {
  const errors = await boot(page);
  await navigate(page, 2);
  await down(page, 2).click();
  await expect(down(page, 2)).toHaveClass(/is-leaving/);
  // Resize before the target is centered. The navigation request, rather than
  // the nearest old position under the new viewport height, owns the result.
  await page.setViewportSize({ width: 1120, height: 770 });
  await expectAlignedAndNavigable(page, 3);
  await up(page, 3).click(); await expectAlignedAndNavigable(page, 2);
  expect(errors).toEqual([]);
});

test('a newer sidebar destination defeats a preceding arrow fade timer', async ({ page }) => {
  const errors = await boot(page);
  await navigate(page, 2);
  // Dispatch within one browser turn so the newer destination is guaranteed
  // to arrive before the first arrow's fade timer starts its native scroll.
  await page.evaluate(() => {
    document.querySelector('[data-section="2"] .slide-down-button').click();
    document.querySelector('[data-section-index="4"]').click();
  });
  await expectAlignedAndNavigable(page, 4);
  // A following real user action must remain usable without a page reload.
  await up(page, 4).click(); await expectAlignedAndNavigable(page, 3);
  expect(errors).toEqual([]);
});

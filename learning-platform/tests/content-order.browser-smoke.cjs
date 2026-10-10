/* Exercise real folder drag controls against isolated HTML fixtures, with no network access. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fixture = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const output = path.resolve(process.argv[3]);
const platform = path.resolve(__dirname, '..');
const origin = 'https://lms-preview.test';
const reports = [];
const posts = [];
const errors = [];
let responseMode = 'success';
let releaseSave;
let gets = 0;
fs.mkdirSync(output, { recursive: true });

function formValues(request) {
  const body = request.postData() || '';
  if (!request.headers()['content-type']?.includes('multipart/form-data')) return Object.fromEntries(new URLSearchParams(body));
  const entries = Array.from(body.matchAll(/name="([^"]+)"\r\n\r\n([^\r]*)/g), match => [match[1], match[2]]);
  return Object.fromEntries(entries);
}

(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.CONTENT_UI_BROWSER ? { executablePath: process.env.CONTENT_UI_BROWSER } : {}) });
  const context = await browser.newContext({ viewport: { width: 1360, height: 1000 } });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  await context.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin) return route.abort();
    if (request.method() === 'POST') {
      const values = formValues(request);
      posts.push({ values, headers: request.headers(), path: url.pathname });
      if (responseMode === 'deferred') await new Promise(resolve => { releaseSave = resolve; });
      if (responseMode === 'stale') return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ error: 'Order changed. Refresh before trying again.' }) });
      if (responseMode === 'network') return route.abort('failed');
      const order = values.order.split(',').map(Number);
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ order, parent: values.parent ? Number(values.parent) : null }) });
    }
    const key = url.pathname + url.search;
    if (fixture.routes[key]) {
      if (key === fixture.browser_url) gets++;
      return route.fulfill({ contentType: 'text/html; charset=utf-8', body: fixture.routes[key] });
    }
    if (url.pathname.startsWith('/platform-assets/')) {
      const asset = path.resolve(platform, 'assets', url.pathname.substring('/platform-assets/'.length));
      if (!asset.startsWith(path.join(platform, 'assets') + path.sep) || !fs.existsSync(asset)) return route.abort();
      return route.fulfill({ contentType: asset.endsWith('.css') ? 'text/css' : 'text/javascript', body: fs.readFileSync(asset) });
    }
    if (url.pathname.startsWith('/design-assets/fonts/')) {
      const asset = path.resolve(platform, '../academic-preview/assets/fonts', path.basename(url.pathname));
      if (fs.existsSync(asset)) return route.fulfill({ body: fs.readFileSync(asset), contentType: asset.endsWith('.css') ? 'text/css' : 'font/woff2' });
    }
    if (url.pathname === '/design-assets/statistics.jpg') return route.fulfill({ body: fs.readFileSync(path.resolve(platform, '../academic-preview/assets/statistics.jpg')), contentType: 'image/jpeg' });
    return route.fulfill({ status: 404, body: '' });
  });
  const row = id => page.locator(`[data-content-item="${id}"]`);
  const handle = id => row(id).locator(':scope > [data-content-drag]');
  const folder = id => page.locator(`[data-content-folder="${id}"]`);
  const status = page.locator('[data-content-order-status]');
  const rootOrder = () => page.locator('[data-content-tree] > [data-content-item]').evaluateAll(rows => rows.map(row => Number(row.dataset.contentItem)));
  const childOrder = id => folder(id).locator(':scope > .content-folder-body > .content-folder-children > [data-content-item]').evaluateAll(rows => rows.map(row => Number(row.dataset.contentItem)));
  const open = async id => { if (!(await folder(id).evaluate(element => element.open))) await folder(id).locator(':scope > summary').click(); };
  const closed = async id => { if (await folder(id).evaluate(element => element.open)) await folder(id).locator(':scope > summary').click(); };
  const waitSaved = async () => { await page.waitForFunction(() => document.querySelector('[data-content-order-message]')?.textContent.includes('Order saved.')); };
  async function assertExpanded(id, expanded) {
    await page.waitForFunction(({ id, expanded }) => {
      const item = document.querySelector(`[data-content-item="${id}"]`);
      return item?.querySelector(':scope > details')?.open === expanded
        && item.querySelector(':scope > [data-content-drag]')?.getAttribute('aria-expanded') === String(expanded);
    }, { id, expanded });
  }
  async function iconToggle(id, expanded) {
    await handle(id).click();
    await assertExpanded(id, expanded);
  }
  async function assertFolderIcon(id) {
    const control = handle(id);
    assert.equal(await control.locator('.content-type-folder svg').count(), 1, 'The folder icon itself is the draggable control.');
    assert.equal(await control.locator('circle').count(), 0, 'The separate dotted grip is gone.');
    assert.equal(await row(id).locator(':scope > details > summary > .content-type-folder:visible, :scope > [data-content-drag] .content-type-folder:visible').count(), 1, 'Show one folder icon, without a second decorative icon.');
    const iconBox = await control.locator('.content-type-folder').boundingBox();
    const arrowBox = await folder(id).locator(':scope > summary > .content-folder-arrow').boundingBox();
    const titleBox = await folder(id).locator(':scope > summary .content-folder-title').boundingBox();
    assert(iconBox.x > arrowBox.x + arrowBox.width && iconBox.x + iconBox.width <= titleBox.x, 'The draggable folder icon occupies the space between the arrow and title.');
  }
  async function drag(id, targetId, after = false) {
    const source = handle(id);
    const targetRow = row(targetId);
    const target = await targetRow.locator(':scope > details[data-content-folder] > summary').count()
      ? targetRow.locator(':scope > details[data-content-folder] > summary') : targetRow;
    await source.scrollIntoViewIfNeeded();
    await target.scrollIntoViewIfNeeded();
    const sourceBox = await source.boundingBox();
    const targetBox = await target.boundingBox();
    await page.mouse.move(sourceBox.x + sourceBox.width / 2, sourceBox.y + sourceBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(sourceBox.x - 15, sourceBox.y + sourceBox.height / 2, { steps: 3 });
    await page.mouse.move(targetBox.x + Math.min(100, targetBox.width / 2), targetBox.y + targetBox.height * (after ? 0.85 : 0.15), { steps: 10 });
    await page.mouse.move(targetBox.x + Math.min(101, targetBox.width / 2), targetBox.y + targetBox.height * (after ? 0.85 : 0.15));
    await page.mouse.up();
  }
  async function cancelledMouseDrag(id, escape = false) {
    await handle(id).scrollIntoViewIfNeeded();
    const bounds = await handle(id).boundingBox();
    const x = bounds.x + bounds.width / 2;
    const y = bounds.y + bounds.height / 2;
    const postsBefore = posts.length;
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(x - 25, y, { steps: 5 });
    await page.waitForFunction(() => document.body.classList.contains('content-reordering'));
    if (escape) await page.keyboard.press('Escape');
    await page.mouse.move(x, y, { steps: 5 });
    await page.mouse.up();
    await page.waitForFunction(() => !document.body.classList.contains('content-reordering'));
    await page.waitForTimeout(100);
    await assertExpanded(id, false);
    assert.equal(posts.length, postsBefore, 'A cancelled or invalid drag must not save a new order.');
    await iconToggle(id, true);
    await iconToggle(id, false);
  }

  await page.goto(origin + fixture.browser_url);
  await handle(fixture.module_id).waitFor({ state: 'visible' });
  assert.deepEqual(await rootOrder(), fixture.root_order);
  await assertFolderIcon(fixture.module_id);
  await assertFolderIcon(fixture.next_module_id);
  await assertExpanded(fixture.module_id, false);
  await iconToggle(fixture.module_id, true);
  await iconToggle(fixture.module_id, false);
  await handle(fixture.module_id).focus();
  await page.keyboard.press('Enter');
  await assertExpanded(fixture.module_id, true);
  await page.keyboard.press('Space');
  await assertExpanded(fixture.module_id, false);
  await folder(fixture.module_id).locator(':scope > summary .content-folder-title').click();
  await assertExpanded(fixture.module_id, true);
  await folder(fixture.module_id).locator(':scope > summary > .content-folder-arrow').click();
  await assertExpanded(fixture.module_id, false);
  await iconToggle(fixture.next_module_id, true);
  assert.equal(await handle(fixture.only_folder_id).isDisabled(), false, 'A folder with no siblings can still open.');
  assert.equal(await handle(fixture.only_folder_id).evaluate(element => element.draggable), false);
  await iconToggle(fixture.only_folder_id, true);
  assert.equal(await page.getByRole('link', { name: 'Single-folder lesson notes', exact: true }).isVisible(), true);
  await handle(fixture.only_folder_id).focus();
  await page.keyboard.press('Space');
  await assertExpanded(fixture.only_folder_id, false);
  await iconToggle(fixture.next_module_id, false);
  await cancelledMouseDrag(fixture.next_module_id);
  await cancelledMouseDrag(fixture.next_module_id, true);
  assert.equal(posts.length, 0, 'Opening and cancelled drags never reorder content.');
  assert.equal(page.url(), origin + fixture.browser_url);
  reports.push('Folder icons open and close with mouse, Enter and Space, including an only-child folder; title and arrow clicks synchronize aria-expanded. Invalid or Escape-cancelled mouse drags never toggle or save.');
  const loadsBefore = gets;
  responseMode = 'deferred';
  await drag(fixture.next_module_id, fixture.module_id);
  await page.waitForFunction(() => document.querySelector('[data-content-order-message]')?.textContent.includes('Saving folder order'));
  assert.deepEqual(await rootOrder(), fixture.root_order, 'Keep original order until the server confirms saving.');
  assert.equal(await handle(fixture.module_id).isDisabled(), false);
  assert.equal(await handle(fixture.module_id).evaluate(element => element.draggable), false);
  await iconToggle(fixture.module_id, true);
  await iconToggle(fixture.module_id, false);
  await page.keyboard.press('Alt+ArrowDown');
  assert.equal(posts.length, 1);
  const firstPost = posts[0];
  assert.equal(firstPost.values.expected_order, fixture.root_order.join(','));
  assert.equal(firstPost.values.order, [fixture.next_module_id, fixture.module_id, fixture.course_page_id].join(','));
  assert.equal(firstPost.values.parent, '');
  assert.equal(firstPost.values.account_id, String(fixture.account_id));
  assert(firstPost.values.csrfmiddlewaretoken || firstPost.headers['x-csrftoken']);
  assert(firstPost.path.endsWith(`/${fixture.next_module_id}/reorder/`));
  while (!releaseSave) await new Promise(resolve => setTimeout(resolve, 10));
  releaseSave();
  await waitSaved();
  responseMode = 'success';
  assert.deepEqual(await rootOrder(), [fixture.next_module_id, fixture.module_id, fixture.course_page_id]);
  assert.equal(await folder(fixture.module_id).evaluate(element => element.open), false);
  assert.equal(await folder(fixture.next_module_id).evaluate(element => element.open), false, 'Dragging the icon does not expand its folder.');
  assert.equal(gets, loadsBefore);
  assert.equal(page.url(), origin + fixture.browser_url);
  reports.push('Dragging a root folder by its icon saves all sibling IDs with CSRF, account ID and original order, without toggling the folder, navigating or optimistic false success.');

  await drag(fixture.next_module_id, fixture.course_page_id, true);
  await page.waitForFunction(({ first }) => Number(document.querySelector('[data-content-tree] > [data-content-item]')?.dataset.contentItem) === first, { first: fixture.module_id });
  assert.deepEqual(await rootOrder(), fixture.root_order);
  await open(fixture.module_id);
  await open(fixture.lesson_id);
  await assertFolderIcon(fixture.module_id);
  await assertFolderIcon(fixture.lesson_id);
  await assertFolderIcon(fixture.resources_id);
  await open(fixture.resources_id);
  const nestedBefore = await childOrder(fixture.lesson_id);
  await handle(fixture.resources_id).focus();
  await page.keyboard.press('Alt+ArrowUp');
  await page.waitForFunction(({ parent, id }) => Number(document.querySelector(`[data-content-folder="${parent}"] > .content-folder-body > .content-folder-children > [data-content-item]`)?.dataset.contentItem) === id, { parent: fixture.lesson_id, id: fixture.resources_id });
  assert.deepEqual(await childOrder(fixture.lesson_id), [fixture.resources_id, ...nestedBefore.filter(id => id !== fixture.resources_id)]);
  for (const id of [fixture.module_id, fixture.lesson_id, fixture.resources_id]) assert.equal(await folder(id).evaluate(element => element.open), true);
  assert.equal(await row(fixture.resources_id).getAttribute('data-content-parent'), String(fixture.lesson_id));
  assert.equal(await page.evaluate(() => document.activeElement?.matches('[data-content-drag]')), true);
  assert.equal(posts.at(-1).values.parent, String(fixture.lesson_id));
  const noOpCount = posts.length;
  await page.keyboard.press('Alt+ArrowUp');
  await page.waitForTimeout(100);
  assert.equal(posts.length, noOpCount);
  await drag(fixture.resources_id, nestedBefore[0], true);
  await page.waitForFunction(({ parent, id }) => Number(document.querySelector(`[data-content-folder="${parent}"] > .content-folder-body > .content-folder-children > [data-content-item]`)?.dataset.contentItem) === id, { parent: fixture.lesson_id, id: nestedBefore[0] });
  assert.deepEqual(await childOrder(fixture.lesson_id), nestedBefore);
  for (const id of [fixture.module_id, fixture.lesson_id, fixture.resources_id]) assert.equal(await folder(id).evaluate(element => element.open), true);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
  await page.screenshot({ path: path.join(output, 'folder-order-desktop.png'), fullPage: true });
  reports.push('Downward drag works across ordinary materials; nested drag and keyboard reorder move the folder and its contents together while preserving expanded state and focus.');

  await closed(fixture.module_id);
  responseMode = 'stale';
  const stableRoot = await rootOrder();
  await drag(fixture.next_module_id, fixture.module_id);
  await page.locator('[data-content-order-reload]').waitFor({ state: 'visible' });
  assert.deepEqual(await rootOrder(), stableRoot);
  assert(!(await status.innerText()).includes('Order saved.'));
  assert.equal(await handle(fixture.module_id).isDisabled(), false);
  assert.equal(await handle(fixture.module_id).evaluate(element => element.draggable), false);
  const conflictPostCount = posts.length;
  await iconToggle(fixture.module_id, true);
  await iconToggle(fixture.module_id, false);
  await page.keyboard.press('Alt+ArrowDown');
  assert.equal(posts.length, conflictPostCount);
  reports.push('Pending saves and concurrent-edit conflicts stop reordering while allowing folder icons to open and close; conflicts preserve the order and show Refresh.');

  responseMode = 'network';
  await page.reload();
  await handle(fixture.module_id).waitFor({ state: 'visible' });
  await drag(fixture.next_module_id, fixture.module_id);
  await page.locator('[data-content-order-reload]').waitFor({ state: 'visible' });
  assert.deepEqual(await rootOrder(), fixture.root_order);
  assert(!(await status.innerText()).includes('Order saved.'));
  reports.push('A failed network request retains the original order and never reports a saved change.');

  responseMode = 'success';
  await page.reload();
  await page.setViewportSize({ width: 320, height: 740 });
  await open(fixture.module_id);
  await open(fixture.lesson_id);
  await assertFolderIcon(fixture.module_id);
  await assertFolderIcon(fixture.lesson_id);
  await assertFolderIcon(fixture.resources_id);
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await handle(fixture.resources_id).focus();
  await page.keyboard.press('Alt+ArrowUp');
  await waitSaved();
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
  await page.screenshot({ path: path.join(output, 'folder-order-mobile.png'), fullPage: true });
  reports.push('Folder icons and the saved-state message fit a 320px viewport; keyboard ordering still works.');

  await closed(fixture.module_id);
  const cdp = await context.newCDPSession(page);
  await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 1 });
  const touches = (x, y) => [{ x, y, id: 1, radiusX: 2, radiusY: 2, force: 1 }];
  async function touchIcon(id, expanded, cancel = '') {
    await handle(id).scrollIntoViewIfNeeded();
    const bounds = await handle(id).boundingBox();
    const x = bounds.x + bounds.width / 2;
    const y = bounds.y + bounds.height / 2;
    const postsBefore = posts.length;
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: touches(x, y) });
    if (cancel) {
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: touches(x + 12, y) });
      await page.waitForFunction(() => document.body.classList.contains('content-reordering'));
    }
    await cdp.send('Input.dispatchTouchEvent', { type: cancel === 'cancel' ? 'touchCancel' : 'touchEnd', touchPoints: [] });
    await page.waitForTimeout(150);
    await assertExpanded(id, expanded);
    assert.equal(posts.length, postsBefore, 'Taps and cancelled or invalid touch drags must not save an order.');
  }
  await touchIcon(fixture.module_id, true);
  await touchIcon(fixture.module_id, false);
  await touchIcon(fixture.next_module_id, true);
  await touchIcon(fixture.only_folder_id, true);
  await touchIcon(fixture.only_folder_id, false);
  await touchIcon(fixture.next_module_id, false);
  await touchIcon(fixture.next_module_id, false, 'invalid');
  await touchIcon(fixture.next_module_id, true);
  await touchIcon(fixture.next_module_id, false);
  await touchIcon(fixture.next_module_id, false, 'cancel');
  await touchIcon(fixture.next_module_id, true);
  await touchIcon(fixture.next_module_id, false);
  reports.push('Real touch taps open and close folders, including only-child folders; invalid and cancelled touch drags do not toggle or block the following tap.');
  await handle(fixture.next_module_id).scrollIntoViewIfNeeded();
  await folder(fixture.module_id).locator(':scope > summary').scrollIntoViewIfNeeded();
  const touchSource = await handle(fixture.next_module_id).boundingBox();
  const touchTarget = await folder(fixture.module_id).locator(':scope > summary').boundingBox();
  const touchX = touchSource.x + touchSource.width / 2;
  const touchY = touchSource.y + touchSource.height / 2;
  const targetX = touchTarget.x + Math.min(70, touchTarget.width / 2);
  const targetY = touchTarget.y + touchTarget.height * 0.15;
  assert(touchY > 0 && touchY < 740 && targetY > 0 && targetY < 740);
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: touches(touchX, touchY) });
  for (let step = 1; step <= 12; step++) {
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: touches(touchX + (targetX - touchX) * step / 12, touchY + (targetY - touchY) * step / 12) });
  }
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await page.waitForFunction(({ id }) => Number(document.querySelector('[data-content-tree] > [data-content-item]')?.dataset.contentItem) === id, { id: fixture.next_module_id });
  assert.deepEqual(await rootOrder(), [fixture.next_module_id, fixture.module_id, fixture.course_page_id]);
  await assertExpanded(fixture.module_id, false);
  await assertExpanded(fixture.next_module_id, false);
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await cdp.detach();
  reports.push('A real browser touch start/move/end sequence reorders a folder on the mobile viewport and saves it successfully.');

  await page.goto(origin + fixture.student_url);
  assert.equal(await page.locator('[data-content-drag], [data-content-order-status], #content-order-help').count(), 0);
  await open(fixture.module_id);
  await open(fixture.lesson_id);
  assert.equal(await page.getByRole('link', { name: 'Getting started', exact: true }).isVisible(), true);
  assert.equal(await page.getByText('Teacher planning folder', { exact: true }).count(), 0);
  reports.push('Students can expand the content but receive no drag or authoring controls.');

  assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(output, 'order-smoke-results.json'), JSON.stringify(reports, null, 2));
  console.log(reports.join('\n'));
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });

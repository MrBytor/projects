import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../assets/lesson-viewer.js', import.meta.url), 'utf8');
function fixture(fullscreenEnabled = true) {
  const element = () => ({ handlers: {}, addEventListener(type, fn) { this.handlers[type] = fn; }, setAttribute(name, value) { this[name] = value; } });
  const slides = Array.from({ length: 3 }, (_, i) => ({ ...element(), offsetTop: i * 100, offsetHeight: 80, dataset: { url: `/slides/${i + 1}/` } }));
  const previous = element(), next = element(), fullscreen = element(), image = element(), counter = element();
  const thumbnails = { scrollTop: 0, clientHeight: 160 }, fullscreenLabel = element(), status = element();
  counter.textContent = 'Slide 1 / 3';
  const nodes = { '[data-slide-status]': status, '.slide-thumbnails': thumbnails, '[data-fullscreen-label]': fullscreenLabel, '[data-previous]': previous, '[data-next]': next, '[data-fullscreen]': fullscreen, '[data-current-slide]': image, '[data-slide-counter]': counter, '[data-presentation-name]': { textContent: 'Real class presentation.pptx' } };
  const viewer = { ...element(), querySelectorAll() { return slides; }, querySelector(selector) { return nodes[selector]; }, async requestFullscreen() { document.fullscreenElement = viewer; document.handlers.fullscreenchange(); } };
  const document = { ...element(), querySelector() { return viewer; }, fullscreenEnabled, fullscreenElement: null, async exitFullscreen() { this.fullscreenElement = null; this.handlers.fullscreenchange(); } };
  vm.runInNewContext(source, { document });
  return { slides, previous, next, fullscreen, fullscreenLabel, thumbnails, status, image, counter, viewer, document };
}

test('slide navigation updates the image, counter and accessible selection at both boundaries', () => {
  const f = fixture();
  f.next.handlers.click();
  assert.equal(f.image.src, '/slides/2/');
  assert.equal(f.counter.textContent, 'Slide 2 / 3');
  assert.equal(f.slides[1]['aria-current'], 'true');
  assert.equal(f.slides[0]['aria-current'], 'false');
  f.slides[2].handlers.click();
  assert.equal(f.next.disabled, true);
  f.next.handlers.click();
  assert.equal(f.image.src, '/slides/3/');
  f.previous.handlers.click(); f.previous.handlers.click();
  assert.equal(f.previous.disabled, true);
  assert.equal(f.image.src, '/slides/1/');
});

test('arrow keys navigate slides without intercepting answer entry', () => {
  const f = fixture(); let prevented = false;
  f.viewer.handlers.keydown({ key: 'ArrowRight', target: { matches: () => true }, preventDefault() { prevented = true; } });
  assert.equal(prevented, false);
  f.viewer.handlers.keydown({ key: 'ArrowRight', target: { matches: () => false }, preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(f.image.src, '/slides/2/');
});

test('fullscreen toggles and unsupported browsers retain normal navigation', async () => {
  const f = fixture();
  await f.fullscreen.handlers.click();
  assert.equal(f.document.fullscreenElement, f.viewer);
  assert.equal(f.fullscreenLabel.textContent, 'Exit fullscreen');
  assert.equal(f.fullscreen['aria-pressed'], 'true');
  await f.fullscreen.handlers.click();
  assert.equal(f.document.fullscreenElement, null);
  assert.equal(f.fullscreenLabel.textContent, 'Fullscreen');
  assert.equal(f.fullscreen['aria-label'], 'Enter fullscreen');
  assert.equal(fixture(false).fullscreen.hidden, true);
});

test('thumbnail selection scrolls only its own rail and restores the first item', () => {
  const f = fixture();
  f.slides[2].handlers.click();
  assert.equal(f.thumbnails.scrollTop, 128);
  f.slides[0].handlers.click();
  assert.equal(f.thumbnails.scrollTop, 0);
  assert.equal(f.image.alt, 'Slide 1 from Real class presentation.pptx');
});

test('fullscreen rejection keeps the compact counter and reports a separate status', async () => {
  const f = fixture();
  f.viewer.requestFullscreen = async () => { throw new Error('Fullscreen not allowed'); };
  await f.fullscreen.handlers.click();
  assert.equal(f.counter.textContent, 'Slide 1 / 3');
  assert.equal(f.status.hidden, false);
  assert.match(f.status.textContent, /Fullscreen is unavailable/);
});

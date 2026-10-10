(() => {
  const viewer = document.querySelector('[data-slide-viewer]');
  if (!viewer) return;
  const slides = Array.from(viewer.querySelectorAll('[data-slide]'));
  if (!slides.length) return;
  const thumbnails = viewer.querySelector('.slide-thumbnails');
  const presentationName = viewer.querySelector('[data-presentation-name]').textContent.trim();
  const image = viewer.querySelector('[data-current-slide]');
  const counter = viewer.querySelector('[data-slide-counter]');
  const previous = viewer.querySelector('[data-previous]');
  const next = viewer.querySelector('[data-next]');
  let current = 0;
  function show(index) {
    current = Math.max(0, Math.min(slides.length - 1, index));
    for (const [i, slide] of slides.entries()) slide.setAttribute('aria-current', String(i === current));
    image.src = slides[current].dataset.url;
    image.alt = `Slide ${current + 1} from ${presentationName}`;
    counter.textContent = `Slide ${current + 1} / ${slides.length}`;
    previous.disabled = current === 0;
    next.disabled = current === slides.length - 1;
    // Scroll this rail only; moving between slides must not jump the lesson page.
    const selected = slides[current];
    const top = selected.offsetTop;
    const bottom = top + selected.offsetHeight;
    if (top < thumbnails.scrollTop) thumbnails.scrollTop = Math.max(0, top - 8);
    else if (bottom > thumbnails.scrollTop + thumbnails.clientHeight) thumbnails.scrollTop = bottom - thumbnails.clientHeight + 8;
  }
  slides.forEach((slide, i) => slide.addEventListener('click', () => show(i)));
  previous.addEventListener('click', () => show(current - 1));
  next.addEventListener('click', () => show(current + 1));
  viewer.addEventListener('keydown', event => {
    if (event.target.matches('input, select, textarea')) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault(); show(current + (event.key === 'ArrowLeft' ? -1 : 1));
    }
  });
  const fullscreen = viewer.querySelector('[data-fullscreen]');
  const fullscreenLabel = viewer.querySelector('[data-fullscreen-label]');
  const status = viewer.querySelector('[data-slide-status]');
  if (!document.fullscreenEnabled) fullscreen.hidden = true;
  document.addEventListener('fullscreenchange', () => {
    const active = document.fullscreenElement === viewer;
    fullscreenLabel.textContent = active ? 'Exit fullscreen' : 'Fullscreen';
    fullscreen.setAttribute('aria-label', active ? 'Exit fullscreen' : 'Enter fullscreen');
    fullscreen.setAttribute('aria-pressed', String(active));
  });
  fullscreen.addEventListener('click', async () => {
    status.hidden = true;
    status.textContent = '';
    try { if (document.fullscreenElement) await document.exitFullscreen(); else await viewer.requestFullscreen(); }
    catch {
      status.textContent = 'Fullscreen is unavailable. You can use your browser’s fullscreen control instead.';
      status.hidden = false;
    }
  });
  next.disabled = slides.length <= 1;
})();

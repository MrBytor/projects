(() => {
  const form = document.querySelector('[data-test-answers]');
  const status = document.getElementById('draft-status');
  if (!form || !status) return;
  let dirty = false;
  form.addEventListener('input', () => { dirty = true; status.textContent = 'Unsaved answers. Save progress before leaving this page.'; });
  form.addEventListener('submit', () => { dirty = false; });
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
})();

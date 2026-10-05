document.querySelectorAll('[data-menu-toggle]').forEach((button) => {
  const menu = document.getElementById(button.getAttribute('aria-controls'));
  if (!menu) return;
  const close = () => {
    menu.classList.remove('is-open');
    button.setAttribute('aria-expanded', 'false');
  };
  button.addEventListener('click', () => {
    const expanded = button.getAttribute('aria-expanded') !== 'true';
    button.setAttribute('aria-expanded', String(expanded));
    menu.classList.toggle('is-open', expanded);
  });
  menu.addEventListener('click', (event) => {
    if (event.target.closest('a')) close();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && button.getAttribute('aria-expanded') === 'true') {
      close();
      button.focus();
    }
  });
});

const publicationSearch = document.getElementById('publication-search');
if (publicationSearch) {
  const entries = Array.from(document.querySelectorAll('[data-publication]'));
  const groups = Array.from(document.querySelectorAll('[data-publication-group]'));
  const count = document.getElementById('publication-count');
  const empty = document.getElementById('publication-empty');
  const filter = () => {
    const words = publicationSearch.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
    let shown = 0;
    entries.forEach((entry) => {
      const matches = words.every((word) => entry.dataset.search.includes(word));
      entry.hidden = !matches;
      if (matches) shown += 1;
    });
    groups.forEach((group) => { group.hidden = !Array.from(group.querySelectorAll('[data-publication]')).some((entry) => !entry.hidden); });
    count.textContent = `${shown} ${shown === 1 ? 'publication' : 'publications'}${words.length ? ' found' : ''}`;
    empty.hidden = shown !== 0;
  };
  publicationSearch.addEventListener('input', filter);
  document.querySelector('[data-clear-publications]').addEventListener('click', () => {
    publicationSearch.value = '';
    filter();
    publicationSearch.focus();
  });
}

document.querySelectorAll('[data-copy-citation]').forEach((button) => {
  button.addEventListener('click', async () => {
    const panel = button.closest('details');
    const status = panel.querySelector('.copy-status');
    try {
      await navigator.clipboard.writeText(panel.querySelector('code').textContent);
      status.textContent = 'Copied';
    } catch {
      status.textContent = 'Select the citation above to copy it.';
    }
  });
});

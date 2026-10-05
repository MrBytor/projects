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

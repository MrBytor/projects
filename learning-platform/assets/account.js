(() => {
  const header = document.querySelector('.platform-header');
  if (!header) return;
  const accountId = Number(header.dataset.accountId) || null;
  for (const link of header.querySelectorAll('.platform-links a')) {
    const path = new URL(link.href).pathname;
    if (location.pathname === path || ((path.endsWith('courses.html') || path === '/my-courses/') && /\/site\/(statistics|corporate-finance|project-management)/.test(location.pathname))) link.setAttribute('aria-current', 'page');
  }
  const measure = () => document.documentElement.style.setProperty('--header-height', header.getBoundingClientRect().height + 'px');
  measure();
  if ('ResizeObserver' in window) new ResizeObserver(measure).observe(header);
  let checking = false;
  async function checkSession() {
    if (checking) return;
    checking = true;
    try {
      const response = await fetch('/api/session/', { credentials: 'same-origin', cache: 'no-store' });
      if (response.ok && (await response.json()).account_id !== accountId) location.reload();
    } catch { /* Keep the current page usable if the local server is temporarily offline. */ }
    finally { checking = false; }
  }
  window.addEventListener('focus', checkSession);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) checkSession(); });
  window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
})();

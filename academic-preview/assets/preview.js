(() => {
  const menuButton = document.querySelector('[data-menu-toggle]');
  const menu = document.getElementById('main-menu');
  const header = document.querySelector('.site-header');
  const main = document.getElementById('main');
  const root = document.documentElement;
  const practiceModuleUrl = new URL('statistics-practice.js?v=20261006a', document.currentScript.src).href;
  const initialisePage = () => {
    const practice = document.getElementById('statistics-practice');
    if (!practice) return;
    import(practiceModuleUrl).then((module) => {
      if (practice.isConnected) return module.mount(practice);
    }).catch(() => {
      if (practice.isConnected) practice.innerHTML = '<p class="practice-card" role="alert">Practice questions could not load. Please refresh the page to try again.</p>';
    });
  };
  initialisePage();
  const closeMenu = () => {
    menu?.classList.remove('is-open');
    menuButton?.setAttribute('aria-expanded', 'false');
  };
  menuButton?.addEventListener('click', () => {
    const expanded = menuButton.getAttribute('aria-expanded') !== 'true';
    menuButton.setAttribute('aria-expanded', String(expanded));
    menu?.classList.toggle('is-open', expanded);
  });
  menu?.addEventListener('click', (event) => {
    if (event.target.closest('a')) closeMenu();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && menuButton?.getAttribute('aria-expanded') === 'true') {
      closeMenu();
      menuButton.focus();
    }
  });
  const measureHeader = () => {
    if (header) root.style.setProperty('--header-height', `${header.getBoundingClientRect().height}px`);
  };
  measureHeader();
  if (header && 'ResizeObserver' in window) new ResizeObserver(measureHeader).observe(header);
  else window.addEventListener('resize', measureHeader);

  // Delegation keeps publication panels and citation controls working after navigation.
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-publication-toggle]');
    if (!button) return;
    const panel = document.getElementById(button.getAttribute('aria-controls'));
    if (!panel) return;
    const expanded = button.getAttribute('aria-expanded') !== 'true';
    button.setAttribute('aria-expanded', String(expanded));
    panel.hidden = !expanded;
  });

  document.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-copy-citation]');
    if (!button) return;
    const panel = button.closest('[data-citation-panel], details');
    if (!panel) return;
    const status = panel.querySelector('.copy-status');
    try {
      await navigator.clipboard.writeText(panel.querySelector('code').textContent);
      status.textContent = 'Copied';
    } catch {
      status.textContent = 'Select the citation above to copy it.';
    }
  });

  if (!main || !window.fetch || !history.pushState) return;
  const siteRoot = new URL('.', location.href);
  const pages = new Set(['index.html', 'courses.html', 'publications.html', 'about-me.html',
    'statistics.html', 'statistics-practice.html', 'corporate-finance.html', 'project-management.html']);
  const pageName = (url) => {
    if (url.origin !== siteRoot.origin || !url.pathname.startsWith(siteRoot.pathname)) return null;
    const name = url.pathname.slice(siteRoot.pathname.length) || 'index.html';
    return pages.has(name) ? name : null;
  };
  const keyFor = (url) => `${pageName(url)}${url.search}`;
  const snapshot = (doc, url) => {
    const content = doc.getElementById('main');
    if (!content) throw new Error('Missing page content');
    return {
      content: content.innerHTML,
      title: doc.title,
      description: doc.querySelector('meta[name="description"]')?.content || '',
      bodyClass: doc.body.className,
      language: doc.documentElement.lang || 'en',
      styles: Array.from(doc.querySelectorAll('head link[rel="stylesheet"], head style')).map((node) =>
        node.tagName === 'LINK' ? { href: new URL(node.getAttribute('href'), url).href } : { text: node.textContent }),
      images: Array.from(content.querySelectorAll('img[src]')).slice(0, 3).map((img) => new URL(img.getAttribute('src'), url).href)
    };
  };
  let currentUrl = new URL(location.href);
  const cache = new Map([[keyFor(currentUrl), snapshot(document, currentUrl)]]);
  const loadedStyles = new Map();
  for (const node of document.querySelectorAll('head link[rel="stylesheet"], head style')) {
    loadedStyles.set(node.tagName === 'LINK' ? node.href : `inline:${node.textContent}`, Promise.resolve());
  }
  const loadStyle = (style) => {
    const key = style.href || `inline:${style.text}`;
    if (loadedStyles.has(key)) return loadedStyles.get(key);
    if (!style.href) {
      const node = document.createElement('style');
      node.textContent = style.text;
      document.head.append(node);
      loadedStyles.set(key, Promise.resolve());
      return Promise.resolve();
    }
    const promise = new Promise((resolve, reject) => {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = style.href;
      const timeout = setTimeout(() => { link.remove(); reject(new Error('Stylesheet timed out')); }, 8000);
      link.onload = () => { clearTimeout(timeout); resolve(); };
      link.onerror = () => { clearTimeout(timeout); link.remove(); reject(new Error('Stylesheet unavailable')); };
      document.head.append(link);
    }).catch((error) => { loadedStyles.delete(key); throw error; });
    loadedStyles.set(key, promise);
    return promise;
  };
  const warmImage = (src) => {
    const image = new Image();
    image.src = src;
    return typeof image.decode === 'function' ? Promise.race([
      image.decode().catch(() => {}),
      new Promise((resolve) => setTimeout(resolve, 1500))
    ]) : Promise.resolve();
  };
  const getPage = async (url, signal) => {
    const key = keyFor(url);
    if (cache.has(key)) return cache.get(key);
    const requestUrl = new URL(url);
    requestUrl.hash = '';
    const response = await fetch(requestUrl.href, { signal, credentials: 'same-origin' });
    if (!response.ok || !response.headers.get('content-type')?.includes('text/html')) throw new Error('Page unavailable');
    const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
    const page = snapshot(doc, url);
    cache.set(key, page);
    return page;
  };
  const announcement = document.createElement('div');
  announcement.className = 'route-announcement';
  announcement.setAttribute('role', 'status');
  announcement.setAttribute('aria-live', 'polite');
  announcement.setAttribute('aria-atomic', 'true');
  document.body.append(announcement);
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let sequence = 0;
  let controller;
  let activeAnimation;
  let routing = false;
  let scrollFrame;
  history.scrollRestoration = 'manual';
  const saveScroll = () => {
    if (routing || keyFor(new URL(location.href)) !== keyFor(currentUrl)) return;
    history.replaceState({ ...history.state, scroll: [scrollX, scrollY] }, '', location.href);
  };
  saveScroll();
  window.addEventListener('scroll', () => {
    if (routing || scrollFrame) return;
    scrollFrame = requestAnimationFrame(() => { scrollFrame = null; saveScroll(); });
  }, { passive: true });
  const positionPage = (url, scroll) => {
    if (Array.isArray(scroll) && scroll.every(Number.isFinite)) window.scrollTo(scroll[0], scroll[1]);
    else if (url.hash) {
      let id;
      try { id = decodeURIComponent(url.hash.slice(1)); } catch { id = url.hash.slice(1); }
      const target = document.getElementById(id);
      if (target) target.scrollIntoView({ block: 'start' });
      else window.scrollTo(0, 0);
    } else window.scrollTo(0, 0);
  };
  const markNavigation = (url) => {
    const name = pageName(url);
    const active = ['index.html', 'publications.html', 'about-me.html'].includes(name) ? name : 'courses.html';
    for (const link of menu.querySelectorAll('a')) {
      if (pageName(new URL(link.href)) === active) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    }
  };
  const navigate = async (url, { push = true, scroll } = {}) => {
    if (push) saveScroll();
    const request = ++sequence;
    controller?.abort();
    activeAnimation?.cancel();
    closeMenu();
    if (keyFor(url) === keyFor(currentUrl)) {
      routing = true;
      root.classList.add('is-routing');
      if (push && url.href !== location.href) history.pushState({ scroll: null }, '', url.href);
      currentUrl = url;
      positionPage(url, scroll);
      root.classList.remove('is-routing', 'is-navigating');
      main.removeAttribute('aria-busy');
      routing = false;
      saveScroll();
      return;
    }
    routing = true;
    root.classList.add('is-routing', 'is-navigating');
    main.setAttribute('aria-busy', 'true');
    const attemptController = new AbortController();
    controller = attemptController;
    const timeout = setTimeout(() => attemptController.abort(), 12000);
    try {
      const page = await getPage(url, attemptController.signal);
      await Promise.all([...page.styles.map(loadStyle), ...page.images.map(warmImage)]);
      if (request !== sequence) return;
      const commit = () => {
        if (request !== sequence) return;
        main.innerHTML = page.content;
        initialisePage();
        document.body.className = page.bodyClass;
        root.lang = page.language;
        document.title = page.title;
        const description = document.querySelector('meta[name="description"]');
        if (description) description.content = page.description;
        if (push) history.pushState({ scroll: null }, '', url.href);
        currentUrl = url;
        markNavigation(url);
        positionPage(url, scroll);
        const heading = main.querySelector('h1');
        if (heading) { heading.tabIndex = -1; heading.focus({ preventScroll: true }); }
        announcement.textContent = `${page.title} loaded.`;
      };
      if (!reduceMotion.matches && typeof main.animate === 'function') {
        activeAnimation = main.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 100, easing: 'ease-in' });
        await activeAnimation.finished.catch(() => {});
        if (request !== sequence) return;
        commit();
        activeAnimation = main.animate([{ opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'none' }], { duration: 200, easing: 'ease-out' });
        await activeAnimation.finished.catch(() => {});
      } else commit();
    } catch (error) {
      if (request === sequence) location.assign(url.href);
    } finally {
      clearTimeout(timeout);
      if (request === sequence) {
        routing = false;
        root.classList.remove('is-routing', 'is-navigating');
        main.removeAttribute('aria-busy');
        activeAnimation = null;
        saveScroll();
      }
    }
  };
  document.addEventListener('click', (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest('a[href]');
    if (!link || link.hasAttribute('download') || (link.target && link.target !== '_self')) return;
    const url = new URL(link.href);
    if (!pageName(url)) return;
    // Native anchors keep smooth scrolling and work without the router.
    if (keyFor(url) === keyFor(currentUrl) && url.hash && !routing) return;
    event.preventDefault();
    navigate(url);
  });
  window.addEventListener('popstate', (event) => {
    const url = new URL(location.href);
    if (pageName(url)) navigate(url, { push: false, scroll: event.state?.scroll });
  });
  window.addEventListener('hashchange', () => {
    if (!routing && keyFor(new URL(location.href)) === keyFor(currentUrl)) currentUrl = new URL(location.href);
  });
})();

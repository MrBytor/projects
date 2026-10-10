(() => {
  'use strict';
  const dialog = document.getElementById('content-dialog');
  const slot = dialog?.querySelector('[data-dialog-slot]');
  const status = document.querySelector('[data-content-status]');
  let opener = null;
  let controller = null;
  let submitting = false;
  let oldOverflow = '';

  function closeMenus(except) {
    document.querySelectorAll('[data-content-menu][open]').forEach(menu => {
      if (menu !== except) menu.removeAttribute('open');
    });
  }

  function positionMenu(menu) {
    const list = menu.querySelector(':scope > .content-menu-list');
    if (!list || !menu.open) return;
    list.style.transform = '';
    const bounds = list.getBoundingClientRect();
    const offset = bounds.right > window.innerWidth - 12
      ? window.innerWidth - 12 - bounds.right
      : bounds.left < 12 ? 12 - bounds.left : 0;
    if (offset) list.style.transform = `translateX(${offset}px)`;
  }

  document.addEventListener('toggle', event => {
    if (event.target.matches('[data-content-menu]') && event.target.open) positionMenu(event.target);
  }, true);
  window.addEventListener('resize', () => {
    document.querySelectorAll('[data-content-menu][open]').forEach(positionMenu);
  });

  const tree = document.querySelector('[data-content-tree]');
  if (tree) {
    const folders = Array.from(tree.querySelectorAll('[data-content-folder]'));
    const storageKey = tree.dataset.folderStorageKey;
    let remembered = new Set();
    try {
      const stored = JSON.parse(sessionStorage.getItem(storageKey) || '[]');
      if (Array.isArray(stored)) remembered = new Set(stored.filter(id => typeof id === 'string' && /^\d+$/.test(id)));
    } catch (_) { /* Folder controls also work when browser storage is unavailable. */ }
    for (const folder of folders) folder.open = remembered.has(folder.dataset.contentFolder);

    function rememberFolders() {
      for (const folder of folders) {
        if (folder.open) remembered.add(folder.dataset.contentFolder);
        else remembered.delete(folder.dataset.contentFolder);
      }
      try { if (storageKey) sessionStorage.setItem(storageKey, JSON.stringify(Array.from(remembered))); } catch (_) { /* Optional persistence. */ }
    }

    function openLinkedFolder() {
      if (!/^#folder-\d+$/.test(window.location.hash)) return;
      const folder = document.getElementById(window.location.hash.slice(1));
      if (!folder?.matches('[data-content-folder]') || !tree.contains(folder)) return;
      let parent = folder;
      while (parent && tree.contains(parent)) {
        parent.open = true;
        parent = parent.parentElement?.closest('[data-content-folder]');
      }
      rememberFolders();
      requestAnimationFrame(() => folder.querySelector(':scope > summary')?.scrollIntoView({ block: 'start' }));
    }

    tree.addEventListener('toggle', event => {
      if (event.target.matches('[data-content-folder]')) rememberFolders();
    }, true);
    window.addEventListener('pagehide', rememberFolders);
    window.addEventListener('hashchange', openLinkedFolder);
    openLinkedFolder();
  }

  function prepareForm(root) {
    const sourceChoices = Array.from(root.querySelectorAll('[name="video_source"]'));
    if (sourceChoices.length) {
      const fileRow = root.querySelector('[data-field-name="file"]');
      const urlRow = root.querySelector('[data-field-name="url"]');
      const fileInput = fileRow?.querySelector('input[type="file"]');
      const selectedFile = document.createElement('p');
      selectedFile.className = 'helptext content-video-selection';
      selectedFile.setAttribute('role', 'status');
      selectedFile.hidden = true;
      fileInput?.after(selectedFile);
      function updateSource() {
        const source = sourceChoices.find(input => input.checked)?.value || sourceChoices[0].value;
        for (const [row, active] of [[fileRow, source === 'upload'], [urlRow, source === 'link']]) {
          if (!row) continue;
          row.hidden = !active;
          row.querySelectorAll('input, select, textarea').forEach(input => { input.disabled = !active; });
        }
      }
      sourceChoices.forEach(input => input.addEventListener('change', updateSource));
      updateSource();
      fileInput?.addEventListener('change', () => {
        const file = fileInput.files?.[0];
        const tooLarge = file && file.size > 100 * 1024 * 1024;
        fileInput.setCustomValidity(tooLarge ? 'Choose a video of 100 MB or less.' : '');
        const size = file && (file.size < 1024 * 1024 ? `${Math.max(1, Math.round(file.size / 1024))} KB` : `${(file.size / 1024 / 1024).toFixed(1)} MB`);
        selectedFile.textContent = file ? `${file.name} · ${size}${tooLarge ? ' — exceeds the 100 MB limit.' : ''}` : '';
        selectedFile.classList.toggle('is-error', Boolean(tooLarge));
        selectedFile.hidden = !file;
      });
    }
    const availability = root.querySelector('[name="availability"]');
    const dateSettings = root.querySelector('[data-availability-dates]');
    availability?.addEventListener('change', () => {
      if (dateSettings && availability.value === 'scheduled') dateSettings.open = true;
    });
    const colorSelect = root.querySelector('[data-field-name="color"] select');
    if (colorSelect && !root.querySelector('.content-color-options')) {
      const colors = { blue: '#70b3d7', yellow: '#e4bb53', green: '#97b96a', purple: '#a68dc3', red: '#d8787f', gray: '#96a3ae' };
      const swatches = document.createElement('div');
      swatches.className = 'content-color-options';
      swatches.setAttribute('role', 'group');
      swatches.setAttribute('aria-label', 'Folder color');
      for (const option of colorSelect.options) {
        if (!colors[option.value]) continue;
        const button = document.createElement('button');
        button.type = 'button';
        button.title = option.text;
        button.setAttribute('aria-label', option.text);
        button.setAttribute('aria-pressed', String(colorSelect.value === option.value));
        button.style.backgroundColor = colors[option.value];
        button.addEventListener('click', () => {
          colorSelect.value = option.value;
          for (const sibling of swatches.children) sibling.setAttribute('aria-pressed', String(sibling === button));
          colorSelect.dispatchEvent(new Event('change', { bubbles: true }));
        });
        swatches.append(button);
      }
      colorSelect.after(swatches);
      colorSelect.hidden = true;
    }
    const search = root.querySelector('[data-question-search]');
    const options = root.querySelector('[data-question-options]');
    const selection = root.querySelector('[data-question-selection]');
    const empty = root.querySelector('[data-question-empty]');
    if (!options) return;
    const checks = Array.from(options.querySelectorAll('input[type="checkbox"]'));
    const updateCount = () => {
      if (selection) selection.textContent = `${checks.filter(input => input.checked).length} selected`;
    };
    checks.forEach(input => input.addEventListener('change', updateCount));
    updateCount();
    search?.addEventListener('input', () => {
      const query = search.value.trim().toLocaleLowerCase();
      let visible = 0;
      for (const input of checks) {
        const label = input.closest('label');
        const row = label?.parentElement;
        if (!label || !row || row === options) continue;
        const match = label.textContent.toLocaleLowerCase().includes(query);
        row.hidden = !match;
        if (match) visible += 1;
      }
      if (empty) empty.hidden = visible > 0 || checks.length === 0;
    });
  }

  function focusForm() {
    const target = slot.querySelector('.content-form-error, input:not([type="hidden"]), select, textarea, [data-dialog-close]');
    target?.focus({ preventScroll: true });
    dialog.scrollTop = 0;
  }

  function replaceContent(html) {
    const documentFragment = new DOMParser().parseFromString(html, 'text/html');
    const content = documentFragment.querySelector('[data-dialog-content]');
    if (!content) throw new Error('The editor could not be loaded. Close this window and try again. If your session expired, sign in again.');
    slot.replaceChildren(content);
    prepareForm(content);
    focusForm();
  }

  function showLoadError(message) {
    const section = document.createElement('section');
    section.className = 'content-dialog-content';
    const body = document.createElement('div');
    body.className = 'content-dialog-body';
    const heading = document.createElement('h2');
    heading.id = 'content-dialog-title';
    heading.textContent = 'Unable to open editor';
    const text = document.createElement('p');
    text.className = 'content-network-error';
    text.setAttribute('role', 'alert');
    text.textContent = message;
    const footer = document.createElement('div');
    footer.className = 'content-dialog-footer';
    const close = document.createElement('button');
    close.type = 'button';
    close.textContent = 'Close';
    close.dataset.dialogClose = '';
    body.append(heading, text);
    footer.append(close);
    section.append(body, footer);
    slot.replaceChildren(section);
    close.focus();
  }

  async function openEditor(link) {
    opener = link;
    closeMenus();
    controller?.abort();
    controller = new AbortController();
    const activeController = controller;
    const loading = document.createElement('p');
    loading.className = 'content-dialog-loading';
    loading.id = 'content-dialog-title';
    loading.setAttribute('role', 'status');
    loading.textContent = 'Opening editor…';
    slot.replaceChildren(loading);
    if (!dialog.open) {
      oldOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
      dialog.showModal();
    }
    try {
      const url = new URL(link.href, window.location.href);
      if (url.origin !== window.location.origin) throw new Error('This editor is not available here.');
      const response = await fetch(url.href, {
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest', Accept: 'text/html' },
        signal: activeController.signal,
      });
      if (!response.ok) throw new Error('The editor could not be opened. Please close this window and try again.');
      const html = await response.text();
      if (controller === activeController && dialog.open) replaceContent(html);
    } catch (error) {
      if (error.name !== 'AbortError' && dialog.open && controller === activeController) showLoadError(error.message);
    }
  }

  document.addEventListener('click', event => {
    const close = event.target.closest('[data-dialog-close]');
    if (close && dialog?.open && dialog.contains(close)) {
      event.preventDefault();
      if (!submitting) dialog.close();
      return;
    }
    const link = event.target.closest('a[data-content-dialog]');
    if (link && dialog && typeof dialog.showModal === 'function' && event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
      event.preventDefault();
      openEditor(link);
      return;
    }
    const menu = event.target.closest('[data-content-menu]');
    closeMenus(menu);
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !dialog?.open) closeMenus();
  });

  document.querySelectorAll('[data-content-form]').forEach(prepareForm);
  document.querySelectorAll('[data-content-video]').forEach(player => {
    const error = player.closest('.content-video-panel')?.querySelector('[data-video-error]');
    function showVideoError() { if (error) error.hidden = false; }
    player.addEventListener('error', showVideoError);
    player.querySelectorAll('source').forEach(source => source.addEventListener('error', showVideoError));
    player.addEventListener('loadedmetadata', () => { if (error) error.hidden = true; });
    if (player.error) showVideoError();
  });
  if (!dialog || !slot) return;
  dialog.addEventListener('cancel', event => { if (submitting) event.preventDefault(); });
  dialog.addEventListener('close', () => {
    controller?.abort();
    document.body.style.overflow = oldOverflow;
    if (opener?.isConnected) {
      const menu = opener.closest('[data-content-menu]');
      const focusTarget = menu && !menu.open ? menu.querySelector('summary') : opener;
      focusTarget?.focus({ preventScroll: true });
    }
  });
  dialog.addEventListener('click', event => {
    if (event.target !== dialog || submitting) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
  dialog.addEventListener('submit', async event => {
    const form = event.target.closest('[data-content-form]');
    if (!form) return;
    event.preventDefault();
    if (submitting) return;
    const action = new URL(form.action, window.location.href);
    if (action.origin !== window.location.origin) return;
    const errorBox = form.querySelector('[data-form-error]');
    if (errorBox) errorBox.hidden = true;
    submitting = true;
    const content = form.closest('[data-dialog-content]');
    content.setAttribute('aria-busy', 'true');
    const submitButton = form.querySelector('button[type="submit"]');
    const submitText = submitButton?.textContent;
    const videoUpload = form.querySelector('[name="video_source"]:checked')?.value === 'upload' && form.querySelector('input[type="file"]')?.files?.length;
    if (submitButton) submitButton.textContent = videoUpload ? 'Uploading video…' : 'Saving…';
    const controls = Array.from(content.querySelectorAll('button, [data-dialog-close]'));
    controls.forEach(control => { if ('disabled' in control) control.disabled = true; });
    try {
      const response = await fetch(action.href, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json, text/html' },
        body: new FormData(form),
      });
      if (response.headers.get('content-type')?.includes('application/json')) {
        const result = await response.json();
        if (!response.ok || !result.redirect) throw new Error(result.error || 'Your changes could not be saved. Please try again.');
        const target = new URL(result.redirect, window.location.href);
        if (target.origin !== window.location.origin) throw new Error('Your changes were saved, but the destination could not be opened. Refresh the page.');
        if (status) status.textContent = 'Changes saved. Opening materials…';
        if (target.pathname === window.location.pathname && target.search === window.location.search) {
          window.history.replaceState(null, '', target.href);
          window.location.reload();
        } else {
          window.location.assign(target.href);
        }
        return;
      }
      if (!response.ok && response.status !== 400 && response.status !== 422) throw new Error('Your changes could not be saved. Please try again.');
      replaceContent(await response.text());
    } catch (error) {
      if (errorBox) {
        errorBox.textContent = error.message || 'The connection was interrupted. Check your connection and try again.';
        errorBox.hidden = false;
      }
    } finally {
      submitting = false;
      content.removeAttribute('aria-busy');
      if (submitButton) submitButton.textContent = submitText;
      controls.forEach(control => { if ('disabled' in control) control.disabled = false; });
    }
  });
})();

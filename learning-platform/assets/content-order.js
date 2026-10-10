(() => {
  'use strict';
  const tree = document.querySelector('[data-content-tree]');
  const handles = Array.from(tree?.querySelectorAll('[data-content-drag]') || []);
  if (!tree || !handles.length) return;

  const status = document.querySelector('[data-content-order-status]');
  const message = status?.querySelector('[data-content-order-message]');
  const reloadButton = status?.querySelector('[data-content-order-reload]');
  let active = null;
  let pointer = null;
  let pending = false;
  let needsReload = false;
  let scrollFrame = 0;

  const rows = container => Array.from(container.children).filter(node => node.matches('[data-content-item]'));
  const ids = container => rows(container).map(row => row.dataset.contentItem);
  const sameOrder = (left, right) => left.length === right.length && left.every((id, index) => id === right[index]);
  const title = row => row.querySelector(':scope > .content-folder > summary .content-folder-title')?.textContent.trim() || 'Folder';
  const canReorder = handle => !pending && !needsReload && rows(handle.closest('[data-content-item]').parentElement).length > 1;

  function announce(text, state = 'success', refresh = false) {
    if (!status || !message) return;
    message.textContent = text;
    status.dataset.state = state;
    status.hidden = false;
    if (reloadButton) reloadButton.hidden = !refresh;
  }

  function updateControls() {
    for (const handle of handles) {
      // Opening a folder stays available even when its order cannot change.
      handle.draggable = canReorder(handle);
    }
    tree.querySelectorAll('[data-content-item]').forEach(row => {
      const siblings = rows(row.parentElement);
      const index = siblings.indexOf(row);
      for (const direction of ['up', 'down']) {
        const input = row.querySelector(`:scope > .content-row-menu input[name="direction"][value="${direction}"]`);
        const button = input?.closest('form')?.querySelector('button');
        if (button) button.disabled = pending || needsReload || (direction === 'up' ? index === 0 : index === siblings.length - 1);
      }
    });
  }

  function clearMarker() {
    tree.querySelectorAll('.content-drop-before, .content-drop-after').forEach(row => row.classList.remove('content-drop-before', 'content-drop-after'));
    if (active) active.target = null;
  }

  function finishDrag() {
    clearMarker();
    active?.row.classList.remove('content-is-dragging');
    active?.handle.removeAttribute('aria-pressed');
    active = null;
    document.body.classList.remove('content-reordering');
    cancelAnimationFrame(scrollFrame);
    scrollFrame = 0;
  }

  function markTarget(element, y) {
    clearMarker();
    if (!active) return false;
    const row = element?.closest('[data-content-item]');
    // A drop only changes order inside the same folder. Moving into folders stays explicit.
    if (!row || row === active.row || row.parentElement !== active.container) return false;
    const heading = row.querySelector(':scope > .content-folder > summary') || row;
    const bounds = heading.getBoundingClientRect();
    const after = y >= bounds.top + bounds.height / 2;
    active.target = { row, after };
    row.classList.add(after ? 'content-drop-after' : 'content-drop-before');
    return true;
  }

  function autoScroll() {
    if (!active) return;
    const edge = 75;
    const { x, y } = active;
    let speed = 0;
    if (y < edge + 55) speed = -Math.min(20, Math.ceil((edge + 55 - y) / 5));
    else if (y > window.innerHeight - edge) speed = Math.min(20, Math.ceil((y - window.innerHeight + edge) / 5));
    if (speed && y >= 0 && y <= window.innerHeight) {
      window.scrollBy(0, speed);
      markTarget(document.elementFromPoint(x, y), y);
    }
    scrollFrame = requestAnimationFrame(autoScroll);
  }

  function beginDrag(handle, x, y, mode) {
    if (!canReorder(handle) || active) return false;
    const row = handle.closest('[data-content-item]');
    if (!row || rows(row.parentElement).length < 2) return false;
    tree.querySelectorAll('[data-content-menu][open]').forEach(menu => { menu.open = false; });
    active = { row, handle, container: row.parentElement, expected: ids(row.parentElement), x, y, mode, target: null };
    row.classList.add('content-is-dragging');
    handle.setAttribute('aria-pressed', 'true');
    document.body.classList.add('content-reordering');
    scrollFrame = requestAnimationFrame(autoScroll);
    return true;
  }

  async function saveOrder(row, handle, container, expected, order) {
    if (pending || needsReload || sameOrder(expected, order)) return;
    const form = row.querySelector(':scope > .content-row-menu input[name="direction"]')?.closest('form');
    const csrf = form?.querySelector('[name="csrfmiddlewaretoken"]')?.value;
    const account = form?.querySelector('[name="account_id"]')?.value;
    if (!csrf || !account) {
      announce('Please refresh this page before changing the order.', 'error', true);
      needsReload = true;
      updateControls();
      return;
    }
    const parent = row.dataset.contentParent || '';
    const data = new FormData();
    data.set('csrfmiddlewaretoken', csrf);
    data.set('account_id', account);
    data.set('order', order.join(','));
    data.set('expected_order', expected.join(','));
    data.set('parent', parent);
    pending = true;
    updateControls();
    tree.setAttribute('aria-busy', 'true');
    announce('Saving folder order…', 'saving');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const url = new URL(handle.dataset.reorderUrl, window.location.href);
      if (url.origin !== window.location.origin) throw new Error('Unexpected reorder address');
      const response = await fetch(url, { method: 'POST', credentials: 'same-origin', body: data, headers: { 'X-Requested-With': 'XMLHttpRequest' }, signal: controller.signal });
      const result = await response.json();
      if (!response.ok) {
        if (response.status === 409) {
          needsReload = true;
          announce('The materials changed. Refresh this page to load their latest order.', 'error', true);
        } else if (response.status === 400) {
          announce(typeof result.error === 'string' ? result.error : 'The order could not be saved. Please try again.', 'error');
        } else {
          needsReload = true;
          announce(typeof result.error === 'string' ? result.error : 'The order could not be saved. Please refresh this page.', 'error', true);
        }
        return;
      }
      const confirmed = Array.isArray(result.order) ? result.order.map(String) : [];
      if (!sameOrder(confirmed, order) || String(result.parent ?? '') !== parent || !sameOrder(ids(container), expected)) throw new Error('Unexpected saved order');
      const byId = new Map(rows(container).map(item => [item.dataset.contentItem, item]));
      // Keep the original nodes, expanded folders, and lesson controls intact.
      for (const id of confirmed) container.append(byId.get(id));
      announce(`${title(row)} moved. Order saved.`);
    } catch (_) {
      needsReload = true;
      announce('Could not confirm the new order. Refresh this page before trying again.', 'error', true);
    } finally {
      clearTimeout(timeout);
      pending = false;
      tree.removeAttribute('aria-busy');
      updateControls();
      if (!handle.disabled) handle.focus({ preventScroll: true });
    }
  }

  function drop() {
    if (!active) return;
    const { row, handle, container, expected, target } = active;
    if (!target) { finishDrag(); return; }
    const order = expected.filter(id => id !== row.dataset.contentItem);
    const targetIndex = order.indexOf(target.row.dataset.contentItem);
    order.splice(targetIndex + (target.after ? 1 : 0), 0, row.dataset.contentItem);
    finishDrag();
    void saveOrder(row, handle, container, expected, order);
  }

  for (const handle of handles) {
    const folder = handle.closest('[data-content-item]').querySelector(':scope > .content-folder');
    let suppressPointerClick = false;
    const syncExpanded = () => handle.setAttribute('aria-expanded', String(folder.open));
    const toggleFolder = () => {
      folder.open = !folder.open;
      syncExpanded();
    };
    folder.addEventListener('toggle', syncExpanded);
    syncExpanded();
    handle.hidden = false;
    handle.closest('.content-folder-row').classList.add('content-can-drag');
    handle.addEventListener('click', event => {
      event.preventDefault();
      // A drag or handled touch tap can produce a follow-up click. A new
      // pointer press resets this guard; keyboard activation stays available.
      if (active || (suppressPointerClick && (event.detail > 0 || event.pointerType))) return;
      toggleFolder();
    });
    handle.addEventListener('dragstart', event => {
      if (!event.dataTransfer || !beginDrag(handle, event.clientX, event.clientY, 'native')) { event.preventDefault(); return; }
      suppressPointerClick = true;
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', title(active.row));
      const ghost = document.createElement('div');
      ghost.className = 'content-drag-ghost';
      ghost.textContent = title(active.row);
      document.body.append(ghost);
      event.dataTransfer.setDragImage(ghost, 20, 20);
      setTimeout(() => ghost.remove(), 0);
    });
    handle.addEventListener('dragend', finishDrag);
    handle.addEventListener('keydown', event => {
      if (!event.altKey || !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
      event.preventDefault();
      if (pending || needsReload || active) return;
      const row = handle.closest('[data-content-item]');
      const container = row.parentElement;
      const expected = ids(container);
      const order = expected.slice();
      const index = order.indexOf(row.dataset.contentItem);
      const nextIndex = index + (event.key === 'ArrowUp' ? -1 : 1);
      if (nextIndex < 0 || nextIndex >= order.length) {
        announce(event.key === 'ArrowUp' ? 'This folder is already first.' : 'This folder is already last.');
        return;
      }
      [order[index], order[nextIndex]] = [order[nextIndex], order[index]];
      void saveOrder(row, handle, container, expected, order);
    });
    handle.addEventListener('pointerdown', event => {
      if (!event.isPrimary || event.button !== 0) return;
      suppressPointerClick = false;
      if (!['touch', 'pen'].includes(event.pointerType) || active || pointer) return;
      event.preventDefault();
      handle.focus({ preventScroll: true });
      pointer = { id: event.pointerId, handle, x: event.clientX, y: event.clientY, moved: false };
      handle.setPointerCapture(event.pointerId);
    });
    handle.addEventListener('pointermove', event => {
      if (!pointer || pointer.id !== event.pointerId) return;
      event.preventDefault();
      if (Math.hypot(event.clientX - pointer.x, event.clientY - pointer.y) >= 6) {
        pointer.moved = true;
        suppressPointerClick = true;
        if (!active) beginDrag(handle, event.clientX, event.clientY, 'pointer');
      }
      if (!active) return;
      active.x = event.clientX;
      active.y = event.clientY;
      markTarget(document.elementFromPoint(event.clientX, event.clientY), event.clientY);
    });
    handle.addEventListener('pointerup', event => {
      if (!pointer || pointer.id !== event.pointerId) return;
      event.preventDefault();
      const isTap = !pointer.moved && !active && Math.hypot(event.clientX - pointer.x, event.clientY - pointer.y) < 6;
      suppressPointerClick = true;
      pointer = null;
      if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
      if (isTap) toggleFolder();
      else drop();
    });
    for (const name of ['pointercancel', 'lostpointercapture']) handle.addEventListener(name, event => {
      if (!pointer || pointer.id !== event.pointerId) return;
      suppressPointerClick = true;
      pointer = null;
      finishDrag();
    });
  }

  document.addEventListener('dragover', event => {
    if (active?.mode !== 'native') return;
    active.x = event.clientX;
    active.y = event.clientY;
    const accepted = markTarget(event.target, event.clientY);
    // Prevent accidental navigation if a folder is released over an invalid target.
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = accepted ? 'move' : 'none';
  });
  document.addEventListener('drop', event => {
    if (active?.mode !== 'native') return;
    event.preventDefault();
    drop();
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !active) return;
    event.preventDefault();
    const handle = active.handle;
    finishDrag();
    pointer = null;
    handle.focus({ preventScroll: true });
    announce('Reordering cancelled.');
  });
  reloadButton?.addEventListener('click', () => window.location.reload());
  const help = document.getElementById('content-order-help');
  if (help) help.hidden = false;
  updateControls();
})();

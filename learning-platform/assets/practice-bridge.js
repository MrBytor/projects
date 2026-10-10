(() => {
  const queue = [];
  let sending = false;
  let teacher = false;
  const accountId = Number(document.querySelector('[data-account-id]')?.dataset.accountId) || null;
  const status = (message, retry = false) => {
    const workspace = document.querySelector('.practice-fullscreen-tools');
    let localStatus = document.getElementById('practice-save-status');
    if (workspace && !localStatus) {
      localStatus = document.createElement('p');
      localStatus.id = 'practice-save-status';
      localStatus.setAttribute('role', 'status');
      localStatus.style.fontSize = '14px';
      workspace.append(localStatus);
    }
    for (const node of [document.getElementById('platform-save-status'), localStatus].filter(Boolean)) {
      node.textContent = message;
      if (retry) {
        const button = document.createElement('button');
        button.type = 'button'; button.textContent = 'Retry saving';
        button.style.marginLeft = '12px';
        button.addEventListener('click', flush);
        node.append(button);
      }
    }
  };
  async function flush() {
    if (sending || teacher || !queue.length) return;
    sending = true;
    status('Saving practice…');
    while (queue.length) {
      try {
        const csrf = document.cookie.split('; ').find(x => x.startsWith('csrftoken='))?.split('=')[1];
        const response = await fetch('/api/practice/attempt/', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf || '' },
          body: JSON.stringify(queue[0])
        });
        if (!response.ok || response.redirected) throw new Error('Not saved');
        const result = await response.json();
        if (!result.saved) throw new Error('Not saved');
        queue.shift();
      } catch {
        sending = false;
        status('Practice has not saved. Keep this page open and retry; if your session expired, sign in in another tab first.', true);
        return;
      }
    }
    sending = false;
    status(teacher ? 'Teacher preview · results are not saved' : 'Practice saved to your account');
  }
  teacher = document.getElementById('platform-save-status')?.textContent.includes('Teacher preview');
  document.addEventListener('teaching:practice-attempt', event => {
    if (teacher) return;
    queue.push({ ...event.detail, account_id: accountId });
    flush();
  });
  window.addEventListener('beforeunload', event => {
    if (queue.length) { event.preventDefault(); event.returnValue = ''; }
  });
})();

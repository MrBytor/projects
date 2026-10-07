import { scoreAnswers, recordAttempt, selectQuestions, summariseSession } from './statistics-practice-core.mjs?v=20261006a';

let bankPromise;
let state;
const mounts = new WeakMap();
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));

function loadBank() {
  if (!bankPromise) bankPromise = fetch(new URL('./statistics-question-bank.json?v=20261007-bank240', import.meta.url))
    .then((response) => {
      if (!response.ok) throw new Error('Question bank unavailable');
      return response.json();
    }).then((bank) => {
      if (bank.version !== 1 || !bank.questions?.length || !Array.isArray(bank.weeks)) {
        throw new Error('Question bank unavailable');
      }
      return bank;
    }).catch((error) => { bankPromise = undefined; throw error; });
  return bankPromise;
}

function recordFor(id) {
  return state.records[id] ||= { values: {}, feedback: null, firstAttempt: null, solved: false,
    usedHelp: false, hintOpen: false, solutionOpen: false };
}

export async function mount(container) {
  if (!container) return;
  mounts.get(container)?.abort();
  const controller = new AbortController();
  mounts.set(container, controller);
  let bank;
  try { bank = await loadBank(); }
  catch {
    if (!controller.signal.aborted && container.isConnected) {
      container.innerHTML = '<div class="practice-notice" role="status"><p>The practice questions could not be loaded. Please try again.</p><button type="button" class="practice-secondary" data-reload-practice>Try again</button></div>';
      container.querySelector('[data-reload-practice]').addEventListener('click', () => mount(container), { signal: controller.signal });
    }
    return;
  }
  if (controller.signal.aborted || !container.isConnected) return;
  if (!state) state = { selectedIds: new Set(bank.questions.map((question) => question.id)),
    sessionIds: bank.questions.map((question) => question.id), mode: 'ordered', count: 'all',
    index: 0, records: {}, showSummary: false, openWeeks: new Set() };
  const questionsById = new Map(bank.questions.map((question) => [question.id, question]));
  const currentQuestion = () => questionsById.get(state.sessionIds[state.index]);
  const announce = (message) => { container.querySelector('.practice-status').textContent = message; };
  const focusHeading = () => {
    const heading = container.querySelector('.practice-question-heading');
    heading?.focus({ preventScroll: true });
    heading?.scrollIntoView({ block: 'start', behavior: 'auto' });
  };

  function renderSettings() {
    return `<aside id="practice-settings" class="practice-settings" aria-labelledby="practice-settings-title">
      <h2 id="practice-settings-title">Choose your practice</h2>
      <form id="practice-settings-form">
        <div class="practice-select-actions"><button type="button" class="practice-text-button" data-action="select-all">Select all</button><button type="button" class="practice-text-button" data-action="clear">Clear</button></div>
        <div class="practice-weeks">${bank.weeks.map((week) => {
          const questions = bank.questions.filter((question) => question.week === week.id);
          const selectedCount = questions.filter((question) => state.selectedIds.has(question.id)).length;
          return `<div class="practice-week"><div class="practice-week-heading"><input type="checkbox" id="practice-week-${week.id}" data-week="${week.id}" ${selectedCount === questions.length ? 'checked' : ''}><label for="practice-week-${week.id}">Week ${week.id}: ${escapeHtml(week.title)}</label></div>
            <details data-week-details="${week.id}" ${state.openWeeks.has(week.id) ? 'open' : ''}><summary>Choose questions</summary><div class="practice-topic-list">${questions.map((question) => `<label class="practice-topic" for="practice-topic-${escapeHtml(question.id)}"><input type="checkbox" id="practice-topic-${escapeHtml(question.id)}" data-question-id="${escapeHtml(question.id)}" ${state.selectedIds.has(question.id) ? 'checked' : ''}><span>${escapeHtml(question.id)} · ${escapeHtml(question.title)}</span></label>`).join('')}</div></details></div>`;
        }).join('')}</div>
        <p class="practice-selection" id="practice-selection-count"></p>
        <fieldset class="practice-mode-options"><legend>Question order</legend>
          <label for="practice-order-topics"><input type="radio" id="practice-order-topics" name="practice-order" value="ordered" ${state.mode === 'ordered' ? 'checked' : ''}> Topic order</label>
          <label for="practice-order-mixed"><input type="radio" id="practice-order-mixed" name="practice-order" value="mixed" ${state.mode === 'mixed' ? 'checked' : ''}> Mixed practice</label>
        </fieldset>
        <label class="practice-field-label" for="practice-question-count">Number of questions</label>
        <select id="practice-question-count">${['5', '10', '20', 'all'].map((count) => `<option value="${count}" ${state.count === count ? 'selected' : ''}>${count === 'all' ? 'All selected' : count}</option>`).join('')}</select>
        <p id="practice-settings-error" class="practice-inline-error" role="alert"></p>
        <button type="submit" class="btn btn-primary">Start practice</button>
      </form>
    </aside>`;
  }

  function updateSelection() {
    for (const week of bank.weeks) {
      const questions = bank.questions.filter((question) => question.week === week.id);
      const count = questions.filter((question) => state.selectedIds.has(question.id)).length;
      const checkbox = container.querySelector(`[data-week="${week.id}"]`);
      checkbox.checked = count === questions.length;
      checkbox.indeterminate = count > 0 && count < questions.length;
    }
    container.querySelectorAll('[data-question-id]').forEach((checkbox) => {
      checkbox.checked = state.selectedIds.has(checkbox.dataset.questionId);
    });
    const count = state.selectedIds.size;
    const limit = state.count === 'all' ? count : Math.min(count, Number(state.count));
    container.querySelector('#practice-selection-count').textContent = `${count} question${count === 1 ? '' : 's'} selected · ${limit} question${limit === 1 ? '' : 's'} in your next practice.`;
    container.querySelector('#practice-settings-error').textContent = '';
  }

  function fieldMarkup(field, question, record) {
    const id = `practice-answer-${question.id}-${field.id}`;
    const resultId = `${id}-result`;
    const value = record.values[field.id] ?? '';
    const result = record.feedback?.fields.find((item) => item.id === field.id);
    let feedback = '';
    if (result) {
      if (!result.valid) feedback = field.kind === 'choice' ? 'Choose an answer.' : 'Enter a valid number or fraction.';
      else if (record.feedback.valid) feedback = result.correct ? 'Correct.' : 'Not quite. Try again or open the hint.';
    }
    const invalid = result && (!result.valid || (record.feedback.valid && !result.correct));
    const label = `${escapeHtml(field.label)}${field.unit ? ` <span class="practice-field-unit">(${escapeHtml(field.unit)})</span>` : ''}`;
    const precision = field.kind !== 'number' ? '' : field.exact ? 'Enter the exact answer.' : field.integer ? 'Enter a whole number.' : field.decimals === 0 ? 'Round to a whole number.' : `Round to ${field.decimals} decimal place${field.decimals === 1 ? '' : 's'}.`;
    return `<div class="practice-field"><label class="practice-field-label" for="${escapeHtml(id)}">${label}</label>
      ${field.kind === 'choice' ? `<select id="${escapeHtml(id)}" data-answer-field="${escapeHtml(field.id)}" aria-required="true" aria-describedby="${escapeHtml(resultId)}" ${invalid ? 'aria-invalid="true"' : ''}><option value="">Choose an answer</option>${field.options.map((option) => `<option value="${escapeHtml(option.value)}" ${value === option.value ? 'selected' : ''}>${escapeHtml(option.label)}</option>`).join('')}</select>` : `<input type="text" inputmode="decimal" id="${escapeHtml(id)}" data-answer-field="${escapeHtml(field.id)}" value="${escapeHtml(value)}" autocomplete="off" spellcheck="false" aria-required="true" aria-describedby="${escapeHtml(id)}-help ${escapeHtml(resultId)}" ${invalid ? 'aria-invalid="true"' : ''}><p class="practice-field-help" id="${escapeHtml(id)}-help">${precision}${field.allowPercent ? ' You may include the % sign.' : ''}</p>`}
      <p class="practice-field-result ${feedback && result?.correct && record.feedback.valid ? 'is-correct' : feedback ? 'is-incorrect' : ''}" id="${escapeHtml(resultId)}">${feedback}</p></div>`;
  }

  function renderQuestion() {
    const question = currentQuestion();
    const record = recordFor(question.id);
    const summary = summariseSession(state.sessionIds, state.records);
    let feedback = '';
    if (record.feedback) {
      const message = !record.feedback.valid ? 'Complete each answer before checking.' : record.feedback.correct ? 'Correct — well done.' : 'Keep going. Check the feedback beside each answer.';
      feedback = `<p class="practice-feedback ${record.feedback.correct ? 'is-correct' : 'is-incorrect'}" role="status">${message}</p>`;
    }
    return `<div class="practice-progress"><span>Question ${state.index + 1} of ${state.sessionIds.length}</span><span> · ${summary.attempted} checked · ${summary.eventuallyCorrect} correct</span></div>
      <p class="practice-select-actions"><a href="#practice-settings">Choose topics</a></p>
      <div class="practice-question-select"><label for="practice-jump">Go to a question</label><select id="practice-jump">${state.sessionIds.map((id, index) => {
        const item = questionsById.get(id);
        return `<option value="${index}" ${index === state.index ? 'selected' : ''}>${escapeHtml(item.id)} · ${escapeHtml(item.topic)}${state.records[id]?.solved ? ' ✓' : ''}</option>`;
      }).join('')}</select></div>
      <article class="practice-card"><p class="practice-meta">Week ${question.week} · ${escapeHtml(question.id)} · ${escapeHtml(question.topic)}</p>
        <h2 class="practice-question-heading" tabindex="-1">${escapeHtml(question.title)}</h2>
        <div class="practice-question-body">${question.promptHtml}</div>
        <form id="practice-answer-form" novalidate>${question.fields.map((field) => fieldMarkup(field, question, record)).join('')}
          <div class="practice-actions"><button type="submit" class="btn btn-primary">Check answer</button><button type="button" class="practice-secondary" data-action="hint" aria-controls="practice-hint" aria-expanded="${record.hintOpen}">${record.hintOpen ? 'Hide hint' : 'Show hint'}</button></div>
          <div id="practice-answer-feedback">${feedback}</div>
        </form>
        <div class="practice-hint" id="practice-hint" ${record.hintOpen ? '' : 'hidden'}><h3>Hint</h3><p>${escapeHtml(question.hint)}</p></div>
        <details class="practice-solution" data-solution ${record.solutionOpen ? 'open' : ''}><summary>Worked solution</summary><div>${question.solutionHtml}</div></details>
      </article>
      <nav class="practice-nav" aria-label="Practice questions"><button type="button" class="practice-secondary" data-action="previous" ${state.index === 0 ? 'disabled' : ''}>Previous</button><button type="button" class="practice-text-button" data-action="results">View results</button><button type="button" class="btn btn-primary" data-action="next">${state.index === state.sessionIds.length - 1 ? 'View results' : 'Next question'}</button></nav>`;
  }

  function renderSummary() {
    const summary = summariseSession(state.sessionIds, state.records);
    return `<section class="practice-summary"><h2 class="practice-question-heading" tabindex="-1">Your practice results</h2>
      <p>You checked ${summary.attempted} of ${summary.total} questions. You can return to any question and keep practising.</p>
      <div class="practice-summary-stats"><div class="practice-stat"><strong>${summary.firstCorrectUnassisted}</strong><span>First try, without help</span></div><div class="practice-stat"><strong>${summary.firstCorrectAssisted}</strong><span>First try, with help</span></div><div class="practice-stat"><strong>${summary.eventuallyCorrect}</strong><span>Correct after any attempt</span></div><div class="practice-stat"><strong>${summary.unanswered}</strong><span>Unanswered</span></div></div>
      <p class="practice-notice">Opening a hint or solution before your first check counts as help. Unanswered questions are listed separately.</p>
      <div class="practice-table-scroll"><table class="practice-summary-table"><caption>Results by concept</caption><thead><tr><th scope="col">Question</th><th scope="col">Concept</th><th scope="col">Result</th></tr></thead><tbody>${state.sessionIds.map((id, index) => {
        const question = questionsById.get(id);
        const record = state.records[id];
        let result = !record?.firstAttempt ? 'Unanswered' : record.solved ? record.firstAttempt.correct ? `First try${record.firstAttempt.assisted ? ', with help' : ', without help'}` : 'Correct after practice' : 'Needs another try';
        return `<tr><th scope="row"><button type="button" class="practice-text-button" data-jump="${index}">${escapeHtml(id)}</button></th><td>${escapeHtml(question.topic)}</td><td>${result}</td></tr>`;
      }).join('')}</tbody></table></div>
      <div class="practice-actions"><button type="button" class="practice-secondary" data-action="back">Back to questions</button>${summary.retryIds.length ? `<button type="button" class="btn btn-primary" data-action="retry">Practise these ${summary.retryIds.length} questions</button>` : ''}</div>
      ${summary.retryIds.length ? '<p class="practice-selection">Practise these questions starts a fresh attempt at the unanswered questions and those still needing another try.</p>' : '<p class="practice-feedback is-correct">You have answered every question correctly. Choose another set when you are ready.</p>'}
    </section>`;
  }

  function renderWorkspace({ focus = false } = {}) {
    container.querySelector('.practice-workspace').innerHTML = state.showSummary ? renderSummary() : renderQuestion();
    if (focus) focusHeading();
  }

  function updateCurrentProgress() {
    const summary = summariseSession(state.sessionIds, state.records);
    const progress = container.querySelector('.practice-progress span:last-child');
    if (progress) progress.textContent = ` · ${summary.attempted} checked · ${summary.eventuallyCorrect} correct`;
    const question = currentQuestion();
    const option = container.querySelector(`#practice-jump option[value="${state.index}"]`);
    if (option) option.textContent = `${question.id} · ${question.topic}${state.records[question.id]?.solved ? ' ✓' : ''}`;
  }

  function startSession(ids) {
    if (!ids.length) return;
    state.sessionIds = ids;
    state.index = 0;
    state.records = {};
    state.showSummary = false;
    renderWorkspace({ focus: true });
    announce(`Practice started with ${ids.length} questions.`);
  }

  container.innerHTML = `<div class="practice-layout">${renderSettings()}<section class="practice-workspace" aria-label="Practice questions"></section></div><p class="practice-status route-announcement" role="status" aria-live="polite" aria-atomic="true"></p>`;
  updateSelection();
  renderWorkspace();

  container.addEventListener('change', (event) => {
    const target = event.target;
    if (target.matches('[data-week]')) {
      bank.questions.filter((question) => question.week === Number(target.dataset.week)).forEach((question) => {
        if (target.checked) state.selectedIds.add(question.id); else state.selectedIds.delete(question.id);
      });
      updateSelection();
    } else if (target.matches('[data-question-id]')) {
      if (target.checked) state.selectedIds.add(target.dataset.questionId); else state.selectedIds.delete(target.dataset.questionId);
      updateSelection();
    } else if (target.name === 'practice-order') state.mode = target.value;
    else if (target.id === 'practice-question-count') { state.count = target.value; updateSelection(); }
    else if (target.id === 'practice-jump') {
      state.index = Number(target.value);
      renderWorkspace({ focus: true });
      announce(`Question ${state.index + 1} of ${state.sessionIds.length}.`);
    }
  }, { signal: controller.signal });

  container.addEventListener('input', (event) => {
    if (!event.target.matches('[data-answer-field]')) return;
    const record = recordFor(currentQuestion().id);
    record.values[event.target.dataset.answerField] = event.target.value;
    record.solved = false;
    updateCurrentProgress();
    if (record.feedback) {
      record.feedback = null;
      container.querySelectorAll('.practice-field-result').forEach((node) => { node.textContent = ''; node.classList.remove('is-correct', 'is-incorrect'); });
      container.querySelectorAll('[data-answer-field]').forEach((node) => node.removeAttribute('aria-invalid'));
      container.querySelector('#practice-answer-feedback').innerHTML = '';
    }
  }, { signal: controller.signal });

  container.addEventListener('submit', (event) => {
    if (event.target.id === 'practice-settings-form') {
      event.preventDefault();
      if (!state.selectedIds.size) {
        container.querySelector('#practice-settings-error').textContent = 'Choose at least one question to start.';
        return;
      }
      startSession(selectQuestions(bank.questions, state.selectedIds, state));
    } else if (event.target.id === 'practice-answer-form') {
      event.preventDefault();
      const question = currentQuestion();
      const record = recordFor(question.id);
      event.target.querySelectorAll('[data-answer-field]').forEach((field) => { record.values[field.dataset.answerField] = field.value; });
      const result = scoreAnswers(question, record.values);
      record.usedHelp ||= record.hintOpen || container.querySelector('[data-solution]').open;
      state.records[question.id] = recordAttempt(record, result);
      renderWorkspace();
      const invalidField = !result.valid && result.fields.find((field) => !field.valid);
      const focusTarget = invalidField ? container.querySelector(`[data-answer-field="${invalidField.id}"]`) : container.querySelector('#practice-answer-form button[type="submit"]');
      focusTarget?.focus({ preventScroll: true });
      announce(!result.valid ? 'Complete each answer before checking.' : result.correct ? 'All answers are correct.' : 'Some answers need another try. A hint is available.');
    }
  }, { signal: controller.signal });

  container.addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (!button || !container.contains(button)) return;
    const action = button.dataset.action;
    if (button.dataset.jump !== undefined) {
      state.index = Number(button.dataset.jump); state.showSummary = false; renderWorkspace({ focus: true });
    } else if (action === 'select-all' || action === 'clear') {
      state.selectedIds = new Set(action === 'select-all' ? bank.questions.map((question) => question.id) : []);
      updateSelection();
    } else if (action === 'hint') {
      const record = recordFor(currentQuestion().id);
      record.hintOpen = !record.hintOpen;
      if (record.hintOpen) record.usedHelp = true;
      container.querySelector('#practice-hint').hidden = !record.hintOpen;
      button.textContent = record.hintOpen ? 'Hide hint' : 'Show hint';
      button.setAttribute('aria-expanded', String(record.hintOpen));
      announce(record.hintOpen ? `Hint: ${currentQuestion().hint}` : 'Hint hidden.');
    } else if (action === 'previous' || action === 'next') {
      if (action === 'previous') state.index = Math.max(0, state.index - 1);
      else if (state.index < state.sessionIds.length - 1) state.index += 1;
      else state.showSummary = true;
      renderWorkspace({ focus: true });
    } else if (action === 'results' || action === 'back') {
      state.showSummary = action === 'results'; renderWorkspace({ focus: true });
    } else if (action === 'retry') {
      startSession(summariseSession(state.sessionIds, state.records).retryIds);
    }
  }, { signal: controller.signal });

  container.addEventListener('toggle', (event) => {
    const details = event.target;
    if (details.matches('[data-week-details]')) {
      const week = Number(details.dataset.weekDetails);
      if (details.open) state.openWeeks.add(week); else state.openWeeks.delete(week);
    } else if (details.matches('[data-solution]')) {
      const record = recordFor(currentQuestion().id);
      record.solutionOpen = details.open;
      if (details.open) record.usedHelp = true;
    }
  }, { capture: true, signal: controller.signal });
}

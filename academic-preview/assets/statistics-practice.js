import { scoreAnswers, recordAttempt, selectQuestions, summariseSession, filterQuestions, setHelpOpen } from './statistics-practice-core.mjs?v=20261007-aligned';

let bankPromise;
let state;
const mounts = new WeakMap();
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
const difficultyLabels = { foundation: 'Foundation', standard: 'Standard', challenge: 'Challenge' };
const styleLabels = { calculation: 'Calculation', interpretation: 'Interpretation', 'error-analysis': 'Find the error', 'mixed-application': 'Mixed application', procedure: 'Choose a method' };

function loadBank() {
  if (!bankPromise) bankPromise = fetch(new URL('./statistics-question-bank.json?v=20261007-aligned', import.meta.url))
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
    usedHelp: false, hintOpen: false, solutionOpen: false, extensionOpen: false };
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
    sessionStarted: false, sessionIds: [], mode: 'ordered', count: 'all',
    index: 0, records: {}, showSummary: false, openWeeks: new Set(), openConcepts: new Set(),
    filters: { difficulty: 'all', questionStyle: 'all' } };
  const questionsById = new Map(bank.questions.map((question) => [question.id, question]));
  const conceptsById = new Map((bank.concepts || []).map((concept) => [concept.id, concept]));
  const objectivesById = new Map((bank.objectives || []).map((objective) => [objective.id, objective]));
  const conceptLabel = (question) => conceptsById.get(question.conceptId)?.label || question.topic;
  const conceptKey = (question) => question.conceptId || `${question.week}-${question.topic}`;
  const matchingQuestions = () => filterQuestions(bank.questions, state.filters);
  const currentQuestion = () => questionsById.get(state.sessionIds[state.index]);
  const announce = (message) => { container.querySelector('.practice-status').textContent = message; };
  const focusHeading = () => {
    const heading = container.querySelector('.practice-question-heading');
    heading?.focus({ preventScroll: true });
    heading?.scrollIntoView({ block: 'start', behavior: 'auto' });
  };

  function renderSettings() {
    const matching = matchingQuestions();
    return `<aside id="practice-settings" class="practice-settings" aria-labelledby="practice-settings-title">
      <h2 id="practice-settings-title" tabindex="-1">Choose your practice</h2>
      <form id="practice-settings-form">
        <p>Choose weeks and concepts, or keep all selected. Set your difficulty and number of questions, then select Start practice.</p>
        <div class="practice-select-actions"><button type="button" class="practice-text-button" data-action="select-all">Select matching</button><button type="button" class="practice-text-button" data-action="clear">Clear matching</button></div>
        <div class="practice-weeks">${bank.weeks.map((week) => {
          const questions = matching.filter((question) => question.week === week.id);
          const selectedCount = questions.filter((question) => state.selectedIds.has(question.id)).length;
          const groups = new Map();
          questions.forEach((question) => {
            const key = conceptKey(question);
            if (!groups.has(key)) groups.set(key, []);
            groups.get(key).push(question);
          });
          return `<div class="practice-week"><div class="practice-week-heading"><input type="checkbox" id="practice-week-${week.id}" data-week="${week.id}" ${questions.length && selectedCount === questions.length ? 'checked' : ''} ${questions.length ? '' : 'disabled'}><label for="practice-week-${week.id}">Week ${week.id}: ${escapeHtml(week.title)}</label></div>
            ${questions.length ? `<details data-week-details="${week.id}" ${state.openWeeks.has(week.id) ? 'open' : ''}><summary>${groups.size} concepts · ${questions.length} questions</summary><div class="practice-concept-list">${[...groups].map(([key, items], groupIndex) => {
              const inputId = `practice-concept-${week.id}-${groupIndex}`;
              return `<div class="practice-concept"><label class="practice-topic practice-concept-heading" for="${inputId}"><input type="checkbox" id="${inputId}" data-concept-id="${escapeHtml(key)}"><span>${escapeHtml(conceptLabel(items[0]))}<small>${items.length} question${items.length === 1 ? '' : 's'}</small></span></label>
                <details data-concept-details="${escapeHtml(key)}" ${state.openConcepts.has(key) ? 'open' : ''}><summary>Choose individual questions</summary><div class="practice-topic-list">${items.map((question) => `<label class="practice-topic" for="practice-topic-${escapeHtml(question.id)}"><input type="checkbox" id="practice-topic-${escapeHtml(question.id)}" data-question-id="${escapeHtml(question.id)}" ${state.selectedIds.has(question.id) ? 'checked' : ''}><span>${escapeHtml(question.id)} · ${escapeHtml(question.title)}<small>${escapeHtml(difficultyLabels[question.difficulty] || '')}</small></span></label>`).join('')}</div></details></div>`;
            }).join('')}</div></details>` : '<p class="practice-empty-filter">No questions match these filters.</p>'}</div>`;
        }).join('')}</div>
        <label for="practice-difficulty">Difficulty</label>
        <select id="practice-difficulty" aria-describedby="practice-difficulty-help"><option value="all">All levels</option>${Object.entries(difficultyLabels).map(([value, label]) => `<option value="${value}" ${state.filters.difficulty === value ? 'selected' : ''}>${label}</option>`).join('')}</select>
        <p class="practice-filter-help" id="practice-difficulty-help">Foundation: one skill. Standard: apply it. Challenge: combine, choose or explain.</p>
        <label for="practice-style">Question style</label>
        <select id="practice-style"><option value="all">All styles</option>${Object.entries(styleLabels).map(([value, label]) => `<option value="${value}" ${state.filters.questionStyle === value ? 'selected' : ''}>${label}</option>`).join('')}</select>
        <p class="practice-selection" id="practice-selection-count"></p>
        <fieldset class="practice-mode-options"><legend>Question order</legend>
          <label for="practice-order-topics"><input type="radio" id="practice-order-topics" name="practice-order" value="ordered" ${state.mode === 'ordered' ? 'checked' : ''}> Question order</label>
          <label for="practice-order-mixed"><input type="radio" id="practice-order-mixed" name="practice-order" value="mixed" ${state.mode === 'mixed' ? 'checked' : ''}> Mixed practice</label>
        </fieldset>
        <label class="practice-field-label" for="practice-question-count">Number of questions</label>
        <select id="practice-question-count">${['5', '10', '15', '20', 'all'].map((count) => `<option value="${count}" ${state.count === count ? 'selected' : ''}>${count === 'all' ? 'All selected' : count}</option>`).join('')}</select>
        <p id="practice-settings-error" class="practice-inline-error" role="alert"></p>
        <button type="submit" class="btn btn-primary">Start practice</button>
      </form>
    </aside>`;
  }

  function updateSelection() {
    const matching = matchingQuestions();
    for (const week of bank.weeks) {
      const questions = matching.filter((question) => question.week === week.id);
      const count = questions.filter((question) => state.selectedIds.has(question.id)).length;
      const checkbox = container.querySelector(`[data-week="${week.id}"]`);
      checkbox.checked = questions.length > 0 && count === questions.length;
      checkbox.indeterminate = count > 0 && count < questions.length;
    }
    container.querySelectorAll('[data-concept-id]').forEach((checkbox) => {
      const questions = matching.filter((question) => conceptKey(question) === checkbox.dataset.conceptId);
      const count = questions.filter((question) => state.selectedIds.has(question.id)).length;
      checkbox.checked = questions.length > 0 && count === questions.length;
      checkbox.indeterminate = count > 0 && count < questions.length;
    });
    container.querySelectorAll('[data-question-id]').forEach((checkbox) => {
      checkbox.checked = state.selectedIds.has(checkbox.dataset.questionId);
    });
    const count = matching.filter((question) => state.selectedIds.has(question.id)).length;
    const limit = state.count === 'all' ? count : Math.min(count, Number(state.count));
    container.querySelector('#practice-selection-count').textContent = `${count} matching question${count === 1 ? '' : 's'} selected · ${limit} question${limit === 1 ? '' : 's'} in your ${state.sessionStarted ? 'next ' : ''}practice. Changes apply when you start.`;
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

  function objectiveMarkup(id) {
    const objective = objectivesById.get(id);
    const title = objective?.label || id;
    const published = /^(\d+)([ABC])\.(\d+)$/.exec(id);
    return published && objective
      ? `<a class="practice-objective" href="statistics-week-${published[1].padStart(2, '0')}.html#objective-${published[1]}${published[2].toLowerCase()}-${published[3]}" title="${escapeHtml(title)}" aria-label="Objective ${escapeHtml(id)}: ${escapeHtml(title)}">${escapeHtml(id)}</a>`
      : `<span class="practice-objective" title="${escapeHtml(title)}" aria-label="Objective ${escapeHtml(id)}: ${escapeHtml(title)}">${escapeHtml(id)}</span>`;
  }

  function extensionMarkup(question, record) {
    if (!question.extension) return '';
    return `<section class="practice-extension" aria-labelledby="practice-extension-title">
      <h3 id="practice-extension-title">Optional practical task <span>Self-check · ungraded</span></h3>
      <p class="practice-notice">Try this on paper or in Excel, then compare your work. It does not affect your score. Opening its model answer before your first check counts as help.</p>
      <div class="practice-question-body">${question.extension.promptHtml}</div>
      <details class="practice-solution" data-extension-model data-help-question="${escapeHtml(question.id)}" ${record.extensionOpen ? 'open' : ''}><summary>Model answer and self-check</summary><div>${question.extension.modelAnswerHtml}</div><h4>Check your work</h4><ul>${question.extension.rubric.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul></details>
    </section>`;
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
      <p class="practice-select-actions"><a href="#practice-settings">Choose weeks, concepts and difficulty</a></p>
      <div class="practice-question-select"><label for="practice-jump">Go to a question</label><select id="practice-jump">${state.sessionIds.map((id, index) => {
        const item = questionsById.get(id);
        return `<option value="${index}" ${index === state.index ? 'selected' : ''}>${escapeHtml(item.id)} · ${escapeHtml(item.title)}${state.records[id]?.solved ? ' ✓' : ''}</option>`;
      }).join('')}</select></div>
      <article class="practice-card"><p class="practice-meta"><span>Week ${question.week}</span><span>${escapeHtml(question.id)}</span><span>${escapeHtml(conceptLabel(question))}</span></p>
        <p class="practice-skill-meta">${question.difficulty ? `<span class="practice-level" data-level="${escapeHtml(question.difficulty)}">${escapeHtml(difficultyLabels[question.difficulty])}</span>` : ''}${question.questionStyle ? `<span>${escapeHtml(styleLabels[question.questionStyle])}</span>` : ''}${question.primaryObjective ? `<span>Objective ${objectiveMarkup(question.primaryObjective)}</span>` : ''}${question.secondaryObjectives?.length ? `<span>Also practises ${question.secondaryObjectives.map(objectiveMarkup).join(', ')}</span>` : ''}</p>
        <h2 class="practice-question-heading" tabindex="-1">${escapeHtml(question.title)}</h2>
        <div class="practice-question-body">${question.promptHtml}</div>
        <form id="practice-answer-form" novalidate>${question.fields.map((field) => fieldMarkup(field, question, record)).join('')}
          <div class="practice-actions"><button type="submit" class="btn btn-primary">Check answer</button><button type="button" class="practice-secondary" data-action="hint" aria-controls="practice-hint" aria-expanded="${record.hintOpen}">${record.hintOpen ? 'Hide hint' : 'Show hint'}</button></div>
          <div id="practice-answer-feedback">${feedback}</div>
        </form>
        <div class="practice-hint" id="practice-hint" ${record.hintOpen ? '' : 'hidden'}><h3>Hint</h3><p>${escapeHtml(question.hint)}</p></div>
        <details class="practice-solution" data-solution data-help-question="${escapeHtml(question.id)}" ${record.solutionOpen ? 'open' : ''}><summary>Worked solution</summary><div>${question.solutionHtml}</div></details>
        ${extensionMarkup(question, record)}
      </article>
      <nav class="practice-nav" aria-label="Practice questions"><button type="button" class="practice-secondary" data-action="previous" ${state.index === 0 ? 'disabled' : ''}>Previous</button><button type="button" class="practice-text-button" data-action="results">View results</button><button type="button" class="btn btn-primary" data-action="next">${state.index === state.sessionIds.length - 1 ? 'View results' : 'Next question'}</button></nav>`;
  }

  function renderSummary() {
    const summary = summariseSession(state.sessionIds, state.records);
    return `<section class="practice-summary"><h2 class="practice-question-heading" tabindex="-1">Your practice results</h2>
      <p>You checked ${summary.attempted} of ${summary.total} questions. You can return to any question and keep practising.</p>
      <div class="practice-summary-stats"><div class="practice-stat"><strong>${summary.firstCorrectUnassisted}</strong><span>First try, without help</span></div><div class="practice-stat"><strong>${summary.firstCorrectAssisted}</strong><span>First try, with help</span></div><div class="practice-stat"><strong>${summary.eventuallyCorrect}</strong><span>Correct after any attempt</span></div><div class="practice-stat"><strong>${summary.unanswered}</strong><span>Unanswered</span></div></div>
      <p class="practice-notice">Opening a hint, worked solution or practical-task model answer before your first check counts as help. Practical tasks are self-checked and are not included in this score. Unanswered questions are listed separately.</p>
      <div class="practice-table-scroll"><table class="practice-summary-table"><caption>Results by concept</caption><thead><tr><th scope="col">Question</th><th scope="col">Concept</th><th scope="col">Result</th></tr></thead><tbody>${state.sessionIds.map((id, index) => {
        const question = questionsById.get(id);
        const record = state.records[id];
        let result = !record?.firstAttempt ? 'Unanswered' : record.solved ? record.firstAttempt.correct ? `First try${record.firstAttempt.assisted ? ', with help' : ', without help'}` : 'Correct after practice' : 'Needs another try';
        return `<tr><th scope="row"><button type="button" class="practice-text-button" data-jump="${index}">${escapeHtml(id)}</button></th><td>${escapeHtml(conceptLabel(question))}${question.primaryObjective ? `<small class="practice-result-objective">${objectiveMarkup(question.primaryObjective)}</small>` : ''}</td><td>${result}</td></tr>`;
      }).join('')}</tbody></table></div>
      <div class="practice-actions"><button type="button" class="practice-secondary" data-action="back">Back to questions</button>${summary.retryIds.length ? `<button type="button" class="btn btn-primary" data-action="retry">Practise these ${summary.retryIds.length} questions</button>` : ''}</div>
      ${summary.retryIds.length ? '<p class="practice-selection">Practise these questions starts a fresh attempt at the unanswered questions and those still needing another try.</p>' : '<p class="practice-feedback is-correct">You have answered every question correctly. Choose another set when you are ready.</p>'}
    </section>`;
  }

  function renderPreparation() {
    return `<article class="practice-preparation" aria-labelledby="practice-preparation-title">
      <p class="practice-preparation-kicker">A little preparation first</p>
      <h2 id="practice-preparation-title">Before you start</h2>
      <p class="practice-preparation-intro">Get your supplies ready and choose what you want to practise.</p>
      <figure class="practice-supplies">
        <img src="assets/practice-supplies.webp" alt="" width="1200" height="600" decoding="async">
        <figcaption><span>Calculator</span><span>Paper and pen</span></figcaption>
      </figure>
      <ol class="practice-preparation-steps">
        <li><div><h3>Prepare your calculator, paper and pen</h3><p>Write out your calculations on paper, then enter your answers here.</p></div></li>
        <li><div><h3>Choose the concepts you want to cover</h3><p>Select your weeks and concepts, or leave all selected to cover them all.</p></div></li>
        <li><div><h3>Choose your difficulty and number of questions</h3><p>Choose Foundation, Standard, Challenge or All levels. When you are ready, select <strong>Start practice</strong>.</p></div></li>
      </ol>
      <button type="button" class="btn btn-primary" data-action="choose-practice">Choose my practice</button>
      <p class="practice-preparation-note">Your first question appears only after you select Start practice.</p>
    </article>`;
  }

  function renderWorkspace({ focus = false } = {}) {
    const workspace = container.querySelector('.practice-workspace');
    workspace.setAttribute('aria-label', state.sessionStarted ? 'Practice questions' : 'Practice preparation');
    workspace.innerHTML = !state.sessionStarted ? renderPreparation() : state.showSummary ? renderSummary() : renderQuestion();
    container.querySelector('.practice-layout').classList.toggle('is-preparing', !state.sessionStarted);
    if (focus) focusHeading();
  }

  function updateCurrentProgress() {
    const summary = summariseSession(state.sessionIds, state.records);
    const progress = container.querySelector('.practice-progress span:last-child');
    if (progress) progress.textContent = ` · ${summary.attempted} checked · ${summary.eventuallyCorrect} correct`;
    const question = currentQuestion();
    const option = container.querySelector(`#practice-jump option[value="${state.index}"]`);
    if (option) option.textContent = `${question.id} · ${question.title}${state.records[question.id]?.solved ? ' ✓' : ''}`;
  }

  function startSession(ids) {
    if (!ids.length) return;
    state.sessionStarted = true;
    state.sessionIds = ids;
    state.index = 0;
    state.records = {};
    state.showSummary = false;
    renderWorkspace({ focus: true });
    announce(`Practice started with ${ids.length} questions.`);
  }

  container.innerHTML = `<div class="practice-layout"><section class="practice-workspace" aria-label="Practice preparation"></section>${renderSettings()}</div><p class="practice-status route-announcement" role="status" aria-live="polite" aria-atomic="true"></p>`;
  updateSelection();
  renderWorkspace();

  container.addEventListener('change', (event) => {
    const target = event.target;
    if (target.matches('[data-week]')) {
      matchingQuestions().filter((question) => question.week === Number(target.dataset.week)).forEach((question) => {
        if (target.checked) state.selectedIds.add(question.id); else state.selectedIds.delete(question.id);
      });
      updateSelection();
    } else if (target.matches('[data-concept-id]')) {
      matchingQuestions().filter((question) => conceptKey(question) === target.dataset.conceptId).forEach((question) => {
        if (target.checked) state.selectedIds.add(question.id); else state.selectedIds.delete(question.id);
      });
      updateSelection();
    } else if (target.matches('[data-question-id]')) {
      if (target.checked) state.selectedIds.add(target.dataset.questionId); else state.selectedIds.delete(target.dataset.questionId);
      updateSelection();
    } else if (target.id === 'practice-difficulty' || target.id === 'practice-style') {
      state.filters[target.id === 'practice-difficulty' ? 'difficulty' : 'questionStyle'] = target.value;
      container.querySelector('#practice-settings').outerHTML = renderSettings();
      updateSelection();
      container.querySelector(`#${target.id}`)?.focus({ preventScroll: true });
      announce(container.querySelector('#practice-selection-count').textContent);
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
      const ids = selectQuestions(bank.questions, state.selectedIds, state);
      if (!ids.length) {
        container.querySelector('#practice-settings-error').textContent = 'Choose at least one matching question, or change the difficulty or style.';
        return;
      }
      startSession(ids);
    } else if (event.target.id === 'practice-answer-form') {
      event.preventDefault();
      const question = currentQuestion();
      const record = recordFor(question.id);
      event.target.querySelectorAll('[data-answer-field]').forEach((field) => { record.values[field.dataset.answerField] = field.value; });
      const result = scoreAnswers(question, record.values);
      record.usedHelp ||= record.hintOpen || container.querySelector('[data-solution]').open || Boolean(container.querySelector('[data-extension-model]')?.open);
      state.records[question.id] = recordAttempt(record, result);
      renderWorkspace();
      const invalidField = !result.valid && result.fields.find((field) => !field.valid);
      const focusTarget = invalidField ? container.querySelector(`[data-answer-field="${invalidField.id}"]`) : container.querySelector('#practice-answer-form button[type="submit"]');
      focusTarget?.focus({ preventScroll: true });
      announce(!result.valid ? 'Complete each answer before checking.' : result.correct ? 'All answers are correct.' : 'Some answers need another try. A hint is available.');
    }
  }, { signal: controller.signal });

  container.addEventListener('click', (event) => {
    // Remember help immediately, even if a details element is closed before its queued toggle event.
    const details = event.target.closest('summary')?.parentElement;
    if (details?.matches('[data-solution], [data-extension-model]') && !details.open) {
      const id = details.dataset.helpQuestion;
      state.records[id] = setHelpOpen(recordFor(id), details.matches('[data-solution]') ? 'solution' : 'extension', true);
    }
    const button = event.target.closest('button');
    if (!button || !container.contains(button)) return;
    const action = button.dataset.action;
    if (action === 'choose-practice') {
      const heading = container.querySelector('#practice-settings-title');
      heading?.focus({ preventScroll: true });
      container.querySelector('#practice-settings')?.scrollIntoView({ block: 'start', behavior: 'auto' });
    } else if (button.dataset.jump !== undefined) {
      state.index = Number(button.dataset.jump); state.showSummary = false; renderWorkspace({ focus: true });
    } else if (action === 'select-all' || action === 'clear') {
      matchingQuestions().forEach((question) => {
        if (action === 'select-all') state.selectedIds.add(question.id); else state.selectedIds.delete(question.id);
      });
      updateSelection();
    } else if (action === 'hint') {
      const id = currentQuestion().id;
      const record = setHelpOpen(recordFor(id), 'hint', !recordFor(id).hintOpen);
      state.records[id] = record;
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
    } else if (details.matches('[data-concept-details]')) {
      const concept = details.dataset.conceptDetails;
      if (details.open) state.openConcepts.add(concept); else state.openConcepts.delete(concept);
    } else if (details.matches('[data-solution], [data-extension-model]')) {
      const id = details.dataset.helpQuestion;
      state.records[id] = setHelpOpen(recordFor(id), details.matches('[data-solution]') ? 'solution' : 'extension', details.open);
    }
  }, { capture: true, signal: controller.signal });
}

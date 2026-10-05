// Shared, deterministic rules for practice sessions and answer checking.
export function parseNumericAnswer(raw, { allowPercent = false } = {}) {
  if (typeof raw !== 'string') return null;
  let value = raw.trim();
  if (!value) return null;
  if (value.endsWith('%')) {
    if (!allowPercent) return null;
    value = value.slice(0, -1).trim();
  }
  const decimal = /^[+-]?(?:(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d*)?|\.\d+)$/;
  const parts = value.split('/');
  if (parts.length > 2 || parts.some((part) => !decimal.test(part.trim()))) return null;
  const numbers = parts.map((part) => Number(part.trim().replaceAll(',', '')));
  if (numbers.some((number) => !Number.isFinite(number))) return null;
  if (parts.length === 2 && numbers[1] === 0) return null;
  const result = parts.length === 2 ? numbers[0] / numbers[1] : numbers[0];
  return Number.isFinite(result) ? result : null;
}

export function numericMatches(actual, expected, decimals = 0, { exact = false, integer = false } = {}) {
  if (!Number.isFinite(actual) || !Number.isFinite(expected)) return false;
  if (integer && !Number.isInteger(actual)) return false;
  const tolerance = exact ? 0 : 0.5 * 10 ** -decimals;
  const epsilon = Number.EPSILON * Math.max(1, Math.abs(actual), Math.abs(expected)) * 8;
  return Math.abs(actual - expected) <= tolerance + epsilon;
}

export function scoreAnswers(question, values) {
  const fields = question.fields.map((field) => {
    const raw = String(values[field.id] ?? '');
    if (field.kind === 'choice') {
      const valid = field.options.some((option) => option.value === raw);
      return { id: field.id, valid, correct: valid && raw === field.answer };
    }
    const number = parseNumericAnswer(raw, field);
    return { id: field.id, valid: number !== null,
      correct: number !== null && numericMatches(number, field.answer, field.decimals, field) };
  });
  return { fields, valid: fields.every((field) => field.valid), correct: fields.every((field) => field.correct) };
}

export function recordAttempt(record, result) {
  return { ...record, feedback: result, solved: result.valid && result.correct,
    firstAttempt: record.firstAttempt || (result.valid ? { correct: result.correct, assisted: Boolean(record.usedHelp) } : null) };
}

function shuffled(items, random) {
  const result = [...items];
  for (let index = result.length - 1; index > 0; index -= 1) {
    const other = Math.floor(random() * (index + 1));
    [result[index], result[other]] = [result[other], result[index]];
  }
  return result;
}

export function selectQuestions(questions, selectedIds, { mode = 'ordered', count = 'all', random = Math.random } = {}) {
  const selected = selectedIds instanceof Set ? selectedIds : new Set(selectedIds);
  let available = questions.filter((question) => selected.has(question.id));
  if (mode === 'mixed') {
    const groups = new Map();
    available.forEach((question) => {
      if (!groups.has(question.week)) groups.set(question.week, []);
      groups.get(question.week).push(question);
    });
    const queues = shuffled([...groups.values()], random).map((group) => shuffled(group, random));
    available = [];
    while (queues.some((queue) => queue.length)) {
      for (const queue of queues) if (queue.length) available.push(queue.shift());
    }
  }
  const limit = count === 'all' ? available.length : Math.max(0, Math.floor(Number(count) || 0));
  return available.slice(0, limit).map((question) => question.id);
}

export function summariseSession(ids, records) {
  const summary = { total: ids.length, attempted: 0, unanswered: 0,
    firstCorrectUnassisted: 0, firstCorrectAssisted: 0, eventuallyCorrect: 0, retryIds: [] };
  for (const id of ids) {
    const record = records[id];
    if (record?.firstAttempt) {
      summary.attempted += 1;
      if (record.firstAttempt.correct) {
        if (record.firstAttempt.assisted) summary.firstCorrectAssisted += 1;
        else summary.firstCorrectUnassisted += 1;
      }
    } else summary.unanswered += 1;
    if (record?.solved) summary.eventuallyCorrect += 1;
    else summary.retryIds.push(id);
  }
  return summary;
}

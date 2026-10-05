import test from 'node:test';
import assert from 'node:assert/strict';
import { parseNumericAnswer, numericMatches, scoreAnswers, recordAttempt, selectQuestions, summariseSession } from '../assets/statistics-practice-core.mjs';

test('numeric input accepts useful classroom formats without accepting trailing junk', () => {
  const examples = new Map([['  -12.50 ', -12.5], ['.75', 0.75], ['+1,250.5', 1250.5], ['1 / 4', 0.25], ['-3/2', -1.5], ['0', 0]]);
  for (const [input, expected] of examples) assert.equal(parseNumericAnswer(input), expected, input);
  for (const input of ['', ' ', '12 apples', '1,23', '12,345,67', '1/0', '0/0', 'Infinity', 'NaN', '1e4', '1/2/3', '--2', '25%', '2 3', '1..2']) {
    assert.equal(parseNumericAnswer(input), null, input);
  }
  assert.equal(parseNumericAnswer('25%', { allowPercent: true }), 25);
  assert.equal(parseNumericAnswer('25', { allowPercent: true }), 25);
  assert.equal(parseNumericAnswer('25%%', { allowPercent: true }), null);
});

test('marking uses the requested rounding precision and safely handles zero and negative values', () => {
  assert.equal(numericMatches(3.14, Math.PI, 2), true);
  assert.equal(numericMatches(3.15, Math.PI, 2), false);
  assert.equal(numericMatches(-2.35, -2.345, 2), true);
  assert.equal(numericMatches(0, 0.0004, 3), true);
  assert.equal(numericMatches(0, 0.0006, 3), false);
  assert.equal(numericMatches(NaN, 1, 2), false);
  assert.equal(numericMatches(1, Infinity, 2), false);
});

test('multi-part questions require every valid field and distinguish omitted from incorrect answers', () => {
  const question = { fields: [
    { id: 'mean', kind: 'number', answer: 3.5, decimals: 1 },
    { id: 'type', kind: 'choice', answer: 'sample', options: [{ value: 'sample' }, { value: 'population' }] }
  ] };
  assert.deepEqual(scoreAnswers(question, { mean: '7/2', type: 'sample' }), {
    valid: true, correct: true, fields: [{ id: 'mean', valid: true, correct: true }, { id: 'type', valid: true, correct: true }]
  });
  const incomplete = scoreAnswers(question, { mean: '3.5' });
  assert.equal(incomplete.valid, false);
  assert.equal(incomplete.fields[1].valid, false);
  const wrong = scoreAnswers(question, { mean: '4', type: 'population' });
  assert.equal(wrong.valid, true);
  assert.equal(wrong.correct, false);
});

test('exact counts reject fractional near-misses while actual rounding questions retain their tolerance', () => {
  const countQuestion = { fields: [{ id: 'ways', kind: 'number', answer: 720, decimals: 0, exact: true }] };
  assert.equal(scoreAnswers(countQuestion, { ways: '720.4' }).correct, false);
  assert.equal(scoreAnswers(countQuestion, { ways: '1440/2' }).correct, true);
  assert.equal(numericMatches(720.4, 720, 0), true);
  assert.equal(numericMatches(720.4, 720, 0, { integer: true }), false);
  assert.equal(numericMatches(0.1 + 0.2, 0.3, 1, { exact: true }), true);
});

test('later edits and assisted retries do not rewrite the first checked result', () => {
  const question = { fields: [{ id: 'mean', kind: 'number', answer: 3.5, decimals: 1 },
    { id: 'median', kind: 'number', answer: 4, decimals: 0, exact: true }] };
  const firstResult = scoreAnswers(question, { mean: '3.5', median: '4' });
  const first = recordAttempt({ firstAttempt: null, usedHelp: false }, firstResult);
  const edited = { ...first, solved: false, feedback: null };
  assert.equal(summariseSession(['q'], { q: edited }).eventuallyCorrect, 0);
  assert.equal(summariseSession(['q'], { q: edited }).firstCorrectUnassisted, 1);
  const retried = recordAttempt({ ...edited, usedHelp: true }, scoreAnswers(question, { mean: '3.5', median: '5' }));
  assert.equal(retried.solved, false);
  assert.deepEqual(retried.firstAttempt, { correct: true, assisted: false });
  const partial = recordAttempt({ firstAttempt: null, usedHelp: false }, scoreAnswers(question, { mean: '3.5' }));
  assert.equal(partial.firstAttempt, null);
  assert.equal(partial.solved, false);
});

test('mixed practice has no repeats, respects selection and balances across weeks', () => {
  const questions = [1, 2, 3, 4].flatMap((week) => [1, 2, 3].map((item) => ({ id: `${week}-${item}`, week })));
  const selected = new Set(questions.map((question) => question.id));
  selected.delete('1-1');
  const ids = selectQuestions(questions, selected, { mode: 'mixed', count: 5, random: () => 0.37 });
  assert.equal(ids.length, 5);
  assert.equal(new Set(ids).size, 5);
  assert.equal(ids.includes('1-1'), false);
  assert.equal(new Set(ids.slice(0, 4).map((id) => id.split('-')[0])).size, 4);
  assert.equal(selectQuestions(questions, selected, { mode: 'mixed', count: 20 }).length, 11);
  assert.deepEqual(selectQuestions(questions, new Set(), { count: 'all' }), []);
  assert.deepEqual(selectQuestions(questions, selected, { count: 2 }), ['1-2', '1-3']);
});

test('summary keeps unanswered, assisted first tries and later corrections separate', () => {
  const records = {
    a: { firstAttempt: { correct: true, assisted: false }, solved: true },
    b: { firstAttempt: { correct: true, assisted: true }, solved: true },
    c: { firstAttempt: { correct: false, assisted: false }, solved: true },
    d: { firstAttempt: { correct: false, assisted: false }, solved: false },
    e: { firstAttempt: null, solved: false }
  };
  assert.deepEqual(summariseSession(['a', 'b', 'c', 'd', 'e', 'f'], records), {
    total: 6, attempted: 4, unanswered: 2, firstCorrectUnassisted: 1,
    firstCorrectAssisted: 1, eventuallyCorrect: 3, retryIds: ['d', 'e', 'f']
  });
});

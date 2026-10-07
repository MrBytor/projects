import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { scoreAnswers } from '../assets/statistics-practice-core.mjs';

const bank = JSON.parse(fs.readFileSync(new URL('../assets/statistics-question-bank.json', import.meta.url), 'utf8'));

test('every practice question and answer part has valid objective and concept links', () => {
  const objectives = new Map(bank.objectives.map((item) => [item.id, item]));
  const concepts = new Map(bank.concepts.map((item) => [item.id, item]));
  assert.equal(objectives.size, bank.objectives.length);
  assert.equal(concepts.size, bank.concepts.length);
  assert.equal(new Set(bank.questions.map((item) => item.id)).size, bank.questions.length);
  for (const question of bank.questions) {
    assert.ok(objectives.has(question.primaryObjective), question.id);
    assert.ok(concepts.has(question.conceptId), question.id);
    assert.equal(concepts.get(question.conceptId).week, question.week, question.id);
    assert.ok(['foundation', 'standard', 'challenge'].includes(question.difficulty), question.id);
    assert.ok(['calculation', 'interpretation', 'error-analysis', 'mixed-application', 'procedure'].includes(question.questionStyle), question.id);
    assert.ok(Array.isArray(question.secondaryObjectives), question.id);
    assert.equal(new Set([question.primaryObjective, ...question.secondaryObjectives]).size, question.secondaryObjectives.length + 1, question.id);
    for (const id of question.secondaryObjectives) assert.ok(objectives.has(id), `${question.id}: ${id}`);
    assert.ok(question.hint && question.solutionHtml && question.promptHtml, question.id);
    assert.ok(question.fields.length > 0, question.id);
    assert.equal(new Set(question.fields.map((field) => field.id)).size, question.fields.length, question.id);
    for (const field of question.fields) {
      assert.ok(field.objectiveIds?.length > 0, `${question.id}: ${field.id}`);
      for (const id of field.objectiveIds) {
        assert.ok(objectives.has(id), `${question.id}: ${field.id}: ${id}`);
        assert.ok([question.primaryObjective, ...question.secondaryObjectives].includes(id), `${question.id}: field objective missing from question`);
      }
    }
    if (question.extension) {
      assert.ok(question.extension.promptHtml && question.extension.modelAnswerHtml, question.id);
      assert.ok(question.extension.rubric?.length > 0, question.id);
      assert.equal(question.extension.assessmentMode, 'self-check', question.id);
      assert.ok(question.extension.objectiveIds?.length > 0, question.id);
      for (const id of question.extension.objectiveIds) {
        assert.ok(objectives.has(id), question.id);
        assert.ok([question.primaryObjective, ...question.secondaryObjectives].includes(id), question.id);
      }
    }
  }
  for (const concept of concepts.values()) {
    assert.ok(concept.label && concept.objectiveIds.length, concept.id);
    for (const id of concept.objectiveIds) assert.ok(objectives.has(id), concept.id);
    assert.ok(bank.questions.some((question) => question.conceptId === concept.id), concept.id);
  }
});

test('all 335 questions from the aligned bank remain available', () => {
  const ids = new Set(bank.questions.map((question) => question.id));
  for (const [week, count] of [[1, 84], [2, 69], [3, 99], [4, 83]]) {
    for (let index = 1; index <= count; index++) assert.ok(ids.has(`W${week}-${String(index).padStart(2, '0')}`));
  }
});

test('each Class A/B objective has at least twice its aligned-bank primary coverage', () => {
  const baseline = {
    '1A.1': 9, '1A.2': 16, '1A.3': 6, '1A.4': 7,
    '1B.1': 10, '1B.2': 7, '1B.3': 8, '1B.4': 21,
    '2A.1': 4, '2A.2': 3, '2A.3': 7, '2A.4': 3, '2A.5': 8,
    '2B.1': 5, '2B.2': 3, '2B.3': 15, '2B.4': 5, '2B.5': 7, '2B.6': 6,
    '3A.1': 17, '3A.2': 10, '3A.3': 3, '3A.4': 6,
    '3B.1': 25, '3B.2': 4, '3B.3': 11, '3B.4': 5,
    '4A.1': 21, '4A.2': 6, '4A.3': 7, '4A.4': 5,
    '4B.1': 18, '4B.2': 5, '4B.3': 5, '4B.4': 4, '4B.5': 4,
  };
  for (const [id, count] of Object.entries(baseline)) {
    assert.ok(bank.questions.filter((question) => question.primaryObjective === id).length >= count * 2, id);
  }
  const contextual = bank.questions.filter((question) => question.primaryObjective === '1C.3');
  assert.ok(contextual.length >= 8, 'dedicated contextual equations and units practice');
  for (const question of contextual) {
    assert.ok(question.fields.some((field) => field.objectiveIds.includes('1C.3')), question.id);
  }
});

test('all stored answers can be submitted at the displayed precision, and wrong or blank answers fail', () => {
  for (const question of bank.questions) {
    const correct = {};
    for (const field of question.fields) {
      if (field.kind === 'number') {
        assert.ok(Number.isFinite(field.answer), question.id);
        assert.ok(Number.isInteger(field.decimals) && field.decimals >= 0, question.id);
        correct[field.id] = field.exact ? String(field.answer) : field.answer.toFixed(field.decimals);
      } else {
        assert.equal(field.kind, 'choice', question.id);
        assert.equal(new Set(field.options.map((option) => option.value)).size, field.options.length, question.id);
        assert.ok(field.options.length >= 2, question.id);
        assert.equal(field.options.filter((option) => option.value === field.answer).length, 1, question.id);
        correct[field.id] = field.answer;
      }
    }
    assert.equal(scoreAnswers(question, correct).correct, true, question.id);
    assert.equal(scoreAnswers(question, {}).valid, false, question.id);
    for (const field of question.fields) {
      const wrong = field.kind === 'number' ? String(field.answer + 10) : field.options.find((option) => option.value !== field.answer).value;
      assert.equal(scoreAnswers(question, { ...correct, [field.id]: wrong }).correct, false, `${question.id}: ${field.id}`);
    }
  }
});

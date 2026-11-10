// Copyright NGGT.LightKeeper. All Rights Reserved.

// Branching rules of the survey page. They mirror Apps/API/surveys.py; the server checks the path
// again when the answers are submitted.

export const CHOICE_KINDS = ['single', 'multiple'];
export const NUMBER_KINDS = ['scale', 'enps'];

export function emptyAnswer() {
  return { options: [], number: null, text: '' };
}

export function isAnswered(answer) {
  return answer.options.length > 0 || answer.number !== null || answer.text.trim() !== '';
}

// Return [min, max] of a numeric question, or null for other kinds.
export function valueRange(question) {
  if (question.kind === 'enps') {
    return [0, 10];
  }
  if (question.kind === 'scale') {
    return [Number(question.scale_min), Number(question.scale_max)];
  }
  return null;
}

export function ruleMatches(rule, answer) {
  switch (rule.operator) {
    case 'chosen':
      return answer.options.includes(String(rule.option));
    case 'not_chosen':
      return !answer.options.includes(String(rule.option));
    case 'range':
      if (answer.number === null) {
        return false;
      }
      return (rule.min === null || answer.number >= rule.min) && (rule.max === null || answer.number <= rule.max);
    case 'answered':
      return isAnswered(answer);
    case 'skipped':
      return !isAnswered(answer);
    case 'always':
      return true;
    default:
      return false;
  }
}

// Return the key of the question after the one at index, or null when the survey ends there.
export function nextKey(questions, index, answer) {
  for (const rule of questions[index].rules || []) {
    if (ruleMatches(rule, answer)) {
      return rule.target === null || rule.target === undefined || rule.target === '' ? null : String(rule.target);
    }
  }
  return index + 1 < questions.length ? String(questions[index + 1].key) : null;
}

// Return the keys of the questions on the path the answers lead through; jumps go forward only.
export function walk(questions, answers) {
  const positions = new Map(questions.map(function position(question, index) {
    return [String(question.key), index];
  }));
  const path = [];
  let index = questions.length ? 0 : null;
  while (index !== null) {
    const key = String(questions[index].key);
    path.push(key);
    const target = nextKey(questions, index, answers[key] || emptyAnswer());
    const targetIndex = target === null ? undefined : positions.get(target);
    index = targetIndex !== undefined && targetIndex > index ? targetIndex : null;
  }
  return path;
}

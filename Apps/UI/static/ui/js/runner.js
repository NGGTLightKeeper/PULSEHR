// Copyright NGGT.LightKeeper. All Rights Reserved.

import { emptyAnswer, isAnswered, nextKey, valueRange, walk } from './branching.js';
import { escHtml, setBusy } from './common.js';

// Longest free-form answer, as the server accepts it.
const MAX_TEXT_LENGTH = 2000;

// Survey runner.
// Show the questions one by one along the branching path. onSubmit gets the answers of the path
// and returns a promise; its errors (answers by question key) bring the user back to the question.
export function createSurveyRunner($container, questions, options) {
  const settings = options || {};
  const positions = new Map(questions.map(function position(question, index) {
    return [String(question.key), index];
  }));
  const answers = {};
  const history = [];
  let index = 0;
  let questionError = '';

  function answerOf(question) {
    const key = String(question.key);
    if (!answers[key]) {
      answers[key] = emptyAnswer();
    }
    return answers[key];
  }


  // Inputs of the question kinds.
  function choicesHtml(question, answer) {
    const type = question.kind === 'single' ? 'radio' : 'checkbox';
    const items = question.options.map(function optionHtml(option) {
      const key = String(option.key);
      const selected = answer.options.includes(key);
      return `
        <label class="choice ${selected ? 'selected' : ''}">
          <input type="${type}" name="answer" value="${escHtml(key)}" ${selected ? 'checked' : ''}>
          <span>${escHtml(option.text)}</span>
        </label>`;
    });
    return `<div class="choice-list">${items.join('')}</div>`;
  }

  function scaleHtml(question, answer) {
    const [low, high] = valueRange(question);
    const buttons = [];
    for (let value = low; value <= high; value += 1) {
      const selected = answer.number === value ? 'selected' : '';
      buttons.push(`<button type="button" class="scale-btn ${selected}" data-value="${value}">${value}</button>`);
    }
    const labels = question.min_label || question.max_label
      ? `<div class="scale-labels"><span>${escHtml(question.min_label)}</span><span>${escHtml(question.max_label)}</span></div>`
      : '';
    return `<div class="scale">${buttons.join('')}</div>${labels}`;
  }

  function textHtml(answer) {
    return `
      <div class="field">
        <textarea class="textarea" name="answer" maxlength="${MAX_TEXT_LENGTH}" rows="5" placeholder="Ваш ответ">${escHtml(answer.text)}</textarea>
        <span class="text-counter">${answer.text.length} / ${MAX_TEXT_LENGTH}</span>
      </div>`;
  }


  // Rendering.
  // Return whether the current question lets the user go on.
  function canContinue(question) {
    return !question.is_required || isAnswered(answerOf(question));
  }

  function updateNav() {
    const question = questions[index];
    const isLast = nextKey(questions, index, answerOf(question)) === null;
    $container.find('[data-next]')
      .prop('disabled', !canContinue(question))
      .text(isLast ? (settings.submitText || 'Отправить') : 'Далее');
  }

  function render() {
    const question = questions[index];
    const answer = answerOf(question);
    const pathLength = walk(questions, answers).length;
    const position = history.length + 1;
    const progress = Math.min(100, Math.round(((position - 1) / Math.max(pathLength, position)) * 100));

    let input = '';
    if (question.kind === 'single' || question.kind === 'multiple') {
      input = choicesHtml(question, answer);
    } else if (question.kind === 'scale' || question.kind === 'enps') {
      input = scaleHtml(question, answer);
    } else {
      input = textHtml(answer);
    }

    const hint = question.kind === 'multiple' ? 'Можно выбрать несколько вариантов.' : '';
    const help = [question.help_text, hint].filter(Boolean).map(escHtml).join(' ');
    $container.html(`
      <div class="runner">
        <div class="runner-progress">
          <span>Вопрос ${position} из ${Math.max(pathLength, position)}</span>
          <div class="progress"><div class="progress-bar" style="width:${progress}%"></div></div>
        </div>
        <div>
          <div class="question-title">${escHtml(question.text)}${question.is_required ? '' : ' <span class="badge">необязательный</span>'}</div>
          ${help ? `<div class="question-help">${help}</div>` : ''}
          ${input}
          ${questionError ? `<div class="form-error" role="alert">${escHtml(questionError)}</div>` : ''}
        </div>
        <div class="runner-nav">
          <button type="button" class="btn" data-back ${history.length ? '' : 'disabled'}>Назад</button>
          <button type="button" class="btn btn-primary" data-next>Далее</button>
        </div>
      </div>`);
    updateNav();
  }


  // Navigation.
  // Go to the question with the given key, rebuilding the history along the current path.
  function goToKey(key) {
    const path = walk(questions, answers);
    const stop = path.indexOf(String(key));
    if (stop < 0) {
      return;
    }
    history.length = 0;
    path.slice(0, stop).forEach(function addStep(stepKey) {
      history.push(positions.get(stepKey));
    });
    index = positions.get(String(key));
  }

  async function submit($button) {
    const payload = {};
    walk(questions, answers).forEach(function collect(key) {
      if (answers[key] && isAnswered(answers[key])) {
        payload[key] = answers[key];
      }
    });

    setBusy($button, true);
    try {
      await settings.onSubmit(payload);
    } catch (error) {
      setBusy($button, false);
      const fieldErrors = (error.data && error.data.errors && error.data.errors.answers) || {};
      const failedKey = Object.keys(fieldErrors).find(function onPath(key) {
        return positions.has(key);
      });
      if (failedKey) {
        goToKey(failedKey);
        questionError = String(fieldErrors[failedKey]);
      } else {
        questionError = error.message || 'Не удалось отправить ответы.';
      }
      render();
    }
  }

  $container.on('change', 'input[name=answer]', function onChoice() {
    const question = questions[index];
    const answer = answerOf(question);
    answer.options = $container.find('input[name=answer]:checked').map(function value() {
      return this.value;
    }).get();
    $container.find('.choice').each(function markSelected() {
      $(this).toggleClass('selected', $(this).find('input').prop('checked'));
    });
    questionError = '';
    updateNav();
  });

  $container.on('click', '.scale-btn', function onScale() {
    const answer = answerOf(questions[index]);
    answer.number = Number($(this).data('value'));
    $container.find('.scale-btn').removeClass('selected');
    $(this).addClass('selected');
    questionError = '';
    updateNav();
  });

  $container.on('input', 'textarea[name=answer]', function onText() {
    const answer = answerOf(questions[index]);
    answer.text = String($(this).val() || '');
    $container.find('.text-counter').text(`${answer.text.length} / ${MAX_TEXT_LENGTH}`);
    updateNav();
  });

  $container.on('click', '[data-back]', function onBack() {
    if (history.length) {
      index = history.pop();
      questionError = '';
      render();
    }
  });

  $container.on('click', '[data-next]', function onNext() {
    const question = questions[index];
    if (!canContinue(question)) {
      return;
    }
    const target = nextKey(questions, index, answerOf(question));
    if (target === null || !positions.has(target) || positions.get(target) <= index) {
      submit($(this));
      return;
    }
    history.push(index);
    index = positions.get(target);
    questionError = '';
    render();
  });

  if (questions.length) {
    render();
  } else {
    $container.html('<div class="empty">В опросе пока нет вопросов.</div>');
  }
}

// Copyright NGGT.LightKeeper. All Rights Reserved.

import { getJson, postJson } from '../api.js';
import { escHtml, formatDate } from '../common.js';
import { createSurveyRunner } from '../runner.js';

// Survey page.
// Explain how the answers are stored, then run the questions and send the answers.
$(function initSurveyPage() {
  const $page = $('#surveyPage');
  const surveyId = $page.data('survey-id');

  // Tell the employee whether the answers are anonymous, and what that means.
  function modeBanner(survey) {
    if (survey.mode === 'anonymous') {
      return `
        <div class="alert">
          <div>
            <strong>Опрос анонимный.</strong>
            <div class="small muted">Ответы хранятся отдельно от профиля: без имени, контактов и времени, только с датой.
            HR видит итоги, только когда ответов достаточно, чтобы никого нельзя было узнать.
            Не указывайте в свободных ответах то, что может вас выдать.</div>
          </div>
        </div>`;
    }
    return `
      <div class="alert">
        <div>
          <strong>Опрос не анонимный.</strong>
          <div class="small muted">HR увидит ваши ответы вместе с именем пользователя @${escHtml(survey.username)}.</div>
        </div>
      </div>`;
  }

  function closedMessage(survey) {
    const text = survey.completed
      ? 'Вы уже прошли этот опрос.'
      : `Опрос ${survey.status === 'closed' ? 'завершён' : 'пока недоступен'}.`;
    return `<div class="card"><p>${text}</p><a class="btn" href="/">На главную</a></div>`;
  }

  async function load() {
    let survey;
    try {
      survey = await getJson(`/api/v1/surveys/${surveyId}/`);
    } catch (error) {
      $page.html(`<div class="card"><p>${escHtml(error.message)}</p><a class="btn" href="/">На главную</a></div>`);
      return;
    }

    document.title = `${survey.title} · PULSEHR`;
    if (!survey.can_answer) {
      $page.html(closedMessage(survey));
      return;
    }

    const deadline = survey.ends_at ? `<span class="muted small">Открыт до ${formatDate(survey.ends_at)}</span>` : '';
    $page.html(`
      <div class="stack">
        <div>
          <h1>${escHtml(survey.title)}</h1>
          ${survey.description ? `<p class="muted">${escHtml(survey.description)}</p>` : ''}
          ${deadline}
        </div>
        ${modeBanner(survey)}
        <section class="card" id="runner"></section>
      </div>`);

    createSurveyRunner($('#runner'), survey.questions, {
      onSubmit: async function submitAnswers(answers) {
        await postJson(`/api/v1/surveys/${surveyId}/submit/`, { answers });
        window.location.href = `/surveys/${surveyId}/done/`;
      }
    });
  }

  load();
});

// Copyright NGGT.LightKeeper. All Rights Reserved.

import { getJson, postJson } from '../api.js';
import { ICONS, escHtml, formatDate } from '../common.js';
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
        <div class="alert alert-success">
          ${ICONS.shield}
          <div>
            <strong>Опрос анонимный.</strong>
            <div class="small">Ответы хранятся отдельно от вашего профиля: в них нет имени, контактов и времени ответа, только дата.
            HR видит итоги, только когда ответов достаточно много, чтобы никого нельзя было узнать.
            Не указывайте в свободных ответах то, что может вас выдать.</div>
          </div>
        </div>`;
    }
    return `
      <div class="alert">
        ${ICONS.user}
        <div>
          <strong>Вы отвечаете как @${escHtml(survey.username)}.</strong>
          <div class="small">Этот опрос не анонимный: HR увидит ваши ответы вместе с именем пользователя.</div>
        </div>
      </div>`;
  }

  function closedMessage(survey) {
    const text = survey.completed
      ? 'Вы уже прошли этот опрос. Спасибо!'
      : `Опрос ${survey.status === 'closed' ? 'завершён' : 'пока недоступен'}.`;
    return `<div class="card"><div class="empty">${text}<br><br><a class="btn btn-secondary" href="/">К моим опросам</a></div></div>`;
  }

  async function load() {
    let survey;
    try {
      survey = await getJson(`/api/v1/surveys/${surveyId}/`);
    } catch (error) {
      $page.html(`<div class="card"><div class="empty">${escHtml(error.message)}<br><br><a class="btn btn-secondary" href="/">К моим опросам</a></div></div>`);
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

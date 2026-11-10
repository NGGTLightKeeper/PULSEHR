// Copyright NGGT.LightKeeper. All Rights Reserved.

import { getJson, postJson } from '../api.js';
import { confirmDialog, escHtml, formatDate, percent, setBusy, toastError } from '../common.js';
import { barsHtml, enpsClass, enpsSplitHtml, histogramHtml } from '../charts.js';

// Badge colors of the survey statuses.
const STATUS_BADGES = { draft: '', scheduled: 'badge-info', active: 'badge-accent', closed: 'badge-success' };

// Survey results.
// Participation, eNPS, channels, departments and the results of every question.
$(function initResultsPage() {
  const surveyId = $('#resultsPage').data('survey-id');
  const $results = $('#results');

  function kpi(label, value, note) {
    return `
      <section class="card kpi">
        <span class="kpi-label">${label}</span>
        <span class="kpi-value">${value}</span>
        <span class="kpi-note">${note}</span>
      </section>`;
  }

  function formatScore(score) {
    if (score === null || score === undefined) {
      return '—';
    }
    return score > 0 ? `+${score}` : String(score);
  }

  function headerHtml(data) {
    const survey = data.survey;
    const mode = survey.mode === 'anonymous'
      ? `<span class="badge badge-success">Анонимный · порог ${data.min_group_size}</span>`
      : '<span class="badge badge-info">Идентифицированный</span>';
    const dates = [
      survey.published_at ? `опубликован ${formatDate(survey.published_at)}` : '',
      survey.ends_at ? `до ${formatDate(survey.ends_at)}` : '',
      survey.closed_at ? `завершён ${formatDate(survey.closed_at)}` : ''
    ].filter(Boolean).join(' · ');
    return `<span class="badge ${STATUS_BADGES[survey.status]}">${escHtml(survey.status_label)}</span>${mode}<span class="muted small">${dates}</span>`;
  }

  function kpisHtml(data) {
    const participation = data.participation;
    const push = data.push_response;
    return `
      <div class="grid grid-4">
        ${kpi('Приглашено', participation.invited, `открыли: ${participation.opened}`)}
        ${kpi('Прошли', participation.completed, `отклик ${percent(participation.rate)}`)}
        ${kpi('eNPS', data.enps ? formatScore(data.enps.score) : '—', data.enps ? `${data.enps.total} оценок` : 'нет вопроса eNPS или ответов')}
        ${kpi('Ответ ≤ 24 ч после push', percent(push.rate), `${push.responded} из ${push.notified} получивших push · цель ≥ 50%`)}
      </div>`;
  }

  function channelsHtml(channels) {
    return `
      <section class="card card-flush">
        <div class="card-head" style="padding:16px 20px 0"><h3>Каналы уведомлений</h3></div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Канал</th><th class="num">Отправлено</th><th class="num">Открыли</th><th class="num">Прошли опрос</th></tr></thead>
            <tbody>${channels.map(function channelRow(item) {
              return `<tr><td>${escHtml(item.label)}</td><td class="num">${item.sent}</td><td class="num">${item.clicked}</td><td class="num">${item.completed}</td></tr>`;
            }).join('')}</tbody>
          </table>
        </div>
      </section>`;
  }

  function departmentsHtml(rows, hasEnps) {
    if (!rows.length) {
      return '';
    }
    return `
      <section class="card card-flush">
        <div class="card-head" style="padding:16px 20px 0"><h3>Подразделения</h3></div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Подразделение</th><th class="num">Приглашено</th><th class="num">Прошли</th><th class="num">Отклик</th>${hasEnps ? '<th class="num">eNPS</th>' : ''}</tr></thead>
            <tbody>${rows.map(function departmentRow(row) {
              let enps = '';
              if (hasEnps) {
                enps = row.hidden
                  ? '<td class="num"><span class="badge" title="Слишком мало ответов для анонимности">скрыто</span></td>'
                  : `<td class="num ${enpsClass(row.enps && row.enps.score)}"><strong>${formatScore(row.enps && row.enps.score)}</strong></td>`;
              }
              return `<tr><td>${escHtml(row.name)}</td><td class="num">${row.invited}</td><td class="num">${row.completed}</td><td class="num">${percent(row.rate)}</td>${enps}</tr>`;
            }).join('')}</tbody>
          </table>
        </div>
      </section>`;
  }

  function questionHtml(question) {
    let body = '';
    if (question.options) {
      body = barsHtml(question.options.map((option) => ({ label: option.text, count: option.count, percent: option.percent })));
    } else if (question.distribution) {
      const average = question.average === null ? '—' : String(question.average).replace('.', ',');
      const labels = question.min_label || question.max_label
        ? `<div class="scale-labels"><span>${escHtml(question.min_label)}</span><span>${escHtml(question.max_label)}</span></div>`
        : '';
      const enps = question.enps
        ? `<div style="margin-top:14px"><div class="row" style="margin-bottom:8px"><strong>eNPS: <span class="${enpsClass(question.enps.score)}">${formatScore(question.enps.score)}</span></strong></div>${enpsSplitHtml(question.enps)}</div>`
        : '';
      body = `<div class="muted small">Среднее: <strong>${average}</strong></div>${histogramHtml(question.distribution, question.kind === 'enps')}${labels}${enps}`;
    } else {
      body = question.texts.length
        ? `<div class="text-answers">${question.texts.map((text) => `<div class="text-answer">${escHtml(text)}</div>`).join('')}</div>`
        : '<div class="empty">Свободных ответов нет.</div>';
    }
    return `
      <section class="card">
        <div class="card-head">
          <h3>${question.number}. ${escHtml(question.text)}</h3>
          <span class="badge">${question.answered} отв.</span>
        </div>
        ${body}
      </section>`;
  }

  function render(data) {
    $('#surveyTitle').text(data.survey.title);
    $('#surveyMeta').html(headerHtml(data));
    $('#closeBtn').toggleClass('hidden', !['active', 'scheduled'].includes(data.survey.status));
    document.title = `${data.survey.title} · PULSEHR`;

    const hidden = data.hidden
      ? `<div class="alert alert-warning"><div><strong>Ответы скрыты для анонимности.</strong>
          <div class="small muted">Сейчас ответов: ${data.responses}. Итоги появятся, когда их будет не меньше ${data.min_group_size}.</div></div></div>`
      : '';
    const enpsBlock = data.enps
      ? `<section class="card"><div class="card-head"><h3>eNPS: <span class="${enpsClass(data.enps.score)}">${formatScore(data.enps.score)}</span></h3></div>${enpsSplitHtml(data.enps)}</section>`
      : '';

    $results.html(`
      ${hidden}
      ${kpisHtml(data)}
      ${enpsBlock}
      <div class="grid grid-2">
        ${channelsHtml(data.channels)}
        ${departmentsHtml(data.departments, data.questions.some((question) => question.kind === 'enps') || Boolean(data.enps))}
      </div>
      ${data.questions.map(questionHtml).join('')}`);
  }

  async function load() {
    try {
      render(await getJson(`/api/v1/hr/surveys/${surveyId}/analytics/`));
    } catch (error) {
      $results.html(`<div class="card empty">${escHtml(error.message)}</div>`);
    }
  }

  $('#csvLink').attr('href', `/api/v1/hr/surveys/${surveyId}/export/?type=csv`);
  $('#xlsxLink').attr('href', `/api/v1/hr/surveys/${surveyId}/export/?type=xlsx`);
  $('#settingsLink').attr('href', `/hr/surveys/${surveyId}/edit/`);

  $('#refreshBtn').on('click', async function onRefresh() {
    setBusy($(this), true);
    await load();
    setBusy($(this), false);
  });

  $('#closeBtn').on('click', async function onClose() {
    const confirmed = await confirmDialog({
      title: 'Завершить опрос?',
      message: 'Сотрудники больше не смогут отвечать, неотправленные напоминания будут отменены.',
      confirmText: 'Завершить',
      danger: true
    });
    if (!confirmed) {
      return;
    }
    try {
      await postJson(`/api/v1/hr/surveys/${surveyId}/close/`);
      load();
    } catch (error) {
      toastError(error);
    }
  });

  load();
});

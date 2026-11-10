// Copyright NGGT.LightKeeper. All Rights Reserved.

import { deleteJson, getJson, postJson } from '../api.js';
import { confirmDialog, escHtml, formatDate, percent, setBusy, toast, toastError } from '../common.js';

// Badge colors of the survey statuses.
const STATUS_BADGES = {
  draft: '',
  scheduled: 'badge-info',
  active: 'badge-accent',
  closed: 'badge-success'
};

// HR survey list.
// Filter by status, create surveys, open, copy and delete them.
$(function initSurveysPage() {
  let surveys = [];
  let status = '';

  function surveyLink(survey) {
    return survey.status === 'draft' ? `/hr/surveys/${survey.id}/edit/` : `/hr/surveys/${survey.id}/`;
  }

  function surveyRow(survey) {
    const rate = survey.invited ? Math.round((survey.completed / survey.invited) * 1000) / 10 : null;
    const progress = survey.status === 'draft'
      ? '<span class="muted">—</span>'
      : `<div class="small">${survey.completed} / ${survey.invited} · ${percent(rate)}</div>
         <div class="progress" style="width:120px;margin-top:4px"><div class="progress-bar" style="width:${rate || 0}%"></div></div>`;
    const dates = survey.status === 'draft'
      ? `создан ${formatDate(survey.created_at)}`
      : `${formatDate(survey.published_at)}${survey.ends_at ? ` — ${formatDate(survey.ends_at)}` : ''}`;
    const remove = survey.status === 'draft'
      ? `<button type="button" class="btn btn-ghost btn-sm" data-delete="${survey.id}">Удалить</button>`
      : '';

    return `
      <tr>
        <td><a href="${surveyLink(survey)}"><strong>${escHtml(survey.title)}</strong></a>
            <div class="muted small">${escHtml(survey.mode_label)}</div></td>
        <td><span class="badge ${STATUS_BADGES[survey.status]}">${escHtml(survey.status_label)}</span></td>
        <td>${progress}</td>
        <td class="small muted nowrap">${dates}</td>
        <td class="nowrap">
          ${survey.status !== 'draft' ? `<a class="btn btn-ghost btn-sm" href="/hr/surveys/${survey.id}/">Результаты</a>` : ''}
          <a class="btn btn-ghost btn-sm" href="/hr/surveys/${survey.id}/edit/">${survey.status === 'draft' ? 'Изменить' : 'Настройки'}</a>
          <button type="button" class="btn btn-ghost btn-sm" data-copy="${survey.id}">Копия</button>
          ${remove}
        </td>
      </tr>`;
  }

  function render() {
    const items = surveys.filter(function byStatus(survey) {
      return !status || survey.status === status;
    });
    $('#surveysTable').html(items.length
      ? `<table class="table">
           <thead><tr><th>Опрос</th><th>Статус</th><th>Прошли</th><th>Даты</th><th></th></tr></thead>
           <tbody>${items.map(surveyRow).join('')}</tbody>
         </table>`
      : '<div class="empty">Опросов нет. Создайте новый или начните с шаблона eNPS.</div>');
  }

  async function load() {
    try {
      surveys = await getJson('/api/v1/hr/surveys/');
      render();
    } catch (error) {
      toastError(error);
    }
  }

  // Create a survey and open it in the builder.
  async function create($button, payload) {
    setBusy($button, true);
    try {
      const survey = await postJson('/api/v1/hr/surveys/', payload);
      window.location.href = `/hr/surveys/${survey.id}/edit/`;
    } catch (error) {
      setBusy($button, false);
      toastError(error);
    }
  }

  $('#createBtn').on('click', function onCreate() {
    create($(this), { title: 'Новый опрос' });
  });

  $('#templateBtn').on('click', function onTemplate() {
    create($(this), { template: 'enps' });
  });

  $('#statusTabs').on('click', '.tab', function onTab() {
    $('#statusTabs .tab').removeClass('active');
    $(this).addClass('active');
    status = String($(this).data('status') || '');
    render();
  });

  $('#surveysTable').on('click', '[data-copy]', async function onCopy() {
    try {
      const copy = await postJson(`/api/v1/hr/surveys/${$(this).data('copy')}/duplicate/`);
      window.location.href = `/hr/surveys/${copy.id}/edit/`;
    } catch (error) {
      toastError(error);
    }
  });

  $('#surveysTable').on('click', '[data-delete]', async function onDelete() {
    const id = $(this).data('delete');
    const confirmed = await confirmDialog({
      title: 'Удалить черновик?',
      message: 'Черновик и его вопросы будут удалены без возможности восстановления.',
      confirmText: 'Удалить',
      danger: true
    });
    if (!confirmed) {
      return;
    }
    try {
      await deleteJson(`/api/v1/hr/surveys/${id}/`);
      toast('Черновик удалён.');
      load();
    } catch (error) {
      toastError(error);
    }
  });

  load();
});

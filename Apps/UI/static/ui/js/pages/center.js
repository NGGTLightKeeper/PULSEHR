// Copyright NGGT.LightKeeper. All Rights Reserved.

import { getJson, postJson } from '../api.js';
import { ICONS, clearErrors, escHtml, formatDate, setBusy, showErrors, toast, toastError } from '../common.js';
import { enablePush, getPushState } from '../push.js';

// Employee center.
// Surveys to take, completed surveys and free-form feedback to HR.
$(function initCenterPage() {
  const STATUS_BADGES = { new: 'badge-info', in_progress: 'badge-warning', closed: 'badge-success' };

  function surveyCard(item) {
    const mode = item.mode === 'anonymous'
      ? '<span class="badge badge-success">Анонимный</span>'
      : '<span class="badge badge-info">С указанием имени</span>';
    const deadline = item.ends_at ? `<span class="muted small">до ${formatDate(item.ends_at)}</span>` : '';
    return `
      <article class="survey-card">
        <div class="row">${mode}${deadline}</div>
        <h3>${escHtml(item.title)}</h3>
        ${item.description ? `<p>${escHtml(item.description)}</p>` : ''}
        <a class="btn btn-primary" href="/surveys/${item.id}/">${item.opened_at ? 'Продолжить' : 'Пройти опрос'}</a>
      </article>`;
  }

  async function loadSurveys() {
    try {
      const data = await getJson('/api/v1/surveys/');
      $('#activeSurveys').removeClass('loading').html(data.active.length
        ? `<div class="survey-cards">${data.active.map(surveyCard).join('')}</div>`
        : '<div class="empty">Сейчас опросов нет. Мы сообщим, когда появится новый.</div>');

      $('#completedSurveys').removeClass('loading').html(data.completed.length
        ? `<ul class="done-list">${data.completed.map(function completedItem(item) {
          return `<li><span>${escHtml(item.title)}</span><span class="muted small">${formatDate(item.completed_at)}</span></li>`;
        }).join('')}</ul>`
        : '<div class="empty">Пока нет пройденных опросов.</div>');
    } catch (error) {
      toastError(error);
    }
  }

  async function loadFeedback() {
    try {
      const items = await getJson('/api/v1/feedback/');
      $('#myFeedback').removeClass('loading').html(items.length
        ? items.map(function feedbackItem(item) {
          const reply = item.reply ? `<div class="feedback-reply"><strong>Ответ HR:</strong> ${escHtml(item.reply)}</div>` : '';
          return `
            <div class="feedback-item">
              <div class="row">
                <span class="badge">${escHtml(item.category_label)}</span>
                <span class="badge ${STATUS_BADGES[item.status] || ''}">${escHtml(item.status_label)}</span>
                <span class="muted small">${formatDate(item.created_on)}</span>
              </div>
              <div class="feedback-text">${escHtml(item.text)}</div>
              ${reply}
            </div>`;
        }).join('')
        : '<div class="empty">Здесь появятся ваши обращения с подписью и ответы на них.</div>');
    } catch (error) {
      toastError(error);
    }
  }

  // Suggest the browser notifications until they are on here.
  async function showPushBanner() {
    const state = await getPushState();
    if (!state.supported || state.subscribed || state.permission === 'denied') {
      return;
    }
    $('#pushBanner').html(`
      <div class="alert alert-accent">
        ${ICONS.bell}
        <div style="flex:1">
          <strong>Не пропускайте опросы.</strong>
          <div class="muted small">Включите уведомления в браузере — новый опрос придёт сразу.</div>
        </div>
        <button type="button" class="btn btn-primary btn-sm" id="enablePushBtn">Включить</button>
      </div>`);
  }

  $('#pushBanner').on('click', '#enablePushBtn', async function onEnablePush() {
    setBusy($(this), true);
    try {
      await enablePush();
      toast('Уведомления включены.', 'success');
      $('#pushBanner').empty();
    } catch (error) {
      setBusy($(this), false);
      toastError(error);
    }
  });

  $('#feedbackForm').on('submit', async function onFeedback(event) {
    event.preventDefault();
    const $form = $(this);
    const $button = $form.find('button[type=submit]');
    const anonymous = $('#anonymous').prop('checked');
    clearErrors($form);
    setBusy($button, true);
    try {
      await postJson('/api/v1/feedback/', {
        category: $('#category').val(),
        text: String($('#feedbackText').val() || '').trim(),
        is_anonymous: anonymous
      });
      $form[0].reset();
      toast(anonymous ? 'Анонимное сообщение отправлено.' : 'Сообщение отправлено. Ответ появится здесь.', 'success');
      loadFeedback();
    } catch (error) {
      showErrors($form, error);
    } finally {
      setBusy($button, false);
    }
  });

  loadSurveys();
  loadFeedback();
  showPushBanner();
});

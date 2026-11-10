// Copyright NGGT.LightKeeper. All Rights Reserved.

import { getJson, patchJson } from '../api.js';
import { clearErrors, escHtml, formatDate, setBusy, showErrors, toast, toastError } from '../common.js';

// Feedback statuses in the order of processing.
const STATUSES = { new: 'Новое', in_progress: 'В работе', closed: 'Закрыто' };

// HR feedback inbox.
// Filter by status, move feedback through the statuses and answer signed feedback.
$(function initFeedbackPage() {
  let status = '';

  function itemHtml(item) {
    const statuses = Object.keys(STATUSES).map(function statusOption(value) {
      return `<option value="${value}" ${item.status === value ? 'selected' : ''}>${STATUSES[value]}</option>`;
    }).join('');
    const author = item.author
      ? `<span class="badge badge-info">@${escHtml(item.author)}</span>`
      : '<span class="badge">Анонимно</span>';
    const reply = item.is_anonymous
      ? ''
      : `<form class="form" data-reply="${item.id}" novalidate>
           <div class="field">
             <textarea class="textarea" name="reply" rows="2" maxlength="4000" placeholder="Ответ сотруднику — он увидит его в своём центре">${escHtml(item.reply)}</textarea>
           </div>
           <div class="form-actions"><button class="btn btn-sm" type="submit">Сохранить ответ</button></div>
         </form>`;

    return `
      <section class="card inbox-item">
        <div class="row-between">
          <div class="row">${author}<span class="badge">${escHtml(item.category_label)}</span><span class="muted small">${formatDate(item.created_on)}</span></div>
          <select class="select input-sm" data-status-select="${item.id}" style="width:auto">${statuses}</select>
        </div>
        <div class="feedback-text">${escHtml(item.text)}</div>
        ${reply}
      </section>`;
  }

  async function load() {
    try {
      const items = await getJson(`/api/v1/hr/feedback/${status ? `?status=${status}` : ''}`);
      $('#feedbackList').html(items.length ? items.map(itemHtml).join('') : '<div class="card empty">Обращений нет.</div>');
    } catch (error) {
      toastError(error);
    }
  }

  $('#statusTabs').on('click', '.tab', function onTab() {
    $('#statusTabs .tab').removeClass('active');
    $(this).addClass('active');
    status = String($(this).data('status') || '');
    load();
  });

  $('#feedbackList').on('change', '[data-status-select]', async function onStatus() {
    try {
      await patchJson(`/api/v1/hr/feedback/${$(this).data('status-select')}/`, { status: $(this).val() });
      toast('Статус изменён.', 'success');
    } catch (error) {
      toastError(error);
    }
  });

  $('#feedbackList').on('submit', '[data-reply]', async function onReply(event) {
    event.preventDefault();
    const $form = $(this);
    const $button = $form.find('button[type=submit]');
    clearErrors($form);
    setBusy($button, true);
    try {
      await patchJson(`/api/v1/hr/feedback/${$form.data('reply')}/`, { reply: $form.find('[name=reply]').val() });
      toast('Ответ сохранён.', 'success');
    } catch (error) {
      showErrors($form, error);
    } finally {
      setBusy($button, false);
    }
  });

  load();
});

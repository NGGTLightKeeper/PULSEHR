// Copyright NGGT.LightKeeper. All Rights Reserved.

import { getJson, patchJson } from '../api.js';
import { clearErrors, escHtml, setBusy, showErrors, toast, toastError } from '../common.js';
import { mountPushBlock } from '../push.js';
import { mountTelegramBlock } from '../telegram.js';

// Profile page.
// Edit the username, the phone and the department; connect Telegram and Web Push.
$(function initProfilePage() {
  const $form = $('#profileForm');

  function phoneBadge(me) {
    if (!me.phone) {
      return '';
    }
    return me.phone_verified
      ? '<span class="badge badge-success">подтверждён</span>'
      : '<span class="badge">не подтверждён</span>';
  }

  function fill(me, departments) {
    $('#email').val(me.email);
    $('#role').val(me.role_label);
    $('#username').val(me.username);
    $('#phone').val(me.phone);
    $('#phoneBadge').html(phoneBadge(me));

    const options = departments.map(function departmentOption(department) {
      const indent = '  '.repeat(department.depth);
      return `<option value="${department.id}">${indent}${escHtml(department.name)}</option>`;
    });
    $('#department').html(`<option value="">Не указано</option>${options.join('')}`);
    $('#department').val(me.department ? String(me.department.id) : '');
  }

  async function load() {
    try {
      const [me, departments] = await Promise.all([getJson('/api/v1/me/'), getJson('/api/v1/departments/')]);
      fill(me, departments);
    } catch (error) {
      toastError(error);
    }
  }

  $form.on('submit', async function onSave(event) {
    event.preventDefault();
    const $button = $form.find('button[type=submit]');
    const departmentId = $('#department').val();
    clearErrors($form);
    setBusy($button, true);
    try {
      const me = await patchJson('/api/v1/me/', {
        username: String($('#username').val() || '').trim(),
        phone: String($('#phone').val() || '').trim(),
        department_id: departmentId ? Number(departmentId) : null
      });
      $('#phoneBadge').html(phoneBadge(me));
      $('.user-link').text(`@${me.username}`);
      toast('Профиль сохранён.', 'success');
    } catch (error) {
      showErrors($form, error);
    } finally {
      setBusy($button, false);
    }
  });

  load();
  mountTelegramBlock($('#telegramBlock'));
  mountPushBlock($('#pushBlock'));
});

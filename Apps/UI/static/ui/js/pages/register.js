// Copyright NGGT.LightKeeper. All Rights Reserved.

import { getJson, postJson } from '../api.js';
import { clearErrors, escHtml, setBusy, showErrors, startCountdown, toastError } from '../common.js';

const RESEND_LABEL = 'Отправить код ещё раз';

// Registration page.
// Step 1 checks the form and sends the code to the e-mail, step 2 creates the account.
$(function initRegisterPage() {
  const $form = $('#registerForm');
  const $codeForm = $('#codeForm');
  const $resend = $('#resendBtn');
  let email = '';

  // Fill the department list; without departments the field is hidden.
  async function loadDepartments() {
    try {
      const departments = await getJson('/api/v1/departments/');
      if (!departments.length) {
        $('#departmentField').addClass('hidden');
        return;
      }
      const options = departments.map(function departmentOption(department) {
        const indent = '  '.repeat(department.depth);
        return `<option value="${department.id}">${indent}${escHtml(department.name)}</option>`;
      });
      $('#department').html(`<option value="">Выберите подразделение</option>${options.join('')}`);
    } catch (error) {
      toastError(error);
    }
  }

  function formData() {
    const departmentId = $('#department').val();
    return {
      email: String($('#email').val() || '').trim(),
      username: String($('#username').val() || '').trim(),
      phone: String($('#phone').val() || '').trim(),
      department_id: departmentId ? Number(departmentId) : null,
      telegram_username: String($('#telegram').val() || '').trim()
    };
  }

  async function requestCode($errorForm, $button) {
    clearErrors($errorForm);
    setBusy($button, true);
    try {
      const data = formData();
      const delivery = await postJson('/api/v1/auth/register/', data);
      setBusy($button, false);
      email = data.email;
      $('#codeEmail').text(email);
      $form.addClass('hidden');
      $codeForm.removeClass('hidden');
      startCountdown($resend, delivery.resend_in, RESEND_LABEL);
      $('#code').val('').trigger('focus');
    } catch (error) {
      setBusy($button, false);
      if (error.data && error.data.retry_after) {
        startCountdown($resend, error.data.retry_after, RESEND_LABEL);
      }
      showErrors($errorForm, error);
    }
  }

  $form.on('submit', function onRegister(event) {
    event.preventDefault();
    requestCode($form, $form.find('button[type=submit]'));
  });

  $codeForm.on('submit', async function onCode(event) {
    event.preventDefault();
    const $button = $codeForm.find('button[type=submit]');
    clearErrors($codeForm);
    setBusy($button, true);
    try {
      await postJson('/api/v1/auth/register/confirm/', { email, code: $('#code').val() });
      window.location.href = '/onboarding/';
    } catch (error) {
      setBusy($button, false);
      showErrors($codeForm, error);
    }
  });

  $resend.on('click', function onResend() {
    requestCode($codeForm, $resend);
  });

  $('#backBtn').on('click', function onBack() {
    clearErrors($codeForm);
    $codeForm.addClass('hidden');
    $form.removeClass('hidden');
  });

  loadDepartments();
});

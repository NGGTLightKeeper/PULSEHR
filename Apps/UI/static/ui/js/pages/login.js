// Copyright NGGT.LightKeeper. All Rights Reserved.

import { postJson } from '../api.js';
import { clearErrors, escHtml, getNextUrl, setBusy, showErrors, startCountdown } from '../common.js';

const RESEND_LABEL = 'Отправить код ещё раз';

// Sign-in page.
// Step 1 sends the code to every channel of the account, step 2 checks it and opens the site.
$(function initLoginPage() {
  const $loginForm = $('#loginForm');
  const $codeForm = $('#codeForm');
  const $resend = $('#resendBtn');
  let login = '';

  function showCodeStep(delivery) {
    $('#codeChannels').html(delivery.channels.map(function channelItem(channel) {
      return `<li>${escHtml(channel)}</li>`;
    }).join(''));
    $loginForm.addClass('hidden');
    $codeForm.removeClass('hidden');
    startCountdown($resend, delivery.resend_in, RESEND_LABEL);
    $('#code').val('').trigger('focus');
  }

  // Request a code; a resend too early shows the remaining time on the button.
  async function requestCode($form, $button) {
    clearErrors($form);
    setBusy($button, true);
    try {
      const delivery = await postJson('/api/v1/auth/login/', { login });
      setBusy($button, false);
      showCodeStep(delivery);
    } catch (error) {
      setBusy($button, false);
      if (error.data && error.data.retry_after) {
        startCountdown($resend, error.data.retry_after, RESEND_LABEL);
      }
      showErrors($form, error);
    }
  }

  $loginForm.on('submit', function onLogin(event) {
    event.preventDefault();
    login = String($('#login').val() || '').trim();
    if (login) {
      requestCode($loginForm, $loginForm.find('button[type=submit]'));
    }
  });

  $codeForm.on('submit', async function onCode(event) {
    event.preventDefault();
    const $button = $codeForm.find('button[type=submit]');
    clearErrors($codeForm);
    setBusy($button, true);
    try {
      await postJson('/api/v1/auth/login/confirm/', { login, code: $('#code').val() });
      window.location.href = getNextUrl('/');
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
    $loginForm.removeClass('hidden');
    $('#login').trigger('focus');
  });
});

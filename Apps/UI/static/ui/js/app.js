// Copyright NGGT.LightKeeper. All Rights Reserved.

import { postJson } from './api.js';
import { toastError } from './common.js';
import { syncPushSubscription } from './push.js';

// Site header.
// Bind the menu toggle of small screens and the sign-out button.
$(function initHeader() {
  const $nav = $('#siteNav');
  $('#navToggle').on('click', function onToggle() {
    const open = !$nav.hasClass('open');
    $nav.toggleClass('open', open);
    $(this).attr('aria-expanded', String(open));
  });

  $('#logoutBtn').on('click', async function onLogout() {
    try {
      await postJson('/api/v1/auth/logout/');
      window.location.href = '/login/';
    } catch (error) {
      toastError(error);
    }
  });

  // Keep the server copy of this browser's push subscription fresh after sign-in.
  if (document.body.dataset.authenticated === 'true') {
    syncPushSubscription();
  }
});

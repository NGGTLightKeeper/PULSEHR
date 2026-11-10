// Copyright NGGT.LightKeeper. All Rights Reserved.

import { deleteJson, getJson, postJson } from './api.js';
import { setBusy, toast, toastError } from './common.js';

// Browser support.
// Return whether this browser can get Web Push on this address: it needs a secure context
// (HTTPS or localhost), a service worker and the Push API.
export function pushSupported() {
  return window.isSecureContext && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
}

// Turn a base64url VAPID key into the bytes the Push API expects.
function keyToBytes(base64url) {
  const padded = base64url.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (base64url.length % 4)) % 4);
  return Uint8Array.from(atob(padded), function toByte(char) {
    return char.charCodeAt(0);
  });
}

// Return whether a subscription was made with the given server key.
function sameKey(subscription, keyBytes) {
  const current = subscription.options && subscription.options.applicationServerKey;
  if (!current) {
    return false;
  }
  const bytes = new Uint8Array(current);
  return bytes.length === keyBytes.length && bytes.every(function equal(value, index) {
    return value === keyBytes[index];
  });
}

async function currentSubscription() {
  const registration = await navigator.serviceWorker.getRegistration('/');
  return registration ? registration.pushManager.getSubscription() : null;
}


// Subscription.
// Return the push state of this browser.
export async function getPushState() {
  if (!pushSupported()) {
    return { supported: false, permission: 'unsupported', subscribed: false };
  }
  const subscription = await currentSubscription();
  return { supported: true, permission: Notification.permission, subscribed: Boolean(subscription) };
}

// Ask for the permission, subscribe this browser and send the subscription to the server. A
// subscription made with an old server key is replaced.
export async function enablePush() {
  if (!pushSupported()) {
    throw new Error('Этот браузер не поддерживает push-уведомления на этом адресе: нужен HTTPS или localhost.');
  }
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') {
    throw new Error('Уведомления запрещены в браузере. Разрешите их в настройках сайта и попробуйте снова.');
  }

  const key = await getJson('/api/v1/push/key/');
  if (!key.enabled) {
    throw new Error('Push-уведомления не настроены на сервере.');
  }
  const keyBytes = keyToBytes(key.public_key);
  const registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
  await navigator.serviceWorker.ready;

  let subscription = await registration.pushManager.getSubscription();
  if (subscription && !sameKey(subscription, keyBytes)) {
    await subscription.unsubscribe();
    subscription = null;
  }
  if (!subscription) {
    subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes });
  }
  await postJson('/api/v1/push/subscriptions/', subscription.toJSON());
}

export async function disablePush() {
  const subscription = await currentSubscription();
  if (!subscription) {
    return;
  }
  await deleteJson('/api/v1/push/subscriptions/', { endpoint: subscription.endpoint });
  await subscription.unsubscribe();
}

// Send the existing subscription of this browser to the server again; problems are ignored.
export async function syncPushSubscription() {
  try {
    if (!pushSupported() || Notification.permission !== 'granted') {
      return;
    }
    const subscription = await currentSubscription();
    if (subscription) {
      await postJson('/api/v1/push/subscriptions/', subscription.toJSON());
    }
  } catch (_error) {
    // The next page load tries again.
  }
}


// Push block.
// Show the push state of this browser with the button that turns it on or off.
export function mountPushBlock($container, options) {
  const settings = options || {};

  async function render() {
    const state = await getPushState();
    let html;
    if (!state.supported) {
      html = '<p class="muted">Этот браузер не может получать push-уведомления на этом адресе. '
        + 'Нужен HTTPS или localhost. Приглашения придут в Telegram или на почту.</p>';
    } else if (state.subscribed) {
      html = '<div class="row"><span class="badge badge-success">Включены в этом браузере</span></div>'
        + '<p class="muted small">Новые опросы будут приходить уведомлением, даже когда сайт закрыт.</p>'
        + '<button type="button" class="btn btn-sm" data-push-disable>Отключить</button>';
    } else if (state.permission === 'denied') {
      html = '<p><span class="badge badge-warning">Запрещены в браузере</span></p>'
        + '<p class="muted small">Разрешите уведомления для этого сайта в настройках браузера (значок замка в адресной строке) и обновите страницу.</p>';
    } else {
      html = '<p class="muted">Включите уведомления, чтобы сразу узнавать о новых опросах.</p>'
        + '<button type="button" class="btn btn-primary" data-push-enable>Включить уведомления</button>';
    }
    $container.html(html);
    if (settings.onChange) {
      settings.onChange(state);
    }
  }

  $container.on('click', '[data-push-enable]', async function onEnable() {
    const $button = $(this);
    setBusy($button, true);
    try {
      await enablePush();
      toast('Уведомления включены.', 'success');
    } catch (error) {
      toastError(error);
    }
    await render();
  });

  $container.on('click', '[data-push-disable]', async function onDisable() {
    const $button = $(this);
    setBusy($button, true);
    try {
      await disablePush();
      toast('Уведомления в этом браузере отключены.');
    } catch (error) {
      toastError(error);
    }
    await render();
  });

  return render();
}

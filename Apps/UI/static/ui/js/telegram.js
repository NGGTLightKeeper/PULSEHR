// Copyright NGGT.LightKeeper. All Rights Reserved.

import { deleteJson, getJson, postJson, putJson } from './api.js';
import { clearErrors, escHtml, setBusy, showErrors, toast, toastError } from './common.js';

// Telegram block.
// Show the Telegram state of the account: claim a username, confirm it with the code from the bot,
// or disconnect it. Used by the onboarding and the profile pages.
export function mountTelegramBlock($container, options) {
  const settings = options || {};
  let status = null;

  function usernameForm(value) {
    return `
      <form class="form" data-tg-username>
        <div class="field">
          <label for="tgUsername">Имя пользователя в Telegram</label>
          <input class="input" id="tgUsername" name="telegram_username" placeholder="@username" value="${escHtml(value || '')}" maxlength="33" autocomplete="off">
          <span class="field-hint">Его можно посмотреть в настройках Telegram.</span>
        </div>
        <div class="form-actions"><button type="submit" class="btn btn-primary">Сохранить</button></div>
      </form>`;
  }

  function pendingBlock() {
    const name = escHtml(status.telegram_username);
    const steps = status.bot_available
      ? `<ol class="small">
           <li>Откройте бота <a href="${escHtml(status.bot_link)}" target="_blank" rel="noopener">@${escHtml(status.bot_username)}</a> из аккаунта @${name}.</li>
           <li>Нажмите «Start» или напишите любое сообщение — бот пришлёт код.</li>
           <li>Введите код ниже. Он действует 10 минут.</li>
         </ol>`
      : '<p class="muted small">Бот пока не подключён администратором. Подтвердить Telegram можно будет позже.</p>';

    return `
      <div class="row">
        <strong>@${name}</strong>
        <span class="badge badge-warning">Не подтверждён</span>
        <button type="button" class="btn btn-ghost btn-sm" data-tg-change>Изменить</button>
      </div>
      ${steps}
      <form class="form" data-tg-confirm>
        <div class="field">
          <label for="tgCode">Код из сообщения бота</label>
          <input class="input code-input" id="tgCode" name="code" inputmode="numeric" maxlength="6" placeholder="000000" autocomplete="one-time-code">
        </div>
        <div class="form-actions"><button type="submit" class="btn btn-primary">Подтвердить</button></div>
      </form>`;
  }

  function verifiedBlock() {
    return `
      <div class="row">
        <span class="badge badge-success">Подтверждён</span>
        <strong>@${escHtml(status.telegram_username)}</strong>
      </div>
      <p class="muted small">Сюда приходят коды входа и приглашения в опросы.</p>
      <button type="button" class="btn btn-sm" data-tg-disconnect>Отключить</button>`;
  }

  function render(editing) {
    if (editing || !status.telegram_username) {
      $container.html(usernameForm(status.telegram_username));
    } else {
      $container.html(status.verified ? verifiedBlock() : pendingBlock());
    }
    if (settings.onChange) {
      settings.onChange(status);
    }
  }

  async function load() {
    try {
      status = await getJson('/api/v1/me/telegram/');
      render(false);
    } catch (error) {
      $container.html(`<p class="field-error">${escHtml(error.message)}</p>`);
    }
  }

  $container.on('submit', '[data-tg-username]', async function onSaveUsername(event) {
    event.preventDefault();
    const $form = $(this);
    const $button = $form.find('button[type=submit]');
    clearErrors($form);
    setBusy($button, true);
    try {
      status = await putJson('/api/v1/me/telegram/', { telegram_username: $form.find('[name=telegram_username]').val() });
      render(false);
    } catch (error) {
      setBusy($button, false);
      showErrors($form, error);
    }
  });

  $container.on('submit', '[data-tg-confirm]', async function onConfirm(event) {
    event.preventDefault();
    const $form = $(this);
    const $button = $form.find('button[type=submit]');
    clearErrors($form);
    setBusy($button, true);
    try {
      status = await postJson('/api/v1/me/telegram/confirm/', { code: $form.find('[name=code]').val() });
      toast('Telegram подтверждён.', 'success');
      render(false);
    } catch (error) {
      setBusy($button, false);
      showErrors($form, error);
    }
  });

  $container.on('click', '[data-tg-change]', function onChange() {
    render(true);
  });

  $container.on('click', '[data-tg-disconnect]', async function onDisconnect() {
    try {
      status = await deleteJson('/api/v1/me/telegram/');
      toast('Telegram отключён.');
      render(false);
    } catch (error) {
      toastError(error);
    }
  });

  return load();
}

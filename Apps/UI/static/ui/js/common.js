// Copyright NGGT.LightKeeper. All Rights Reserved.

// Text.
// Escape text for HTML.
export function escHtml(value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function formatDate(value) {
  if (!value) {
    return '—';
  }
  return new Date(value).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
}

export function formatDateTime(value) {
  if (!value) {
    return '—';
  }
  return new Date(value).toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
}

// Pick the Russian word form for a count: plural(5, 'ответ', 'ответа', 'ответов').
export function plural(count, one, few, many) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) {
    return one;
  }
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return few;
  }
  return many;
}

export function percent(value) {
  return value === null || value === undefined ? '—' : `${String(value).replace('.', ',')}%`;
}

// Return the "next" page from the address when it is a path of this site.
export function getNextUrl(fallback) {
  const next = new URLSearchParams(window.location.search).get('next');
  return next && next.startsWith('/') && !next.startsWith('//') ? next : fallback;
}


// Buttons and forms.
// Show or clear the busy state of a button.
export function setBusy($button, busy) {
  $button.prop('disabled', busy).toggleClass('is-busy', busy);
}

// Keep a resend button disabled for the given seconds, showing the time left on it.
export function startCountdown($button, seconds, label) {
  clearInterval($button.data('countdown'));
  let left = Math.max(0, Math.round(seconds));

  function tick() {
    if (left <= 0) {
      clearInterval($button.data('countdown'));
      $button.prop('disabled', false).text(label);
      return;
    }
    $button.prop('disabled', true).text(`${label} (${left} с)`);
    left -= 1;
  }

  tick();
  $button.data('countdown', setInterval(tick, 1000));
}

export function clearErrors($form) {
  $form.find('.is-invalid').removeClass('is-invalid');
  $form.find('.field-error, .form-error').remove();
}

// Show the API errors on the form: field errors next to their fields, the rest above the buttons.
export function showErrors($form, error) {
  clearErrors($form);
  const errors = (error && error.data && error.data.errors) || {};
  let shownOnField = false;

  Object.keys(errors).forEach(function showFieldError(name) {
    const $input = $form.find(`[name="${name}"]`).first();
    if (!$input.length) {
      return;
    }
    const messages = errors[name];
    const text = Array.isArray(messages) ? messages[0] : String(messages);
    $input.addClass('is-invalid');
    $('<div class="field-error">').text(text).insertAfter($input.closest('.field').children().last());
    shownOnField = true;
  });

  if (!shownOnField) {
    const $target = $form.find('.form-actions').first();
    const $error = $('<div class="form-error" role="alert">').text(error.message || 'Что-то пошло не так.');
    if ($target.length) {
      $error.insertBefore($target);
    } else {
      $form.append($error);
    }
  }
}


// Toasts.
// Show a short message in the corner of the page.
export function toast(message, type) {
  let $box = $('.toasts');
  if (!$box.length) {
    $box = $('<div class="toasts" aria-live="polite">').appendTo('body');
  }
  const $toast = $(`<div class="toast toast-${type || 'info'}">`).text(message).appendTo($box);
  setTimeout(function removeToast() {
    $toast.fadeOut(200, function onFaded() {
      $toast.remove();
    });
  }, 3500);
}

// Show the error message of a failed request.
export function toastError(error) {
  toast((error && error.message) || 'Что-то пошло не так.', 'error');
}


// Dialogs.
// Open a modal dialog with the given body; Escape and a click outside close it.
export function openDialog(options) {
  const $backdrop = $('<div class="dialog-backdrop" role="dialog" aria-modal="true">');
  const $dialog = $('<div class="dialog">').toggleClass('dialog-wide', Boolean(options.wide)).appendTo($backdrop);
  if (options.title) {
    $('<div class="dialog-title">').text(options.title).appendTo($dialog);
  }
  $dialog.append(options.$body);

  let closed = false;
  function close() {
    if (closed) {
      return;
    }
    closed = true;
    $(document).off('keydown', onKeyDown);
    $backdrop.remove();
    if (options.onClose) {
      options.onClose();
    }
  }

  function onKeyDown(event) {
    if (event.key === 'Escape') {
      close();
    }
  }

  $backdrop.on('mousedown', function onBackdrop(event) {
    if (event.target === $backdrop[0]) {
      close();
    }
  });
  $(document).on('keydown', onKeyDown);
  $backdrop.appendTo('body');
  return { $dialog, close };
}

// Ask for a confirmation; resolves true when confirmed.
export function confirmDialog(options) {
  return new Promise(function confirmPromise(resolve) {
    let result = false;
    const $body = $('<div>');
    $('<div class="dialog-message">').text(options.message || '').appendTo($body);
    const $actions = $('<div class="dialog-actions">').appendTo($body);
    const $cancel = $('<button type="button" class="btn">').text(options.cancelText || 'Отмена').appendTo($actions);
    const $confirm = $('<button type="button" class="btn">')
      .addClass(options.danger ? 'btn-danger' : 'btn-primary')
      .text(options.confirmText || 'Подтвердить')
      .appendTo($actions);

    const dialog = openDialog({
      title: options.title || 'Подтверждение',
      $body,
      onClose: function onClose() {
        resolve(result);
      }
    });
    $cancel.on('click', dialog.close);
    $confirm.on('click', function onConfirm() {
      result = true;
      dialog.close();
    });
    $confirm.trigger('focus');
  });
}

// Ask for a text value; resolves the trimmed text, or null when cancelled.
export function promptDialog(options) {
  return new Promise(function promptPromise(resolve) {
    let result = null;
    const $body = $('<form class="form">');
    if (options.message) {
      $('<div class="dialog-message">').text(options.message).appendTo($body);
    }
    const $input = $('<input class="input" type="text" maxlength="200" required>').val(options.value || '').appendTo($body);
    const $actions = $('<div class="dialog-actions">').appendTo($body);
    const $cancel = $('<button type="button" class="btn">').text('Отмена').appendTo($actions);
    $('<button type="submit" class="btn btn-primary">').text(options.confirmText || 'Сохранить').appendTo($actions);

    const dialog = openDialog({
      title: options.title,
      $body,
      onClose: function onClose() {
        resolve(result);
      }
    });
    $cancel.on('click', dialog.close);
    $body.on('submit', function onSubmit(event) {
      event.preventDefault();
      const value = String($input.val() || '').trim();
      if (value) {
        result = value;
        dialog.close();
      }
    });
    $input.trigger('focus').trigger('select');
  });
}

// Copyright NGGT.LightKeeper. All Rights Reserved.

// CSRF.
// Read one cookie value by name.
export function getCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

// Resolve the CSRF token from the page or the cookie.
export function getCsrfToken() {
  const input = document.querySelector('[name=csrfmiddlewaretoken]');
  return input ? input.value : getCookie('csrftoken');
}


// Requests.
// Send to the sign-in page and come back here afterwards.
function redirectToLogin() {
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  window.location.href = `/login/?next=${next}`;
}

// Send one JSON request. An error response throws an Error with the API message; error.data keeps
// the field errors and error.status the HTTP status. An expired session goes to the sign-in page.
export async function requestJson(url, options) {
  const requestOptions = options || {};
  const method = requestOptions.method || 'GET';
  const headers = { Accept: 'application/json', ...(requestOptions.headers || {}) };
  if (method !== 'GET' && method !== 'HEAD') {
    headers['X-CSRFToken'] = getCsrfToken();
  }

  let response;
  try {
    response = await fetch(url, { ...requestOptions, method, headers, credentials: 'same-origin' });
  } catch (_error) {
    throw Object.assign(new Error('Нет связи с сервером. Проверьте подключение.'), { status: 0, data: {} });
  }

  let data = null;
  if (response.status !== 204) {
    try {
      data = await response.json();
    } catch (_error) {
      data = null;
    }
  }

  if (!response.ok) {
    if (data && data.code === 'not_authenticated') {
      redirectToLogin();
    }
    const message = data && data.detail ? data.detail : `Ошибка запроса (${response.status}).`;
    throw Object.assign(new Error(message), { status: response.status, data: data || {} });
  }
  return data;
}

export function getJson(url) {
  return requestJson(url, { method: 'GET' });
}

// Send a JSON body with the given method.
function sendJson(method, url, payload) {
  return requestJson(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload === undefined ? {} : payload)
  });
}

export function postJson(url, payload) {
  return sendJson('POST', url, payload);
}

export function putJson(url, payload) {
  return sendJson('PUT', url, payload);
}

export function patchJson(url, payload) {
  return sendJson('PATCH', url, payload);
}

export function deleteJson(url, payload) {
  return sendJson('DELETE', url, payload);
}

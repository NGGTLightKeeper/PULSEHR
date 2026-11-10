// Copyright NGGT.LightKeeper. All Rights Reserved.

// Service worker of PULSEHR: shows survey invitations from Web Push and opens their links.

// Show a push message as a system notification.
self.addEventListener('push', function onPush(event) {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_error) {
    data = { body: event.data ? event.data.text() : '' };
  }

  event.waitUntil(self.registration.showNotification(data.title || 'PULSEHR', {
    body: data.body || '',
    tag: data.tag || 'pulsehr',
    icon: '/static/ui/img/icon-192.png',
    data: { url: data.url || '/' }
  }));
});

// Open the survey link of a clicked notification, reusing an open tab of the same page.
self.addEventListener('notificationclick', function onNotificationClick(event) {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';

  event.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function focusOrOpen(windows) {
    for (const client of windows) {
      if (client.url === url && 'focus' in client) {
        return client.focus();
      }
    }
    return clients.openWindow(url);
  }));
});

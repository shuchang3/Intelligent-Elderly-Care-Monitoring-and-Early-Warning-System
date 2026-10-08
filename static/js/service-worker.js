'use strict';
self.addEventListener('push',event=>{event.waitUntil(self.registration.showNotification('腰间北斗智能监护提醒',{body:'有新的监护事件，请登录平台查看详情。',tag:'eldercare-event'}));});
self.addEventListener('notificationclick',event=>{event.notification.close();event.waitUntil(clients.openWindow('/'));});
// Do not cache authenticated pages, camera frames, faces or snapshots.

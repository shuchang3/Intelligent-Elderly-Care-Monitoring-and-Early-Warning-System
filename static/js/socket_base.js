'use strict';
(() => {
  let socket,stopped=false,delay=1000,timer;
  const seen=new Map(),status=document.getElementById('connectionStatus'),box=document.getElementById('alertList');
  function renderItem(event,prepend=false){
    if(!box)return;
    if(!event?.id||seen.has(String(event.id)))return;
    seen.set(String(event.id),true);if(seen.size>200)seen.delete(seen.keys().next().value);
    if(!box.querySelector('.event'))box.replaceChildren();
    const item=ui.el('div',null,{class:'event '+event.eventLevel});
    if(event.imageUrl){const img=ui.el('img',null,{src:`/api/v1/events/${event.id}/snapshot`,alt:'告警截图',loading:'lazy'});img.onerror=()=>img.remove();item.append(img);}
    const content=ui.el('div');content.append(ui.el('strong',typeNames[event.eventType]||event.eventType),ui.el('p',`${event.cameraCode} · ${event.eventTime}`),ui.el('span',({PENDING:'待处理',PROCESSING:'处理中',DONE:'已完成'})[event.status]||event.status,{class:'sidebar-status'}),ui.button('查看事件',()=>window.showEvent(event.id)));
    item.append(content);prepend?box.prepend(item):box.append(item);while(box.children.length>10)box.lastElementChild.remove();
  }
  async function loadLatest(){if(!box)return;try{const rows=await api('events/latest?size=10');if(Array.isArray(rows)){box.replaceChildren();seen.clear();for(const row of rows)renderItem(row);if(!rows.length)box.append(ui.el('div','暂无真实告警事件',{class:'text-secondary'}));}}catch(e){/* Connection status already reports backend failures. */}}
  async function connect(){if(stopped)return;try{const data=await api('auth/ws-ticket',{method:'POST',body:{}});if(stopped)return;const url=new URL(window.APP_CONFIG.wsUrl,location.href);url.searchParams.set('ticket',data.ticket);socket=new WebSocket(url);socket.onopen=()=>{delay=1000;status.textContent='实时事件已连接';eventBus.dispatchEvent(new Event('resync'));loadLatest();};socket.onmessage=e=>{try{const msg=JSON.parse(e.data);if(!['EVENT_CREATED','EVENT_STATUS_UPDATED','EVENT_DELETED'].includes(msg.messageType)||!msg.data?.id)return;eventBus.dispatchEvent(new CustomEvent('event',{detail:msg}));if(msg.messageType==='EVENT_STATUS_UPDATED'||msg.messageType==='EVENT_DELETED'){seen.delete(String(msg.data.id));loadLatest();return;}if(seen.has(String(msg.data.id)))return;renderItem(msg.data,true);if('Notification'in window&&Notification.permission==='granted'){navigator.serviceWorker?.getRegistration().then(reg=>{if(reg)return reg.showNotification('腰间北斗智能监护提醒',{body:'收到新的监护事件，请登录平台查看。',tag:String(msg.data.id)});try{new Notification('腰间北斗智能监护提醒',{body:'收到新的监护事件，请登录平台查看。',tag:String(msg.data.id)});}catch(err){}}).catch(()=>{});}}catch(err){ui.error(new Error('事件消息格式异常'));}};socket.onerror=()=>{status.textContent='事件连接异常，正在重试；可手动刷新查询';};socket.onclose=retry;}catch(e){status.textContent='事件服务未连接：'+e.message;retry();}}
  function retry(){if(stopped)return;clearTimeout(timer);timer=setTimeout(connect,delay);delay=Math.min(delay*2,30000);}
  window.addEventListener('pagehide',()=>{stopped=true;clearTimeout(timer);socket?.close();});connect();
  document.getElementById('notifyButton').onclick=()=>ui.run(async()=>{if(!('Notification'in window)||!isSecureContext)throw new Error('通知需要HTTPS或本机localhost，并使用支持的浏览器');if(await Notification.requestPermission()!=='granted')throw new Error('通知权限未授予');if(!('serviceWorker'in navigator)||!('PushManager'in window))throw new Error('当前浏览器只支持页面打开时的通知');const key=await api('notifications/public-key');const registration=await navigator.serviceWorker.register('/service-worker.js');await navigator.serviceWorker.ready;const bytes=Uint8Array.from(atob(key.publicKey.replace(/-/g,'+').replace(/_/g,'/').padEnd(Math.ceil(key.publicKey.length/4)*4,'=')),c=>c.charCodeAt(0));const sub=await registration.pushManager.getSubscription()||await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:bytes});await api('notifications/subscriptions',{method:'POST',body:sub.toJSON()});document.getElementById('notifyButton').textContent='通知已订阅';});
})();

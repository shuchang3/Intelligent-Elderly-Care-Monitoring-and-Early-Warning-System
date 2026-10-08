'use strict';
(()=>{
  const box=document.createElement('p');box.id='healthStatus';box.setAttribute('role','status');
  document.getElementById('connectionStatus').after(box);
  let stopped=false;window.addEventListener('pagehide',()=>stopped=true);
  async function refresh(){
    if(stopped)return;
    try{
      const r=await fetch('/health'),data=await r.json(),ai=data.algorithm||{},outbox=ai.outbox||{};
      const count=Object.values(outbox.queue||{}).reduce((a,b)=>a+Number(b),0);
      const warnings=[data.backend?.status!=='UP'?'Java或数据库不可用':null,ai.message,ai.emotionError,outbox.error,data.notifications?.message].filter(Boolean);
      box.className=warnings.length?'error':'muted';
      box.textContent=warnings.length?warnings.join('；'):`页面服务正常 · 算法 ${ai.status||'未知'} · 待发送/失败记录 ${count} · Redis ${data.backend?.redis||'未知'}`;
    }catch(e){box.className='error';box.textContent='无法读取服务健康状态，请检查本机服务。';}
    finally{if(!stopped)setTimeout(refresh,10000);}
  }
  refresh();
  if(document.body.dataset.role==='ADMIN'){
    const button=ui.button('通知发送记录',async()=>{const jobs=await api('notifications/jobs');ui.dialog(ui.table(jobs,[['id','任务'],['eventId','事件'],['state','结果'],['attempts','尝试次数'],['lastError','失败原因']]));},'btn btn-outline-secondary');
    document.getElementById('notificationActions').append(button);
  }
  const cancel=ui.button('取消通知',async()=>{
    await api('notifications/subscriptions',{method:'DELETE'});
    if('serviceWorker'in navigator){const registration=await navigator.serviceWorker.getRegistration();const sub=await registration?.pushManager?.getSubscription();if(sub)await sub.unsubscribe();}
    document.getElementById('notifyButton').textContent='订阅通知';
  },'btn btn-outline-secondary');document.getElementById('notificationActions').append(cancel);
})();

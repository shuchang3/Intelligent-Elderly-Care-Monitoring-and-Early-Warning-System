'use strict';
(async () => {
  const root=document.getElementById('cameras'); if(!root)return;
  let stopped=false; window.addEventListener('pagehide',()=>stopped=true);
  try {
    const [cameras,zones]=await Promise.all([api('cameras'),api('danger-zones')]);
    const controlForm=document.getElementById('aiControlForm'),controlSelect=document.getElementById('controlCamera'),syncState=document.getElementById('controlSyncState');
    if(controlForm){
      for(const camera of cameras)controlSelect.append(ui.el('option',`${camera.cameraName} · ${camera.cameraCode}`,{value:camera.cameraCode}));
      const showControl=()=>{const camera=cameras.find(c=>c.cameraCode===controlSelect.value);let config={};try{config=JSON.parse(camera.configJson||'{}');}catch(e){}for(const key of ['fallEnabled','strangerEnabled','dangerEnabled','emotionEnabled'])controlForm.elements[key].checked=config[key]!==false;syncState.textContent=`当前配置版本 ${camera.version}，算法确认版本 ${camera.appliedVersion}；${String(camera.version)===String(camera.appliedVersion)?'已生效':'等待算法同步'}`;};
      controlSelect.onchange=showControl;showControl();
      controlForm.onsubmit=e=>{e.preventDefault();ui.run(async()=>{const camera=cameras.find(c=>c.cameraCode===controlSelect.value),button=controlForm.querySelector('button[type="submit"]');let config={};try{config=JSON.parse(camera.configJson||'{}');}catch(err){}for(const key of ['fallEnabled','strangerEnabled','dangerEnabled','emotionEnabled'])config[key]=controlForm.elements[key].checked;button.disabled=true;try{await api('cameras/'+camera.cameraCode,{method:'PUT',body:{cameraName:camera.cameraName,location:camera.location,captureSource:camera.captureSource,enabled:camera.enabled,config}});camera.configJson=JSON.stringify(config);camera.version=Number(camera.version)+1;syncState.textContent=`配置已保存为版本 ${camera.version}，等待算法确认后生效`;syncState.className='small mt-2 mb-0 text-warning';}finally{button.disabled=false;}});};
    }
    for(const camera of cameras){
      const panel=ui.panel(camera.cameraName+' · '+camera.cameraCode);
      const view=ui.el('div',null,{class:'camera-view'});
      const canvas=ui.el('canvas',null,{width:640,height:480});
      const overlay=ui.el('canvas',null,{width:640,height:480,class:'overlay'});
      const state=ui.el('p','连接中…',{class:'camera-state'});
      view.append(canvas,overlay);panel.append(view,state);root.append(panel);
      let points=[],editing=null;
      const cameraZones=zones.filter(z=>z.cameraCode===camera.cameraCode);
      const ctx=canvas.getContext('2d'),draw=overlay.getContext('2d');
      function redraw(){
        draw.clearRect(0,0,640,480);
        const existing=cameraZones.filter(z=>z.enabled&&z.zoneCode!==editing?.zoneCode);
        for(const zone of existing){
          const polygon=JSON.parse(zone.pointsJson);
          if(!polygon.length)continue;
          draw.beginPath();draw.strokeStyle='#45dab0';
          polygon.forEach(([x,y],i)=>i?draw.lineTo(x*640,y*480):draw.moveTo(x*640,y*480));
          if(polygon.length>=3)draw.closePath();draw.stroke();
          for(const [x,y]of polygon)draw.fillRect(x*640-3,y*480-3,6,6);
          const [tx,ty]=polygon[0];
          draw.fillStyle='#45dab0';draw.font='12px sans-serif';
          draw.fillText(zone.zoneName,tx*640+4,ty*480-4);
        }
        if(points.length){
          draw.beginPath();draw.strokeStyle='#ffe16a';
          points.forEach(([x,y],i)=>i?draw.lineTo(x*640,y*480):draw.moveTo(x*640,y*480));
          if(points.length>=3)draw.closePath();draw.stroke();
          for(const [x,y]of points)draw.fillRect(x*640-3,y*480-3,6,6);
        }
      }
      if(role==='ADMIN'){
        overlay.onclick=e=>{
          if(points.length>=32){ui.error(new Error('最多32个顶点'));return;}
          const b=overlay.getBoundingClientRect();
          points.push([Math.min(1,Math.max(0,(e.clientX-b.left)/b.width)),Math.min(1,Math.max(0,(e.clientY-b.top)/b.height))]);redraw();
        };
        panel.append(ui.button('撤销顶点',()=>{points.pop();redraw();}),ui.button('清空/新建',()=>{editing=null;points=[];redraw();}),ui.button('保存区域',async()=>{
          if(points.length<3)throw new Error('请至少点击三个顶点');
          const form=ui.form([['zoneName','区域名称','text',editing?.zoneName||'危险区'],['enterSeconds','进入持续秒数','number',editing?.enterSeconds||1],['exitSeconds','离开解除秒数','number',editing?.exitSeconds||2],['enabled','启用','checkbox',true]],async data=>{
            data.points=points;data.enterSeconds=Number(data.enterSeconds);data.exitSeconds=Number(data.exitSeconds);
            if(editing)await api('danger-zones/'+editing.zoneCode,{method:'PUT',body:data});
            else await api('danger-zones',{method:'POST',body:{...data,zoneCode:'ZONE-'+crypto.randomUUID().slice(0,8),cameraCode:camera.cameraCode}});
            location.reload();
          });ui.dialog(form);
        }));
        for(const zone of cameraZones){
          const confirmed=String(zone.version)===String(zone.appliedVersion);
          panel.append(ui.el('p',`${zone.zoneName} · ${zone.enabled?'启用':'停用'} · ${confirmed?'算法已确认':'等待算法同步'} (${zone.version}/${zone.appliedVersion})`));
          panel.append(ui.button('编辑 '+zone.zoneName,()=>{editing=zone;points=JSON.parse(zone.pointsJson).map(p=>[...p]);redraw();}));
          if(zone.enabled)panel.append(ui.button('删除/停用 '+zone.zoneName,async()=>{
            await api('danger-zones/'+zone.zoneCode,{method:'DELETE'});location.reload();
          }));
        }
      }
      redraw();
      async function poll(){
        if(stopped)return;
        try{
          const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),4000);
          const response=await fetch('/api/camera_frame?cameraCode='+encodeURIComponent(camera.cameraCode),{signal:controller.signal});
          clearTimeout(timer);
          if(response.status===401){location.assign('/login');return;}
          if(!response.ok)throw new Error('画面接口不可用');
          const data=await response.json();state.textContent=data.status+(data.message?' · '+data.message:'');
          if(data.frame){const image=new Image();image.onload=()=>{if(!stopped)ctx.drawImage(image,0,0,640,480);};image.src='data:image/jpeg;base64,'+data.frame;}
          else{ctx.fillStyle='#172a32';ctx.fillRect(0,0,640,480);}
        }catch(e){state.textContent=e.name==='AbortError'?'画面接口超时，自动重试中…':e.message;ctx.clearRect(0,0,640,480);}
        finally{if(!stopped)setTimeout(poll,500);}
      }
      poll();
    }
  }catch(e){ui.error(e);}
})();

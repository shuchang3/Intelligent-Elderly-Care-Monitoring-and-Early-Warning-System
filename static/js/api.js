'use strict';
window.ui = {
  el(tag, text, attrs = {}) { const el = document.createElement(tag); if (text != null) el.textContent = text; for (const [k,v] of Object.entries(attrs)) el.setAttribute(k,v); return el; },
  error(error) { const box = document.getElementById('globalError'); box.hidden = false; box.textContent = error.message || String(error); },
  async run(fn) { try { document.getElementById('globalError').hidden = true; return await fn(); } catch (e) { ui.error(e); } },
  button(text, fn, cls = 'btn btn-outline-primary btn-sm') { const b = ui.el('button',text,{type:'button',class:cls}); b.onclick = () => ui.run(async()=>{b.disabled=true;try {await fn();}finally {b.disabled=false;}}); return b; },
  table(rows, columns, actions) { const wrap=ui.el('div',null,{class:'table-responsive'}); if (!rows.length) {wrap.append(ui.el('p','暂无实际数据',{class:'text-secondary text-center py-4'}));return wrap;} const table=ui.el('table',null,{class:'table table-hover align-middle'}),thead=ui.el('thead'),head=ui.el('tr'); for(const [key,label] of columns) head.append(ui.el('th',label)); if(actions)head.append(ui.el('th','操作')); thead.append(head);table.append(thead);const tbody=ui.el('tbody');for(const row of rows){const tr=ui.el('tr');for(const [key] of columns)tr.append(ui.el('td',row[key]==null?'—':typeof row[key]==='object'?JSON.stringify(row[key]):String(row[key])));if(actions){const td=ui.el('td');actions(row,td);tr.append(td);}tbody.append(tr);}table.append(tbody);wrap.append(table);return wrap; },
  form(fields, submit, title='保存') { const form=ui.el('form',null,{class:'data-form'});for(const f of fields){const [name,label,type='text',value='']=f;const l=ui.el('label',label,{class:type==='checkbox'?'form-check-label':'form-label'});let input;if(Array.isArray(type)){input=ui.el('select',null,{name,class:'form-select'});for(const item of type)input.append(ui.el('option',item,{value:item}));}else input=ui.el('input',null,{name,type,class:type==='checkbox'?'form-check-input':'form-control'});if(type==='checkbox')input.checked=!!value;else input.value=value|| (Array.isArray(type)?type[0]:'');input.required=type!=='checkbox'&&name!=='note';l.append(input);form.append(l);}const b=ui.el('button',title,{class:'btn btn-primary'});form.append(b);form.onsubmit=e=>{e.preventDefault();ui.run(async()=>{b.disabled=true;try{const data=Object.fromEntries(new FormData(form));for(const f of fields)if(f[2]==='checkbox')data[f[0]]=form.elements[f[0]].checked;await submit(data,form);}finally{b.disabled=false;}});};return form; },
  panel(title) {const p=ui.el('section',null,{class:'panel'});p.append(ui.el('h2',title));return p;},
  dialog(content){document.getElementById('dialogBody').replaceChildren(content);document.getElementById('detailDialog').showModal();},
};
window.api = async function(path, options={}) {
  const headers = new Headers(options.headers || {});
  headers.set('X-CSRF-Token',document.querySelector('meta[name="csrf-token"]').content);
  if(options.body && !(options.body instanceof FormData)){headers.set('Content-Type','application/json');options.body=JSON.stringify(options.body);}
  let response;try{response=await fetch('/api/v1/'+path,{...options,headers,credentials:'same-origin'});}catch(e){throw new Error('网络连接失败');}
  if(response.status===401){location.assign('/login');throw new Error('登录已失效');}
  let body;try{body=await response.json();}catch(e){throw new Error('服务返回格式异常');}
  if(response.status===403&&body.message?.includes('页面验证已失效')){location.reload();throw new Error('页面会话已更新，正在刷新');}
  if(!response.ok||body.code!==200)throw new Error(body.message||`请求失败 ${response.status}`);
  return body.data;
};
window.typeNames={FALL:'老人跌倒',STRANGER:'陌生人',DANGER_ZONE:'危险区域闯入',EMOTION_ABNORMAL:'持续负面情绪'};
window.eventBus=new EventTarget();
document.getElementById('closeDialog').onclick=()=>document.getElementById('detailDialog').close();
const userDialog=document.getElementById('userDialog');
document.getElementById('personalButton').onclick=()=>userDialog.showModal();
document.getElementById('closeUserDialog').onclick=()=>userDialog.close();
document.getElementById('passwordForm').onsubmit=e=>{e.preventDefault();ui.run(async()=>{const form=e.currentTarget,button=form.querySelector('button[type="submit"]'),data=Object.fromEntries(new FormData(form));button.disabled=true;try{await api('auth/password',{method:'PUT',body:data});location.assign('/login?reason=expired');}finally{button.disabled=false;}});};

const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
function element(){return {textContent:'',children:[],hidden:true,append(...nodes){this.children.push(...nodes)},prepend(node){this.children.unshift(node)},replaceChildren(...nodes){this.children=nodes},querySelector(){return this.children.find(n=>n.isEvent)},get lastElementChild(){return {remove:()=>this.children.pop()}},setAttribute(){}};}
function sandbox(){
  const nodes=new Map();const context={Headers,FormData,Event,CustomEvent,EventTarget,URL,Uint8Array,Map,JSON,Promise,console,
    document:{getElementById(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)},querySelector(){return {content:'csrf-from-server'}}},
    location:{href:'http://127.0.0.1:5001/dashboard',assign(url){context.redirect=url}},
    addEventListener(name,fn){context.listeners[name]=fn},listeners:{},timers:[],setTimeout(fn,delay){context.timers.push({fn,delay});return 1},clearTimeout(){}};
  context.window=context;return {context:vm.createContext(context),nodes};
}
test('API checks HTTP AND application errors; CSRF is attached and 401 redirects',async()=>{
  const {context:c}=sandbox();let reply={ok:true,status:200,json:async()=>({code:200,data:{id:'9007199254740993'}})};const requests=[];
  c.fetch=async(url,options)=>{requests.push({url,options});return reply};
  vm.runInContext(fs.readFileSync(path.join(root,'static/js/api.js'),'utf8'),c);
  const result=await c.api('events/1/status',{method:'PUT',body:{status:'DONE'}});
  assert.equal(result.id,'9007199254740993');assert.equal(requests[0].options.headers.get('X-CSRF-Token'),'csrf-from-server');
  assert.equal(requests[0].options.credentials,'same-origin');
  reply={ok:true,status:200,json:async()=>({code:409,message:'conflict'})};await assert.rejects(c.api('events/page'),/conflict/);
  reply={ok:false,status:503,json:async()=>({code:503,message:'backend down'})};await assert.rejects(c.api('events/page'),/backend down/);
  reply={ok:false,status:401};await assert.rejects(c.api('events/page'));assert.equal(c.redirect,'/login');
});
test('WebSocket uses one-use ticket, deduplicates created events, updates status and resyncs',async()=>{
  const {context:c,nodes}=sandbox();const sockets=[],calls=[],events=[];let resync=0;
  c.APP_CONFIG={wsUrl:'ws://127.0.0.1:8081/ws/events'};c.eventBus=new EventTarget();
  c.eventBus.addEventListener('event',e=>events.push(e.detail));c.eventBus.addEventListener('resync',()=>resync++);
  c.typeNames={FALL:'跌倒'};c.api=async(path,options)=>{calls.push({path,options});return {ticket:'short-lived'}};
  c.ui={el(tag,text,attrs={}){return {...element(),textContent:text,isEvent:!!attrs.class?.startsWith('event ')}},button(){return element()},error(e){throw e},run:fn=>fn()};
  c.WebSocket=class {constructor(url){this.url=url;sockets.push(this)}close(){this.onclose?.()}};
  vm.runInContext(fs.readFileSync(path.join(root,'static/js/socket_base.js'),'utf8'),c);await new Promise(setImmediate);
  assert.equal(calls[0].path,'auth/ws-ticket');assert.equal(calls[0].options.method,'POST');
  assert.equal(sockets[0].url.searchParams.get('ticket'),'short-lived');assert.equal(sockets[0].url.searchParams.has('token'),false);
  sockets[0].onopen();assert.equal(resync,1);
  const data={id:'123',eventType:'FALL',eventLevel:'URGENT',cameraCode:'CAM001',eventTime:'2026-09-01T08:00:00'};
  for(const messageType of ['EVENT_CREATED','EVENT_CREATED','EVENT_STATUS_UPDATED'])sockets[0].onmessage({data:JSON.stringify({messageType,data})});
  assert.equal(nodes.get('alertList').children.length,1);assert.equal(events.length,3);
  sockets[0].onclose();assert.equal(c.timers[0].delay,1000);await c.timers[0].fn();sockets[1].onopen();assert.equal(resync,2);
  c.listeners.pagehide();assert.equal(sockets.length,2);
});

"""Export local API contract, verifying paths against controller annotations."""
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
S={'type':'string'};B={'type':'boolean'};N={'type':'number'};I={'type':'integer'}
def obj(properties,required=()):return {'type':'object','properties':properties,'required':list(required)} if required else {'type':'object','properties':properties}
def enum(*values):return {'type':'string','enum':list(values)}
event=obj({'id':S,'eventNo':{'type':'string','format':'uuid'},'eventType':enum('FALL','STRANGER','DANGER_ZONE','EMOTION_ABNORMAL'),'cameraCode':S,'personCode':dict(S,nullable=True),'zoneCode':dict(S,nullable=True),'trackId':dict(S,nullable=True),'eventTime':dict(S,example='2026-09-01T08:00:00'),'description':S,'confidence':dict(N,nullable=True),'scoreType':dict(S,nullable=True),'imageUrl':dict(S,nullable=True),'status':enum('PENDING','PROCESSING','DONE'),'eventLevel':enum('URGENT','WARNING','CARE'),'videoState':enum('PENDING','READY','FAILED')})
event_input={k:v for k,v in event['properties'].items() if k not in ('id','imageUrl','status','eventLevel','videoState')}
event_input['snapshot']={'type':'string','format':'binary'}
schemas={'Event':event,'Envelope':obj({'code':I,'message':S,'data':{}},['code','message']),'Error':obj({'code':I,'message':S},['code','message'])}
config=obj({**{k:B for k in ['fallEnabled','emotionEnabled','strangerEnabled','dangerEnabled','soundEnabled']},'sadSeconds':dict(N,minimum=.001,maximum=3600),'missingSeconds':dict(N,minimum=.001,maximum=3600),'fallCooldownSeconds':dict(N,minimum=.001,maximum=3600),'captureFps':dict(N,minimum=.001,maximum=60)})
config['additionalProperties']=False
polygon={'type':'array','minItems':3,'maxItems':32,'items':{'type':'array','minItems':2,'maxItems':2,'items':dict(N,minimum=0,maximum=1)}}
zone=obj({'zoneCode':S,'cameraCode':S,'zoneName':S,'points':polygon,'enabled':B,'enterSeconds':dict(N,default=1),'exitSeconds':dict(N,default=2)},['zoneCode','cameraCode','zoneName','points'])
camera=obj({'cameraCode':S,'cameraName':S,'location':S,'captureSource':S,'enabled':B,'config':config},['cameraCode','cameraName','location','captureSource'])
contracts={
 ('post','/auth/login'):obj({'username':S,'password':dict(S,format='password')},['username','password']),
 ('put','/auth/password'):obj({'oldPassword':dict(S,format='password'),'newPassword':dict(S,format='password',minLength=12)},['oldPassword','newPassword']),
 ('post','/ai/events'):obj(event_input,['eventNo','eventType','cameraCode','eventTime','description']),
 ('put','/events/{id}/status'):obj({'status':enum('PROCESSING','DONE'),'remark':S},['status']),
 ('post','/persons'):obj({'personCode':S,'name':S,'personType':enum('ELDER','WORKER','FAMILY'),'note':S},['personCode','name','personType']),
 ('put','/persons/{code}'):obj({'name':S,'note':S},['name']),
 ('post','/persons/{code}/face'):obj({'file':{'type':'string','format':'binary'}},['file']),
 ('post','/cameras'):camera,
 ('put','/cameras/{code}'):dict(camera,required=['cameraName','location','captureSource','enabled']),
 ('post','/danger-zones'):zone,
 ('put','/danger-zones/{code}'):dict(zone,required=['zoneName','points','enabled']),
 ('post','/users'):obj({'username':S,'password':dict(S,minLength=12),'realName':S,'role':enum('ADMIN','STAFF','FAMILY')},['username','password','realName','role']),
 ('put','/users/{id}'):obj({'role':enum('ADMIN','STAFF','FAMILY'),'status':enum('NORMAL','DISABLED')},['role','status']),
 ('post','/family-bindings'):obj({'userId':S,'personCode':S},['userId','personCode']),
 ('post','/ai/ack'):obj({'kind':enum('person','camera','zone'),'code':S,'version':{'type':'string','description':'版本号；整数也可接收'},'state':enum('ACTIVE','FAILED','REMOVED','NONE'),'error':dict(S,nullable=True)},['kind','code','version']),
 ('post','/ai/heartbeat'):obj({'cameraCode':S,'status':enum('ONLINE','OFFLINE','ERROR','DISABLED'),'error':dict(S,nullable=True)},['cameraCode','status']),
 ('post','/ai/samples'):obj({'kind':enum('emotion','track'),'sampleNo':dict(S,format='uuid'),'cameraCode':S,'personCode':S,'sampleTime':S,'emotion':enum('sad','happy','angry','fear','disgust','surprise','neutral'),'score':dict(N,minimum=0,maximum=1),'trackId':S,'x':dict(N,minimum=0,maximum=1),'y':dict(N,minimum=0,maximum=1)},['kind','sampleNo','cameraCode','sampleTime']),
 ('post','/ai/interactions'):obj({'recordNo':dict(S,format='uuid'),'cameraCode':S,'elderCode':S,'workerCode':S,'startTime':S,'endTime':S},['recordNo','cameraCode','elderCode','workerCode','startTime','endTime']),
 ('put','/analytics/interactions/{id}'):obj({'status':enum('CONFIRMED','REJECTED')},['status']),
 ('post','/ai/events/{no}/video'):obj({'state':enum('READY','FAILED'),'error':S,'file':{'type':'string','format':'binary'}},['state']),
 ('put','/alert-rules'):obj({'eventType':event['properties']['eventType'],'eventLevel':enum('URGENT','WARNING','CARE')},['eventType','eventLevel']),
 ('post','/notifications/subscriptions'):obj({'endpoint':dict(S,format='uri'),'keys':obj({'p256dh':S,'auth':S},['p256dh','auth'])},['endpoint','keys']),
 ('post','/ai/notification-jobs/{id}'):obj({'state':enum('SENT','RETRY','FAILED'),'error':dict(S,nullable=True)},['state'])
}
paths={}
for source in (ROOT/'backend/src/main/java/com/eldercare/platform').glob('*Controller.java'):
    for match in re.finditer(r'@(Get|Post|Put|Delete)Mapping\(([^\n]*?)\)',source.read_text(encoding='utf8')):
        method=match[1].lower()
        for path in re.findall(r'"(/[^\"]+)"',match[2]):
            short=path.removeprefix('/api/v1')
            operation={'summary':method.upper()+' '+path,'security':[] if path=='/health' or short=='/auth/login' else [{'AlgorithmKey':[]}] if short.startswith('/ai/') else [{'BearerAuth':[]}],'parameters':[],'responses':{'200':{'description':'成功；业务code=200','content':{'application/json':{'schema':{'$ref':'#/components/schemas/Envelope'}}}}}}
            for error in (400,401,403,404,409,413,503):operation['responses'][str(error)]={'description':{400:'参数无效',401:'认证失效',403:'权限不足',404:'记录或媒体不存在',409:'重复内容冲突、过期配置、录像未就绪等',413:'文件太大',503:'数据库或可选能力不可用'}[error],'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Error'}}}}
            for name in re.findall(r'\{(\w+)\}',path):operation['parameters'].append({'name':name,'in':'path','required':True,'schema':S})
            if (method,short) in contracts:
                multipart=short=='/ai/events' or short.endswith('/face') or short.endswith('/video')
                operation['requestBody']={'required':True,'content':{'multipart/form-data' if multipart else 'application/json':{'schema':contracts[method,short]}}}
            if method=='get' and short in ('/events','/events/page','/events/latest'):
                for name in ['page','size','eventType','cameraCode','personCode','status','startTime','endTime']:
                    operation['parameters'].append({'name':name,'in':'query','schema':dict(I,minimum=1,default=1 if name=='page' else 20) if name in ('page','size') else S})
            if method=='get' and short.startswith('/analytics/'):
                for name in ['personCode','cameraCode']:operation['parameters'].append({'name':name,'in':'query','schema':S})
            if method=='delete' and short=='/family-bindings':
                operation['parameters'] += [{'name':name,'in':'query','required':True,'schema':S} for name in ['userId','personCode']]
            if method=='get' and short.endswith(('/snapshot','/video','/face')):
                mime='video/mp4' if short.endswith('/video') else 'image/jpeg'
                operation['responses']['200']={'description':'鉴权后的媒体字节','content':{mime:{'schema':{'type':'string','format':'binary'}}}}
                if mime=='video/mp4':
                    operation['parameters'].append({'name':'Range','in':'header','schema':S,'example':'bytes=0-99'})
                    operation['responses']['206']={'description':'HTTP Range分段读取'}
            paths.setdefault(path,{})[method]=operation
spec={'openapi':'3.0.3','info':{'title':'视界无疆单机后端','version':'1.0.0','description':'与当前Controller路径同步的导入契约。条件必填、权限及WebSocket消息详见API.md；不是原ZIP的数据库兼容声明。'},'servers':[{'url':'http://127.0.0.1:8081','description':'本机联调配置'},{'url':'http://127.0.0.1:8080','description':'默认示例'}],'paths':paths,'components':{'securitySchemes':{'BearerAuth':{'type':'http','scheme':'bearer','bearerFormat':'JWT'},'AlgorithmKey':{'type':'apiKey','in':'header','name':'X-AI-Key'}},'schemas':schemas},'x-websocket':{'url':'/ws/events?ticket=<一次性票据>','expiresIn':30,'singleUse':True,'messageTypes':['EVENT_CREATED','EVENT_STATUS_UPDATED']}}
(ROOT/'docs/openapi.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf8')
print('Exported',len(paths),'paths /',sum(len(p) for p in paths.values()),'HTTP operations')

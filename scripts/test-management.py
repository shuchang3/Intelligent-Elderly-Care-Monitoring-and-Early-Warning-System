"""Real MySQL management/media acceptance using synthetic records only."""
import io,json,os,re,sys,uuid,subprocess
from datetime import datetime,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
from PIL import Image
import requests
load_dotenv(ROOT/'.env.local')
base=os.environ['JAVA_BASE_URL'];web='http://127.0.0.1:'+os.getenv('PORT','5000')
http=requests.Session();http.trust_env=False
tag=uuid.uuid4().hex[:8];codes=['TEST-E-'+tag,'TEST-W-'+tag]
def call(method,path,status=200,**kw):
    r=http.request(method,base+'/api/v1/'+path,timeout=20,**kw)
    assert r.status_code==status,(path,r.status_code,r.text[:200])
    return r.json().get('data') if status==200 else None
token=call('POST','auth/login',json={'username':'admin','password':os.environ['BOOTSTRAP_ADMIN_PASSWORD']})['token']
http.headers['Authorization']='Bearer '+token
ai={'X-AI-Key':os.environ['AI_SERVICE_KEY']}
for code,kind in zip(codes,['ELDER','WORKER']):call('POST','persons',json={'personCode':code,'name':'TEST 无真人 '+kind,'personType':kind})
image=io.BytesIO();Image.new('RGB',(320,240),'navy').save(image,format='PNG')
call('POST','persons/'+codes[0]+'/face',files={'file':('no-face.png',image.getvalue(),'image/png')})
from algorithm.faces import FaceRegistry
registry=FaceRegistry()
def sync():
    data=call('GET','ai/config',headers=ai)
    people=[p for p in data['persons'] if p['personCode'] in codes]
    def download(code):
        r=http.get(base+'/api/v1/ai/persons/'+code+'/face',headers=ai,timeout=10);r.raise_for_status();return r.content
    registry.synchronize(people,download,lambda code,version,state,error:call('POST','ai/ack',headers=ai,json={'kind':'person','code':code,'version':version,'state':state,'error':error}))
sync()
person=next(p for p in call('GET','persons') if p['personCode']==codes[0]);assert person['faceState']=='FAILED'
call('POST','ai/ack',status=409,headers=ai,json={'kind':'person','code':codes[0],'version':0,'state':'ACTIVE'})
zone='TEST-Z-'+tag
call('POST','danger-zones',status=400,json={'zoneCode':zone,'cameraCode':'CAM001','zoneName':'TEST invalid','points':[[0,0],[1,1],[0,1],[1,0]]})
call('POST','danger-zones',json={'zoneCode':zone,'cameraCode':'CAM001','zoneName':'TEST zone','points':[[0,0],[1,0],[1,1],[0,1]],'enterSeconds':1,'exitSeconds':2})
family='test_family_'+tag;password=uuid.uuid4().hex
user=call('POST','users',json={'username':family,'realName':'TEST 家属','role':'FAMILY','password':password})
call('POST','family-bindings',json={'userId':user['id'],'personCode':codes[0]})
f=requests.Session();f.trust_env=False
r=f.post(base+'/api/v1/auth/login',json={'username':family,'password':password},timeout=10);r.raise_for_status();f.headers['Authorization']='Bearer '+r.json()['data']['token']
now=datetime.now().replace(microsecond=0);event_no=str(uuid.uuid4())
event=call('POST','ai/events',headers=ai,data={'eventNo':event_no,'eventType':'DANGER_ZONE','cameraCode':'CAM001','personCode':codes[0],'zoneCode':zone,'eventTime':now.isoformat(),'description':'TEST synthetic management acceptance'},files={'snapshot':('test.png',image.getvalue(),'image/png')})
assert f.get(base+'/api/v1/events/'+event['id'],timeout=10).status_code==200
assert f.put(base+'/api/v1/events/'+event['id']+'/status',json={'status':'DONE'},timeout=10).status_code==403
for kind in ['emotion','track']:
    payload={'kind':kind,'sampleNo':str(uuid.uuid4()),'cameraCode':'CAM001','personCode':codes[0],'sampleTime':now.isoformat()}
    payload.update({'emotion':'sad','score':.8} if kind=='emotion' else {'trackId':'TEST-'+tag,'x':.5,'y':.8})
    call('POST','ai/samples',headers=ai,json=payload)
    assert call('GET','analytics/'+('emotion' if kind=='emotion' else 'tracks'),params={'personCode':codes[0]})
record_no=str(uuid.uuid4())
call('POST','ai/interactions',headers=ai,json={'recordNo':record_no,'cameraCode':'CAM001','elderCode':codes[0],'workerCode':codes[1],'startTime':(now-timedelta(seconds=30)).isoformat(),'endTime':now.isoformat()})
interaction=next(r for r in call('GET','analytics/interactions',params={'personCode':codes[0]}) if r['recordNo']==record_no)
call('PUT','analytics/interactions/'+interaction['id'],json={'status':'CONFIRMED'})
call('PUT','analytics/interactions/'+interaction['id'],status=409,json={'status':'REJECTED'})
import imageio_ffmpeg
video=ROOT/'runtime'/('TEST-'+tag+'.mp4')
subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-loglevel','error','-f','lavfi','-i','color=c=blue:s=320x240:r=5','-t','1','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(video)],check=True,timeout=20,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
call('POST','ai/events/'+event_no+'/video',headers=ai,data={'state':'READY'},files={'file':('test.mp4',video.read_bytes(),'video/mp4')})
response=http.get(base+'/api/v1/events/'+event['id']+'/video',headers={'Range':'bytes=0-99'},timeout=10)
assert response.status_code==206 and len(response.content)==100
call('DELETE','family-bindings',params={'userId':user['id'],'personCode':codes[0]})
assert f.get(base+'/api/v1/events/'+event['id'],timeout=10).status_code==403
assert f.get(base+'/api/v1/events/'+event['id']+'/video',timeout=10).status_code==403
call('PUT','users/'+user['id'],json={'role':'FAMILY','status':'DISABLED'})
assert f.get(base+'/api/v1/auth/me',timeout=10).status_code==401
call('PUT','events/'+event['id']+'/status',json={'status':'DONE','remark':'TEST 自动验收'})
call('DELETE','danger-zones/'+zone)
for code in codes:call('DELETE','persons/'+code)
sync()
assert not registry.entries
print(json.dumps({'result':'PASS','eventId':event['id'],'checks':['no-face upload FAILED','stale ack 409','zone geometry','bound family scope','emotion aggregation','trajectory','interaction review','actual MP4 upload and HTTP range','unbind revocation','disabled token','delete face sync']},ensure_ascii=False))

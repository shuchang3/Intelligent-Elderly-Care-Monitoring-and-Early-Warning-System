"""Real local integration smoke test. Creates explicitly labelled synthetic events only."""
import io
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
import requests
from dotenv import load_dotenv
from PIL import Image

ROOT=Path(__file__).resolve().parent.parent
load_dotenv(ROOT/'.env.local')
web='http://127.0.0.1:'+os.getenv('PORT','5000')
java=os.getenv('JAVA_BASE_URL','http://127.0.0.1:8080')
s=requests.Session();s.trust_env=False
j=requests.Session();j.trust_env=False
admin=requests.Session();admin.trust_env=False
def check(r,status=200):
    assert r.status_code==status,f'HTTP {r.status_code}: {r.text[:200]}'
    return r
def data(r):
    body=check(r).json();assert body['code']==200,body
    return body['data']
def csrf(text):
    match=re.search(r'(?:name="csrf_token" value|name="csrf-token" content)="([^"]+)"',text)
    assert match,'Missing CSRF field'
    return match[1]
check(s.get(web+'/health',timeout=10))
admin_login=data(admin.post(java+'/api/v1/auth/login',json={'username':'admin','password':os.environ['BOOTSTRAP_ADMIN_PASSWORD']},timeout=10))
admin.headers['Authorization']='Bearer '+admin_login['token']
test_user='smoke_'+uuid.uuid4().hex[:10];test_password=uuid.uuid4().hex
test_user_id=data(admin.post(java+'/api/v1/users',json={'username':test_user,'password':test_password,'realName':'TEST 自动冒烟','role':'STAFF'},timeout=10))['id']
page=check(s.get(web+'/login',timeout=10))
r=s.post(web+'/login',data={'username':test_user,'password':test_password,'csrf_token':csrf(page.text)},allow_redirects=False,timeout=15)
check(r,302)
page=check(s.get(web+'/dashboard',timeout=15));assert '监控看板' in page.text,'Login session not retained: '+page.url
s.headers['X-CSRF-Token']=csrf(page.text)
assert data(s.get(web+'/api/v1/auth/me',timeout=10))['role']=='STAFF'
check(s.get(web+'/api/v1/ai/config',timeout=10),404)
check(requests.post(web+'/logout',proxies={'http':'','https':''},allow_redirects=False,timeout=10),302)
image=io.BytesIO();Image.new('RGB',(320,240),(24,76,99)).save(image,format='PNG')
event={'eventNo':str(uuid.uuid4()),'eventType':'FALL','cameraCode':'CAM001','eventTime':datetime.now().isoformat(timespec='seconds'),'description':'SMOKE TEST / 人工合成联调事件（非真实跌倒）'}
def report(payload):return j.post(java+'/api/v1/ai/events',headers={'X-AI-Key':os.environ['AI_SERVICE_KEY']},data=payload,files={'snapshot':('synthetic.png',image.getvalue(),'image/png')},timeout=15)
start=time.perf_counter();row=data(report(event));event_id=row['id'];assert isinstance(event_id,str)
assert data(report(event))['id']==event_id
check(report(dict(event,description='conflicting synthetic payload')),409)
records=data(s.get(web+'/api/v1/events/page',timeout=10))['records'];assert any(r['id']==event_id for r in records)
latest=data(s.get(web+'/api/v1/events/latest',timeout=10));assert isinstance(latest,list) and all(isinstance(item,dict) for item in latest)
snapshot=check(s.get(web+f'/api/v1/events/{event_id}/snapshot',timeout=10));assert snapshot.headers['Content-Type'].startswith('image/jpeg')
data(s.put(web+f'/api/v1/events/{event_id}/status',json={'status':'DONE','remark':'自动联调验收'},timeout=10))
assert data(s.get(web+f'/api/v1/events/{event_id}',timeout=10))['status']=='DONE'
assert len(data(s.get(web+f'/api/v1/events/{event_id}/records',timeout=10)))==1
check(s.put(web+f'/api/v1/events/{event_id}/status',json={'status':'PROCESSING'},timeout=10),409)
data(j.post(java+f'/api/v1/ai/events/{event["eventNo"]}/video',headers={'X-AI-Key':os.environ['AI_SERVICE_KEY']},files={'state':(None,'FAILED'),'error':(None,'人工事件没有录像')},timeout=10))
elapsed=round(time.perf_counter()-start,3)
check(s.post(web+'/logout',allow_redirects=False,timeout=10),302)
check(s.get(web+'/api/v1/events/page',timeout=10),401)
data(admin.put(java+'/api/v1/users/'+test_user_id,json={'role':'STAFF','status':'DISABLED'},timeout=10))
print(json.dumps({'result':'PASS','web':web,'eventId':event_id,'eventNo':event['eventNo'],'fullSmokeSeconds':elapsed,'checks':['real login','CSRF','allowlist','multipart snapshot','idempotency','conflict','history','authenticated media','persistent status','record','logout']},ensure_ascii=False))

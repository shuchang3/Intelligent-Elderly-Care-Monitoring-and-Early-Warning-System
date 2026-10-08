"""Seed clearly labelled DEMO records through the real Java APIs."""
import io,json,os,subprocess,sys,uuid
from datetime import datetime,timedelta
from pathlib import Path
import requests
from dotenv import load_dotenv
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parent.parent
load_dotenv(ROOT/'.env.local')
BASE=os.environ['JAVA_BASE_URL'].rstrip('/')+'/api/v1/'
http=requests.Session();http.trust_env=False
def call(method,path,status=200,**kwargs):
    response=http.request(method,BASE+path,timeout=30,**kwargs)
    if response.status_code!=status:raise RuntimeError(f'{method} {path}: {response.status_code} {response.text[:300]}')
    return response.json().get('data') if status==200 else None
login=call('POST','auth/login',json={'username':'admin','password':os.environ['BOOTSTRAP_ADMIN_PASSWORD']})
http.headers['Authorization']='Bearer '+login['token']
ai={'X-AI-Key':os.environ['AI_SERVICE_KEY']}

people=[('DEMO-E001','张爷爷（演示）','ELDER','一号卧室'),('DEMO-E002','李奶奶（演示）','ELDER','二号卧室'),('DEMO-W001','王护理（演示）','WORKER','负责一楼区域'),('DEMO-F001','王先生（演示）','FAMILY','张爷爷的家属')]
existing={row['personCode'] for row in call('GET','persons')}
demo_codes={code for code,_,_,_ in people}
if existing.intersection(demo_codes) not in (set(),demo_codes):
    raise SystemExit('DEMO人员只写入了一部分，请先运行 scripts/cleanup-demo-data.ps1 后重试。')

font_path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/msyh.ttc'
font=lambda size:ImageFont.truetype(str(font_path),size) if font_path.exists() else ImageFont.load_default()
def picture(title,subtitle,color,size=(640,400)):
    image=Image.new('RGB',size,'#eef5ff');draw=ImageDraw.Draw(image)
    draw.rectangle((0,0,size[0],100),fill=color);draw.text((30,24),title,font=font(34),fill='white')
    draw.rounded_rectangle((28,130,size[0]-28,size[1]-30),radius=20,fill='white',outline='#c9d8ec',width=3)
    draw.text((55,170),subtitle,font=font(26),fill='#183b56');draw.text((55,230),'视界无疆 · DEMO 演示数据',font=font(20),fill='#6b7280')
    out=io.BytesIO();image.save(out,'JPEG',quality=90);return out.getvalue()
def avatar(name,color):
    image=Image.new('RGB',(420,420),color);draw=ImageDraw.Draw(image);draw.ellipse((90,55,330,295),fill='#ffe0bd');draw.ellipse((130,125,155,150),fill='#263238');draw.ellipse((265,125,290,150),fill='#263238');draw.arc((155,155,270,240),0,180,fill='#8b4513',width=7);draw.text((72,335),name,font=font(28),fill='white');out=io.BytesIO();image.save(out,'JPEG',quality=92);return out.getvalue()

if not demo_codes.issubset(existing):
    for code,name,kind,note in people:
        call('POST','persons',json={'personCode':code,'name':name,'personType':kind,'note':note})
        call('POST',f'persons/{code}/face',files={'file':('demo-face.jpg',avatar(name,{'ELDER':'#5b8def','WORKER':'#38a169','FAMILY':'#d4a017'}[kind]),'image/jpeg')})

# 家属登录账户 + 绑定老人（演示）：家属登录后只能看到绑定老人的告警/情绪数据
family_user=os.environ.get('DEMO_FAMILY_USERNAME','family01')
family_pass=os.environ.get('DEMO_FAMILY_PASSWORD','Family@123456')
family_row=next((u for u in call('GET','users') if u.get('username')==family_user),None)
if family_row is None:
    family_row=call('POST','users',json={'username':family_user,'password':family_pass,'realName':'王先生（家属演示）','role':'FAMILY'})
if not any(str(b.get('userId'))==str(family_row['id']) and b.get('personCode')=='DEMO-E001' for b in call('GET','family-bindings')):
    call('POST','family-bindings',json={'userId':str(family_row['id']),'personCode':'DEMO-E001'})

zone='DEMO-Z001'
if not any(row['zoneCode']==zone for row in call('GET','danger-zones')):
    call('POST','danger-zones',json={'zoneCode':zone,'cameraCode':'CAM001','zoneName':'楼梯口危险区域（演示）','points':[[.58,.42],[.94,.42],[.94,.94],[.58,.94]],'enterSeconds':1,'exitSeconds':2})

now=datetime.now().replace(microsecond=0)
types=[('FALL','老人跌倒','DEMO-E001','#cf1322'),('DANGER_ZONE','危险区域闯入','DEMO-E002','#d48806'),('STRANGER','陌生人出现',None,'#d46b08'),('EMOTION_ABNORMAL','持续负面情绪','DEMO-E002','#1677ff')]
existing_events=[row for row in call('GET','events/page?page=1&size=100')['records'] if str(row.get('description','')).startswith('DEMO ')]
event_ids=[(row['id'],row['eventNo']) for row in existing_events]
for index in range(len(existing_events),12):
    kind,label,person,color=types[index%len(types)];time=now-timedelta(days=index%7,hours=index*2)
    payload={'eventNo':str(uuid.uuid4()),'eventType':kind,'cameraCode':'CAM001','eventTime':time.isoformat(),'description':f'DEMO 展示数据：{label}，用于查看前端卡片、图表和处理状态'}
    if person:payload['personCode']=person
    if kind=='DANGER_ZONE':payload['zoneCode']=zone
    row=call('POST','ai/events',headers=ai,data=payload,files={'snapshot':('demo.jpg',picture(label,f'CAM001 · {time:%Y-%m-%d %H:%M}',color),'image/jpeg')})
    event_ids.append((row['id'],payload['eventNo']))
    if index%3==0:call('PUT',f"events/{row['id']}/status",json={'status':'DONE','remark':'DEMO 已完成处理'})
    elif index%3==1:call('PUT',f"events/{row['id']}/status",json={'status':'PROCESSING','remark':'DEMO 正在跟进'})

if not call('GET','analytics/emotion?personCode=DEMO-E001'):
    for day in range(7):
        sample_time=(now-timedelta(days=6-day)).replace(hour=9,minute=30)
        for code in ['DEMO-E001','DEMO-E002']:
            emotions=['neutral','happy','sad'] if code=='DEMO-E001' else ['neutral','sad','sad']
            for n,emotion in enumerate(emotions):
                call('POST','ai/samples',headers=ai,json={'kind':'emotion','sampleNo':str(uuid.uuid4()),'cameraCode':'CAM001','personCode':code,'sampleTime':(sample_time+timedelta(minutes=n)).isoformat(),'emotion':emotion,'score':round(.62+.04*n,2)})

if not call('GET','analytics/tracks?personCode=DEMO-E001'):
    for n in range(18):
        call('POST','ai/samples',headers=ai,json={'kind':'track','sampleNo':str(uuid.uuid4()),'cameraCode':'CAM001','personCode':'DEMO-E001','sampleTime':(now-timedelta(minutes=18-n)).isoformat(),'trackId':'DEMO-TRACK-001','x':round(.12+n*.04,3),'y':round(.68-.18*((n%6)/5),3)})

all_interactions=call('GET','analytics/interactions')
if not any(str(row.get('elderCode','')).startswith('DEMO-') for row in all_interactions):
    for day in range(7):
        end=(now-timedelta(days=6-day)).replace(hour=15,minute=0);start=end-timedelta(minutes=18+day*4)
        call('POST','ai/interactions',headers=ai,json={'recordNo':str(uuid.uuid4()),'cameraCode':'CAM001','elderCode':'DEMO-E001' if day%2==0 else 'DEMO-E002','workerCode':'DEMO-W001','startTime':start.isoformat(),'endTime':end.isoformat()})
    all_interactions=call('GET','analytics/interactions')
for row in all_interactions:
    if str(row.get('elderCode','')).startswith('DEMO-') and row['status']=='CANDIDATE' and int(row['id'])%3!=0:call('PUT',f"analytics/interactions/{row['id']}",json={'status':'CONFIRMED'})

try:
    import imageio_ffmpeg
    video=ROOT/'runtime/demo-preview.mp4';video.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-loglevel','error','-f','lavfi','-i','color=c=0x1677ff:s=640x360:r=12','-t','3','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(video)],check=True,timeout=30,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    call('POST',f'ai/events/{event_ids[0][1]}/video',headers=ai,files={'state':(None,'READY'),'file':('demo.mp4',video.read_bytes(),'video/mp4')})
except Exception as error:
    print('录像生成跳过：',error)

print(json.dumps({'result':'PASS','persons':4,'familyUser':family_user,'zone':1,'events':12,'emotionSamples':42,'trackPoints':18,'interactions':7,'latestEventId':event_ids[0][0]},ensure_ascii=False))

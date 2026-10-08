"""One process owns all cameras. Capture, inference, emotion and HTTP uploading are isolated."""
from __future__ import annotations
import base64
import collections
import json
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from .outbox import Outbox
from .rules import CooldownGate, SustainedRule, point_in_polygon
from .faces import FaceRegistry
from .geofence_monitor import GeofenceMonitor

LOG=logging.getLogger(__name__)
# Emotion labels drawn on the annotated frame. Chinese is rendered via Pillow +
# Microsoft YaHei (OpenCV Hershey fonts have no CJK glyphs); falls back to ASCII
# if Pillow or the font is unavailable. Kept in sync with dashboard_charts.js.
EMOTION_ZH={'neutral':'平静','happy':'开心','sad':'悲伤','angry':'生气','fear':'害怕','surprise':'惊讶','disgust':'厌恶'}
try:
    from PIL import Image,ImageDraw,ImageFont
    _CN_FONT=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',14)
except Exception:
    _CN_FONT=None
def put_cn(img,text,x,y,color=(65,200,130)):
    """Draw a (possibly Chinese) label onto a BGR frame; ASCII fallback."""
    if _CN_FONT is not None:
        import numpy
        h,w=img.shape[:2]
        ov=Image.new('RGBA',(w,h),(0,0,0,0))
        ImageDraw.Draw(ov).text((x,y),text,font=_CN_FONT,fill=color+(255,))
        ov=numpy.asarray(ov);mask=ov[:,:,3]>0
        img[mask]=ov[:,:,:3][:, :, ::-1][mask]
    else:
        import cv2
        cv2.putText(img,text,(x,y),cv2.FONT_HERSHEY_SIMPLEX,.45,color,1)
def wall_time():
    # Windows Python installations may not include IANA tzdata. UTC+8 is fixed for this local deployment.
    from datetime import timezone,timedelta
    return datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None).isoformat(timespec='seconds')

class AlgorithmRuntime:
    def __init__(self,base_url,key,directory,camera_codes=None):
        self.base,self.key=base_url.rstrip('/'),key
        self.root=Path(directory)
        self.camera_codes=set(camera_codes) if camera_codes is not None else None
        self.outbox=Outbox(self.root/'outbox',self.base,key)
        self.faces=FaceRegistry()
        self.cameras={}
        self.lock=threading.RLock()
        # dlib/face_recognition is NOT thread-safe; a native crash (0xc0000005 on
        # Windows) happens when the infer thread and faces.synchronize run
        # face_locations concurrently. Serialize every dlib call with this lock.
        self.dlib_lock=threading.RLock()
        self.stop_event=threading.Event()
        self.thread=None
        self.error=None
        self.emotion_error=None
        self.emotion_queue=queue.Queue(maxsize=8)
        self.emotions={}
        self.recordings=queue.Queue(maxsize=4)
        self.geofence_monitor=GeofenceMonitor(self)

    def request(self,method,path,**kwargs):
        r=requests.request(method,self.base+path,headers={'X-AI-Key':self.key},timeout=(3,15),allow_redirects=False,proxies={'http':'','https':''},**kwargs)
        if not r.ok:raise RuntimeError('算法接口失败 HTTP '+str(r.status_code))
        return r

    def start(self):
        if len(self.key)<32:raise RuntimeError('AI_SERVICE_KEY至少32字符')
        self.outbox.start()
        self.geofence_monitor.start()
        self.thread=threading.Thread(target=self.supervise,name='algorithm-supervisor',daemon=True)
        self.thread.start()

    def supervise(self):
        try:
            import cv2
            import numpy
            import torch
            import face_recognition
            from ultralytics import YOLO
            from deep_sort_realtime.deepsort_tracker import DeepSort
            import yaml
            from .fall_detector import FallConfig
            self.cv2,self.np,self.recognition=cv2,numpy,face_recognition
            self.inference_device=0 if torch.cuda.is_available() else 'cpu'
            self.inference_device_name=torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'
            config=yaml.safe_load((Path(__file__).resolve().parent.parent/'configs/fall_detection.yaml').read_text(encoding='utf8'))
            self.fall_config=FallConfig.from_mapping(config['fall_detector'])
            self.model_path=Path(__file__).resolve().parent.parent/config['model']['path']
            if not self.model_path.is_file():raise FileNotFoundError('缺少本地YOLO权重，拒绝隐式下载')
            self.model_conf=config['model']['confidence']
            self.YOLO,self.DeepSort=YOLO,DeepSort
            threading.Thread(target=self.emotion_loop,name='emotion-worker',daemon=True).start()
            threading.Thread(target=self.video_loop,name='video-worker',daemon=True).start()
        except Exception as exc:
            self.error='算法依赖或模型初始化失败：'+type(exc).__name__+': '+str(exc)[:150]
            LOG.exception('Algorithm bootstrap failed')
            return
        while not self.stop_event.is_set():
            try:
                body=self.request('GET','/api/v1/ai/config').json()
                if body.get('code')!=200:raise RuntimeError('算法配置读取失败')
                config=body['data']
                if self.camera_codes is not None:
                    config['cameras']=[c for c in config['cameras'] if c['cameraCode'] in self.camera_codes]
                self.faces.synchronize(config['persons'],lambda code:self.request('GET',f'/api/v1/ai/persons/{code}/face').content,lambda code,version,state,error:self.request('POST','/api/v1/ai/ack',json={'kind':'person','code':code,'version':version,'state':state,'error':error}),self.dlib_lock)
                configured={c['cameraCode'] for c in config['cameras']}
                with self.lock:
                    for code in set(self.cameras)-configured:
                        if self.cameras[code].stop():self.cameras.pop(code)
                    for c in config['cameras']:
                        code=c['cameraCode']
                        zones=[z for z in config['zones'] if z['cameraCode']==code]
                        old=self.cameras.get(code)
                        if old and not old.stopped.is_set() and old.config==c and old.zones==zones:continue
                        # Heartbeat fields must not force a restart.
                        if old and not old.stopped.is_set() and int(old.config['version'])==int(c['version']) and [(z['zoneCode'],z['version']) for z in old.zones]==[(z['zoneCode'],z['version']) for z in zones]:continue
                        if old and not old.stop():
                            raise RuntimeError('旧摄像头线程尚未退出，拒绝再次打开视频源')
                        if c['enabled']:
                            camera=CameraWorker(self,c,zones)
                            self.cameras[code]=camera
                            camera.start()
                        else:
                            self.cameras.pop(code,None)
                            self.outbox.enqueue('/api/v1/ai/ack',{'kind':'camera','code':code,'version':c['version']})
                            for z in zones:self.outbox.enqueue('/api/v1/ai/ack',{'kind':'zone','code':z['zoneCode'],'version':z['version']})
                self.error=None
            except Exception as exc:
                self.error='配置同步失败，暂停识别防止使用过期人员/区域：'+type(exc).__name__
                with self.lock:
                    for code,cam in list(self.cameras.items()):
                        if cam.stop():self.cameras.pop(code)
            self.stop_event.wait(5)

    def emotion_loop(self):
        weights=Path(os.getenv('DEEPFACE_HOME',str(Path.home())))/'.deepface'/'weights'/'facial_expression_model_weights.h5'
        if not weights.is_file():
            self.emotion_error='缺少情绪模型权重；请算法同学交付已校验文件，不自动下载'
            return
        try:from deepface import DeepFace
        except Exception as exc:
            self.emotion_error='情绪模块不可用：'+type(exc).__name__
            return
        # mtcnn is the slowest detector on CPU and blocks this single worker thread.
        # opencv is ~5-10x faster with acceptable emotion accuracy for sustained-sadness.
        detector=os.getenv('EMOTION_DETECTOR','opencv')
        while not self.stop_event.is_set():
            try:key,person,crop,captured=self.emotion_queue.get(timeout=1)
            except queue.Empty:continue
            if time.monotonic()-captured>5:continue
            try:
                result=DeepFace.analyze(crop,actions=['emotion'],silent=True,enforce_detection=False,detector_backend=detector)[0]
                with self.lock:self.emotions[key]=(captured,person,result['dominant_emotion'],result['emotion'][result['dominant_emotion']]/100)
            except Exception:
                LOG.warning('Emotion inference failed',exc_info=True)

    def video_loop(self):
        while not self.stop_event.is_set():
            try:event_no,frames=self.recordings.get(timeout=1)
            except queue.Empty:continue
            try:
                import imageio_ffmpeg
                import tempfile
                with tempfile.TemporaryDirectory(dir=self.root,prefix='clip-') as tmp:
                    folder=Path(tmp)
                    for i,jpeg in enumerate(frames):(folder/f'{i:05d}.jpg').write_bytes(jpeg)
                    output=folder/'clip.mp4'
                    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-loglevel','error','-framerate','5','-i',str(folder/'%05d.jpg'),'-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(output)],check=True,timeout=60,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    self.outbox.enqueue(f'/api/v1/ai/events/{event_no}/video',{'state':'READY'},output.read_bytes(),'file','.mp4')
            except Exception as exc:
                self.outbox.enqueue(f'/api/v1/ai/events/{event_no}/video',{'state':'FAILED','error':type(exc).__name__})

    def frame(self,code):
        with self.lock:camera=self.cameras.get(code)
        if not camera:return {'frame':None,'status':'ERROR' if self.error else 'DISABLED','message':self.error or '摄像头未启用'}
        with camera.lock:
            fresh=camera.last_frame_time and time.monotonic()-camera.last_frame_time<3
            image=camera.annotated if camera.annotated and time.monotonic()-camera.annotated_time<1 else camera.jpeg
            return {'frame':base64.b64encode(image).decode() if image and fresh else None,'status':'ERROR' if camera.inference_error else ('ONLINE' if fresh else camera.status),'message':camera.inference_error or camera.error}

    def health(self):
        with self.lock:
            now=time.monotonic();cameras={}
            for code,camera in self.cameras.items():
                inference_age=None if not camera.last_inference_time else max(0,now-camera.last_inference_time)
                inference=('ERROR' if camera.inference_error else ('LOADING' if not camera.inference_ready else ('RUNNING' if inference_age is not None and inference_age<3 else 'STALLED')))
                cameras[code]={'capture':camera.status,'inference':inference,'device':getattr(self,'inference_device_name',None),'inferenceFps':round(camera.inference_fps,1),'inferenceAgeSeconds':None if inference_age is None else round(inference_age,2),'error':camera.inference_error or camera.error}
        degraded=self.error or self.emotion_error or any(v['inference'] in ('ERROR','STALLED') for v in cameras.values())
        return {'status':'ERROR' if degraded else 'RUNNING','message':self.error,'emotionError':self.emotion_error,'cameras':cameras,'outbox':self.outbox.health()}

    def stop(self):
        self.stop_event.set()
        with self.lock:
            for c in self.cameras.values():c.stop()
        self.geofence_monitor.stop()
        self.outbox.stop()

class CameraWorker:
    def __init__(self,runtime,config,zones):
        self.r,self.config,self.zones=runtime,config,zones
        self.code=config['cameraCode']
        self.options=json.loads(config['configJson'])
        self.lock=threading.RLock()
        self.stopped=threading.Event()
        self.frame_data=None
        self.jpeg=None
        self.annotated=None
        self.annotated_time=0
        self.last_frame_time=0
        self.last_inference_time=0
        self.inference_fps=0.0
        self.status='OFFLINE'
        self.error=None
        self.inference_error=None
        self.inference_ready=False
        self.buffer=collections.deque(maxlen=50)
        self.last_record_sample=0
        self.clips={}
        self.capture_thread=self.infer_thread=None
        self.generation=uuid.uuid4().hex[:8]
        self.last_sound=0

    def start(self):
        self.capture_thread=threading.Thread(target=self.capture,name='capture-'+self.code,daemon=True)
        self.infer_thread=threading.Thread(target=self.infer,name='infer-'+self.code,daemon=True)
        self.capture_thread.start();self.infer_thread.start()

    def stop(self):
        self.stopped.set()
        self.status='OFFLINE'
        for thread in (self.capture_thread,self.infer_thread):
            if thread and thread!=threading.current_thread():thread.join(timeout=3)
        with self.lock:
            self.frame_data=self.jpeg=self.annotated=None
            for no in self.clips:self.r.outbox.enqueue(f'/api/v1/ai/events/{no}/video',{'state':'FAILED','error':'采集终止，录像不完整'})
            self.clips.clear()
        return not any(t and t.is_alive() for t in (self.capture_thread,self.infer_thread))

    def capture(self):
        cv2=self.r.cv2
        source=self.config['captureSource']
        source=int(source) if str(source).isdigit() else source
        cap=None
        last_heartbeat=0
        try:
            while not self.stopped.is_set():
                cycle_started=time.monotonic()
                if cap is None or not cap.isOpened():
                    if cap:cap.release()
                    cap=cv2.VideoCapture(source,cv2.CAP_DSHOW if isinstance(source,int) and os.name=='nt' else cv2.CAP_ANY)
                ok,frame=cap.read()
                if self.stopped.is_set():break
                now=time.monotonic()
                if ok:
                    frame=cv2.resize(frame,(640,480))
                    encoded,jpeg=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,75])
                    if encoded:
                        raw=jpeg.tobytes()
                        with self.lock:
                            self.frame_data=frame;self.jpeg=raw;self.last_frame_time=now;self.status='ONLINE';self.error=None
                            if now-self.last_record_sample>=.2:
                                self.last_record_sample=now
                                self.buffer.append(raw)
                                for no,clip in list(self.clips.items()):
                                    clip['frames'].append(raw)
                                    if now>=clip['end']:
                                        try:self.r.recordings.put_nowait((no,clip['frames']))
                                        except queue.Full:self.r.outbox.enqueue(f'/api/v1/ai/events/{no}/video',{'state':'FAILED','error':'录像处理队列已满'})
                                        del self.clips[no]
                else:
                    with self.lock:self.frame_data=self.jpeg=self.annotated=None;self.status='OFFLINE';self.error='无法读取视频源'
                    cap.release();cap=None
                if now-last_heartbeat>=5:
                    self.r.outbox.enqueue('/api/v1/ai/heartbeat',{'cameraCode':self.code,'status':'ERROR' if self.inference_error else self.status,'error':self.inference_error or self.error})
                    last_heartbeat=now
                target_fps=float(self.options.get('captureFps',30))
                self.stopped.wait(max(0,1/target_fps-(time.monotonic()-cycle_started)) if ok else 2)
        except Exception as exc:
            self.status='ERROR';self.error=type(exc).__name__
        finally:
            if cap:cap.release()
            self.r.outbox.enqueue('/api/v1/ai/heartbeat',{'cameraCode':self.code,'status':'OFFLINE','error':'采集停止'})

    def emit(self,kind,person=None,track=None,zone=None,description=None):
        no=str(uuid.uuid4())
        data={'eventNo':no,'eventType':kind,'cameraCode':self.code,'eventTime':wall_time(),'description':description or kind+' 检测规则触发'}
        if person:data['personCode']=person['personCode']
        if track:data['trackId']=str(track)
        if zone:data['zoneCode']=zone
        with self.lock:
            accepted=self.r.outbox.enqueue('/api/v1/ai/events',data,self.jpeg,'snapshot')
            if accepted:
                if len(self.clips)<4:self.clips[no]={'frames':list(self.buffer),'end':time.monotonic()+20}
                else:self.r.outbox.enqueue(f'/api/v1/ai/events/{no}/video',{'state':'FAILED','error':'同时录像事件过多'})
                if self.options.get('soundEnabled',False) and os.name=='nt' and time.monotonic()-self.last_sound>5:
                    try:
                        import winsound
                        winsound.PlaySound('SystemExclamation',winsound.SND_ALIAS|winsound.SND_ASYNC)
                        self.last_sound=time.monotonic()
                    except Exception:LOG.warning('现场声音播放失败')

    def infer(self):
        try:
            from .fall_detector import TemporalFallDetector,compute_pose_features
            from .pose_utils import match_boxes_one_to_one
            cv2,np=self.r.cv2,self.r.np
            model=self.r.YOLO(str(self.r.model_path))
            # DeepSORT association with local color-histogram embeddings; no silent model download.
            # This is a baseline association feature, not a claimed trained cross-camera re-ID model.
            tracker=self.r.DeepSort(max_age=20,n_init=2,embedder=None)
            self.inference_ready=True
            states={};last_frame=0;interactions={}
            # Throttle inference: capture runs at captureFps, but running YOLO on every
            # captured frame saturates the CPU and starves the web process in the same
            # container. Default 10fps is enough for fall/stranger/danger rules.
            inference_interval=1/max(float(self.options.get('inferenceFps',10)),1)
            face_interval=float(self.options.get('faceInterval',5))
            emotion_interval=float(self.options.get('emotionInterval',5))
            self.r.outbox.enqueue('/api/v1/ai/ack',{'kind':'camera','code':self.code,'version':self.config['version']})
            for zone in self.zones:self.r.outbox.enqueue('/api/v1/ai/ack',{'kind':'zone','code':zone['zoneCode'],'version':zone['version']})
            while not self.stopped.is_set():
                if self.last_inference_time and time.monotonic()-self.last_inference_time<inference_interval:
                    self.stopped.wait(inference_interval-(time.monotonic()-self.last_inference_time));continue
                with self.lock:
                    stamp=self.last_frame_time
                    frame=None if self.frame_data is None else self.frame_data.copy()
                if frame is None or stamp==last_frame:
                    self.stopped.wait(.1);continue
                last_frame=stamp
                result=model.predict(frame,conf=self.r.model_conf,device=self.r.inference_device,verbose=False)[0]
                completed=time.monotonic()
                if self.last_inference_time:
                    instant=1/max(completed-self.last_inference_time,1e-6)
                    self.inference_fps=instant if not self.inference_fps else .85*self.inference_fps+.15*instant
                self.last_inference_time=completed
                boxes=result.boxes.xyxy.cpu().numpy() if result.boxes is not None else []
                detections=[];embeds=[]
                for box_index,box in enumerate(boxes):
                    x1,y1,x2,y2=box.astype(int);x1,y1=max(0,x1),max(0,y1);x2,y2=min(640,x2),min(480,y2)
                    crop=frame[y1:y2,x1:x2]
                    if not crop.size:continue
                    hist=cv2.calcHist([cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)],[0,1],None,[8,8],[0,180,0,256]).flatten()
                    hist=hist/(np.linalg.norm(hist)+1e-9)
                    detections.append(([x1,y1,x2-x1,y2-y1],float(result.boxes.conf[box_index]),'person'));embeds.append(hist)
                tracks=tracker.update_tracks(detections,embeds=embeds)
                active_tracks=[track for track in tracks if track.is_confirmed() and track.time_since_update==0]
                track_boxes=[np.asarray(track.to_ltrb(),dtype=float) for track in active_tracks]
                pose_assignments=match_boxes_one_to_one(track_boxes,boxes,.3)
                now=time.monotonic();visible=[];annotated=frame.copy()
                for track_index,track in enumerate(active_tracks):
                    tid=self.generation+'-'+track.track_id
                    x1,y1,x2,y2=map(int,track.to_ltrb())
                    x1,y1=max(0,x1),max(0,y1);x2,y2=min(640,x2),min(480,y2)
                    state=states.setdefault(tid,{'fall':TemporalFallDetector(self.r.fall_config),'fallGate':CooldownGate(float(self.options.get('fallCooldownSeconds',10))),'sad':SustainedRule(float(self.options.get('sadSeconds',30)),2,float(self.options.get('missingSeconds',5))),'stranger':SustainedRule(1,2,5),'zones':{},'lastFace':0,'person':None,'lastSample':0,'lastEmotion':0,'lastEmotionSample':0,'lastSeen':now})
                    if now-state['lastSeen']>2:state['fall'].reset()
                    state['lastSeen']=now
                    features=None
                    index=pose_assignments.get(track_index)
                    if index is not None and result.keypoints is not None:
                        features=compute_pose_features(result.keypoints.xy[index].cpu().numpy(),result.keypoints.conf[index].cpu().numpy(),boxes[index],480,self.r.fall_config.min_keypoint_confidence)
                    fall=state['fall'].update(features,now)
                    if self.options.get('fallEnabled',True) and fall.event_started and state['fallGate'].allow(now):
                        evidence=(f"姿态规则触发：状态={fall.state.value}，"
                                  f"髋部下降速度={fall.downward_velocity:.3f}/秒，"
                                  f"倒地姿态={'是' if fall.is_lying else '否'}，依据={fall.reason}")
                        self.emit('FALL',state['person'],tid,description=evidence)
                    if now-state['lastFace']>=face_interval:
                        state['lastFace']=now
                        # dlib face_locations/encodings segfault (0xc0000005) on tiny or
                        # degenerate ROIs on Windows. Normalize the box ordering and enforce
                        # a minimum size before calling into dlib.
                        l,b,rr,tt=max(0,min(x1,x2)),min(640,max(x1,x2)),max(0,min(y1,y2)),min(480,max(y1,y2))
                        if b>l+20 and tt>rr+20:
                            roi=frame[rr:tt,l:b]
                            if roi.size:
                                with self.r.dlib_lock:
                                    locs=self.r.recognition.face_locations(cv2.cvtColor(roi,cv2.COLOR_BGR2RGB))
                                    encs=self.r.recognition.face_encodings(cv2.cvtColor(roi,cv2.COLOR_BGR2RGB),locs) if locs else []
                            else:
                                roi=None;locs=[];encs=[]
                        else:
                            roi=None;locs=[];encs=[]
                        state['person']=self.r.faces.match(encs[0]) if len(encs)==1 else None
                        if self.options.get('strangerEnabled',True) and state['stranger'].update(len(encs)==1 and state['person'] is None,now):self.emit('STRANGER',track=tid)
                        if self.options.get('emotionEnabled',True) and locs and state['person'] and now-state.get('lastEmotionSample',0)>=emotion_interval:
                            state['lastEmotionSample']=now
                            top,right,bottom,left=locs[0];face=roi[top:bottom,left:right].copy()
                            if face.size:
                                try:self.r.emotion_queue.put_nowait(((self.code,tid),state['person'],face,now))
                                except queue.Full:pass
                    person=state['person']
                    cv2.rectangle(annotated,(x1,y1),(x2,y2),(65,200,130),2)
                    cv2.putText(annotated,(person['personCode'] if person else 'UNKNOWN')+' #'+tid,(x1,max(18,y1-5)),cv2.FONT_HERSHEY_SIMPLEX,.45,(65,200,130),1)
                    with self.r.lock:emotion=self.r.emotions.get((self.code,tid))
                    if person and emotion and now-emotion[0]<5 and emotion[1] and emotion[1]['personCode']==person['personCode']:
                        put_cn(annotated,f"{EMOTION_ZH.get(emotion[2],emotion[2])} {int(emotion[3]*100)}%",x1,max(34,y1-5+16))
                    if emotion and emotion[0]>state['lastEmotion'] and now-emotion[0]<5:
                        state['lastEmotion']=emotion[0]
                        if person and emotion[1]['personCode']==person['personCode']:
                            if state['sad'].update(emotion[2]=='sad',now):self.emit('EMOTION_ABNORMAL',person,tid)
                            self.r.outbox.enqueue('/api/v1/ai/samples',{'kind':'emotion','sampleNo':str(uuid.uuid4()),'cameraCode':self.code,'personCode':person['personCode'],'emotion':emotion[2],'score':emotion[3],'sampleTime':wall_time()})
                    state['sad'].expire_missing(now)
                    px,py=(x1+x2)/1280,(y1+y2)/2/480
                    for z in self.zones:
                        if not z['enabled'] or not self.options.get('dangerEnabled',True):continue
                        rule=state['zones'].setdefault(z['zoneCode'],SustainedRule(float(z['enterSeconds']),float(z['exitSeconds']),5))
                        if rule.update(point_in_polygon(px,py,json.loads(z['pointsJson'])),now):self.emit('DANGER_ZONE',person,tid,z['zoneCode'])
                    if now-state['lastSample']>=1:
                        data={'kind':'track','sampleNo':str(uuid.uuid4()),'cameraCode':self.code,'trackId':tid,'sampleTime':wall_time(),'x':min(1,max(0,px)),'y':min(1,max(0,py))}
                        if person:data['personCode']=person['personCode']
                        self.r.outbox.enqueue('/api/v1/ai/samples',data);state['lastSample']=now
                    if person:visible.append((person,(x1+x2)/2,(y1+y2)/2,max(1,x2-x1)))
                for elder,ex,ey,ew in visible:
                    if elder['personType']!='ELDER':continue
                    for worker,wx,wy,ww in visible:
                        if worker['personType']!='WORKER' or ((ex-wx)**2+(ey-wy)**2)**.5>1.5*(ew+ww)/2:continue
                        pair=(elder['personCode'],worker['personCode']);entry=interactions.setdefault(pair,{'first':now,'last':now,'start':wall_time()});entry['last']=now;entry['end']=wall_time()
                for pair,entry in list(interactions.items()):
                    if now-entry['last']>5:
                        if entry['last']-entry['first']>=10:self.r.outbox.enqueue('/api/v1/ai/interactions',{'recordNo':str(uuid.uuid4()),'cameraCode':self.code,'elderCode':pair[0],'workerCode':pair[1],'startTime':entry['start'],'endTime':entry['end']})
                        del interactions[pair]
                for tid in list(states):
                    if now-states[tid]['lastSeen']>10:
                        del states[tid]
                        with self.r.lock:self.r.emotions.pop((self.code,tid),None)
                encoded,jpeg=cv2.imencode('.jpg',annotated,[cv2.IMWRITE_JPEG_QUALITY,75])
                if encoded:
                    with self.lock:self.annotated=jpeg.tobytes();self.annotated_time=time.monotonic()
                self.stopped.wait(.02)
        except Exception as exc:
            self.inference_error='识别线程异常：'+type(exc).__name__+': '+str(exc)[:120]
            self.status='ERROR'
            LOG.exception('Inference failed for %s',self.code)

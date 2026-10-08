"""Runs real YOLO and tracking on two synthetic video files, never device 0.

This verifies the pipeline, NOT recognition accuracy. Test cameras are disabled
afterwards, and all generated data is explicitly labelled TEST.
"""
import io
import json
import os
import sys
import time
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env.local')
import cv2
import numpy as np
import requests
from algorithm.runtime import AlgorithmRuntime

http=requests.Session();http.trust_env=False
base=os.environ['JAVA_BASE_URL'];key=os.environ['AI_SERVICE_KEY']
def api(method,path,**kw):
    r=http.request(method,base+'/api/v1/'+path,timeout=20,**kw)
    assert r.ok,(r.status_code,r.text[:200])
    body=r.json();assert body['code']==200,body
    return body['data']
token=api('POST','auth/login',json={'username':'admin','password':os.environ['BOOTSTRAP_ADMIN_PASSWORD']})['token']
http.headers['Authorization']='Bearer '+token
tag=uuid.uuid4().hex[:8]
directory=ROOT/'runtime'/'test-videos';directory.mkdir(parents=True,exist_ok=True)
cameras=[];runtime=None
try:
    for index in (1,2):
        code=f'TEST-{tag}-{index}';path=directory/(code+'.avi')
        writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),5,(640,480))
        assert writer.isOpened(),'Cannot encode synthetic video'
        for frame_number in range(225):
            frame=np.zeros((480,640,3),dtype=np.uint8);frame[:]=(20+index*20,40,60)
            cv2.putText(frame,f'TEST CAMERA {index} FRAME {frame_number}',(35,200),cv2.FONT_HERSHEY_SIMPLEX,.8,(240,240,240),2)
            writer.write(frame)
        writer.release()
        camera={'cameraCode':code,'cameraName':'TEST 合成视频 '+str(index),'location':'TEST 非真实监控','captureSource':str(path),'enabled':True,'config':{'fallEnabled':True,'emotionEnabled':False,'strangerEnabled':False,'dangerEnabled':True}}
        api('POST','cameras',json=camera);api('PUT','cameras/'+code,json=camera);cameras.append(camera)
    runtime=AlgorithmRuntime(base,key,ROOT/'runtime'/('ai-test-'+tag),[c['cameraCode'] for c in cameras])
    runtime.start()
    deadline=time.monotonic()+65
    while time.monotonic()<deadline:
        with runtime.lock:
            ready=len(runtime.cameras)==2 and all(c.last_inference_time for c in runtime.cameras.values())
        if ready:break
        if runtime.error and not runtime.cameras:raise RuntimeError(runtime.error)
        time.sleep(.5)
    assert ready,json.dumps(runtime.health(),ensure_ascii=False)
    assert all(runtime.frame(c['cameraCode'])['frame'] for c in cameras)
    print(json.dumps({'result':'PASS','scope':'two synthetic videos, actual YOLO/DeepSORT, no physical camera','cameras':[c['cameraCode'] for c in cameras],'health':runtime.health()},ensure_ascii=False),flush=True)
finally:
    if runtime:runtime.stop()
    for camera in cameras:
        camera['enabled']=False
        api('PUT','cameras/'+camera['cameraCode'],json=camera)

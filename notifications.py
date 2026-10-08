"""Optional Web Push transport. Java owns subscriptions, authorization and jobs.

Disabled by default. Delivery is at-least-once and may be delayed by the browser.
No person names, images, locations or medical details enter push payloads.
"""
import json
import logging
import threading
import requests

class PushWorker:
    def __init__(self,base_url,key,private_key,subject):
        if len(key)<32 or not private_key or not subject:
            raise ValueError('通知需要AI_SERVICE_KEY、VAPID_PRIVATE_KEY和VAPID_SUBJECT')
        self.base=base_url.rstrip('/')
        self.key,self.private_key,self.subject=key,private_key,subject
        self.stopped=threading.Event()
        self.error=None
        self.thread=None

    def request(self,method,path,**kw):
        r=requests.request(method,self.base+path,headers={'X-AI-Key':self.key},timeout=(3,10),proxies={'http':'','https':''},**kw)
        r.raise_for_status()
        body=r.json()
        if body.get('code')!=200:raise RuntimeError('通知任务接口失败')
        return body.get('data')

    def process(self):
        from pywebpush import webpush,WebPushException
        for job in self.request('GET','/api/v1/ai/notification-jobs'):
            if self.stopped.is_set():return
            state,error='SENT',None
            try:
                webpush(subscription_info=json.loads(job['subscriptionJson']),
                        data=json.dumps({'title':'视界无疆','body':'有新的监护消息，请登录平台查看。','tag':'event-'+str(job['eventId'])},ensure_ascii=False),
                        vapid_private_key=self.private_key,vapid_claims={'sub':self.subject},ttl=300,timeout=10)
            except WebPushException as exc:
                status=getattr(exc.response,'status_code',0)
                state='FAILED' if status in (400,401,403,404,410) or int(job['attempts'])>=4 else 'RETRY'
                error='推送服务 HTTP '+str(status)
            except Exception as exc:
                state='FAILED' if int(job['attempts'])>=4 else 'RETRY'
                error=type(exc).__name__
            self.request('POST',f'/api/v1/ai/notification-jobs/{job["id"]}',json={'state':state,'error':error})

    def run(self):
        while not self.stopped.is_set():
            try:self.process();self.error=None
            except requests.HTTPError as exc:
                self.error='通知任务认证或后端故障'
                if exc.response is not None and exc.response.status_code in (401,403):return
            except Exception as exc:
                self.error='通知发送器故障：'+type(exc).__name__
                logging.getLogger(__name__).warning(self.error)
            self.stopped.wait(60)

    def start(self):
        self.thread=threading.Thread(target=self.run,name='web-push-worker',daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()


"""Durable bounded upload queue. Only successful HTTP + business responses remove data."""
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
import requests

class Outbox:
    def __init__(self, directory, base_url, key, max_items=2000, max_bytes=512*1024*1024):
        self.root=Path(directory).resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        self.database=self.root/'outbox.sqlite'
        self.base=base_url.rstrip('/')
        self.key=key
        self.max_items,self.max_bytes=max_items,max_bytes
        self.lock=threading.RLock()
        self.stop_event=threading.Event()
        self.thread=None
        self.error=None
        self.dropped=0
        self.auth_blocked=False
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,path TEXT NOT NULL,payload TEXT NOT NULL,file TEXT,file_field TEXT,state TEXT NOT NULL DEFAULT "PENDING",attempts INTEGER NOT NULL DEFAULT 0,due REAL NOT NULL DEFAULT 0,error TEXT)')

    def connect(self):
        db=sqlite3.connect(self.database,timeout=10)
        db.row_factory=sqlite3.Row
        return db

    def enqueue(self,path,payload,content=None,file_field=None,suffix='.jpg'):
        if not path.startswith('/api/v1/ai/') or '..' in path:
            raise ValueError('Invalid algorithm endpoint')
        with self.lock,self.connect() as db:
            count=db.execute('SELECT count(*) FROM jobs').fetchone()[0]
            size=sum(p.stat().st_size for p in self.root.iterdir() if p.is_file())
            if count>=self.max_items or size+len(content or b'')>self.max_bytes:
                self.dropped+=1
                self.error='待发送队列容量达到上限，可能丢失数据；请检查网络并清理失败记录'
                return False
            key=str(uuid.uuid4())
            filename=None
            if content is not None:
                filename=key+suffix
                try:(self.root/filename).write_bytes(content)
                except OSError:
                    self.dropped+=1
                    self.error='截图写入失败，磁盘可能已满；事件未被保存'
                    (self.root/filename).unlink(missing_ok=True)
                    return False
            try:
                db.execute('INSERT INTO jobs(id,path,payload,file,file_field) VALUES(?,?,?,?,?)',(key,path,json.dumps(payload,ensure_ascii=False),filename,file_field))
            except Exception:
                if filename:(self.root/filename).unlink(missing_ok=True)
                self.error='持久化队列写入失败，事件可能丢失'
                self.dropped+=1
                return False
        return True

    def process_one(self):
        if self.auth_blocked:return False
        with self.connect() as db:
            job=db.execute('SELECT * FROM jobs WHERE state="PENDING" AND due<=? ORDER BY CASE WHEN path="/api/v1/ai/events" THEN 0 WHEN path LIKE "%/video" THEN 2 ELSE 1 END,rowid LIMIT 1',(time.time(),)).fetchone()
        if not job:return False
        payload=json.loads(job['payload'])
        stream=None
        try:
            if job['file']:
                stream=(self.root/job['file']).open('rb')
                files={job['file_field']:(job['file'],stream,'video/mp4' if job['file'].endswith('.mp4') else 'image/jpeg')}
                kwargs={'data':payload,'files':files}
            elif job['path']=='/api/v1/ai/events' or job['path'].endswith('/video'):
                kwargs={'files':{k:(None,str(v)) for k,v in payload.items() if v is not None}}
            else:
                kwargs={'json':payload}
            response=requests.post(self.base+job['path'],headers={'X-AI-Key':self.key},timeout=(3,20),allow_redirects=False,proxies={'http':'','https':''},**kwargs)
            body=response.json()
            if response.ok and body.get('code')==200:
                with self.connect() as db:db.execute('DELETE FROM jobs WHERE id=?',(job['id'],))
                if stream:stream.close()
                if job['file']:(self.root/job['file']).unlink(missing_ok=True)
                return True
            if response.status_code in (401,403):
                self.auth_blocked=True
                self.error='算法认证失败，发送队列已暂停；修复凭据后重启'
                state='BLOCKED'
            elif 400<=response.status_code<500 and not(response.status_code==429 or job['path'].endswith('/video') and response.status_code==404):
                state='FAILED'
            else:state='PENDING'
            message=body.get('message','上报失败')
        except (requests.RequestException,ValueError,OSError) as exc:
            state='PENDING'
            message='网络或文件读取失败：'+type(exc).__name__
        finally:
            if stream:stream.close()
        with self.connect() as db:
            if state=='BLOCKED':db.execute('UPDATE jobs SET state="BLOCKED" WHERE state="PENDING"')
            db.execute('UPDATE jobs SET state=?,attempts=attempts+1,due=?,error=? WHERE id=?',(state,time.time()+min(60,2**min(job['attempts']+1,6)),message,job['id']))
        return True

    def start(self):
        if self.thread and self.thread.is_alive():return
        # A restart after credential repair retries blocked records with the same eventNo.
        with self.connect() as db:db.execute('UPDATE jobs SET state="PENDING",due=0 WHERE state="BLOCKED"')
        self.auth_blocked=False
        self.stop_event.clear()
        self.thread=threading.Thread(target=self._loop,daemon=True,name='event-outbox')
        self.thread.start()

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                processed=self.process_one()
            except Exception as exc:self.error='发送线程故障：'+type(exc).__name__
            # Drain independent camera samples fast enough; sleep only when idle.
            self.stop_event.wait(.02 if 'processed' in locals() and processed else .25)

    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=2)

    def health(self):
        with self.connect() as db:counts={r[0]:r[1] for r in db.execute('SELECT state,count(*) FROM jobs GROUP BY state')}
        return {'queue':counts,'error':self.error,'dropped':self.dropped}

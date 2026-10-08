import json
from algorithm.rules import CooldownGate,SustainedRule,point_in_polygon
from algorithm.outbox import Outbox

def test_sad_requires_duration_and_resets_after_missing():
    rule=SustainedRule(30,2,5)
    assert not any(rule.update(True,t) for t in range(0,30,2))
    assert rule.update(True,30)
    assert not rule.update(True,32)
    assert not rule.update(True,50)
    assert not rule.active

def test_missing_observation_expires_without_a_new_emotion_result():
    rule=SustainedRule(30,2,5)
    rule.update(True,0);rule.update(True,4)
    assert rule.started==0
    assert rule.expire_missing(10)
    assert rule.started is None and not rule.active

def test_cooldown_gate_suppresses_duplicate_events_per_track():
    gate=CooldownGate(10)
    assert gate.allow(100)
    assert not gate.allow(109.9)
    assert gate.allow(110)

def test_zone_exit_debounce_and_polygon():
    rule=SustainedRule(1,2,5)
    assert not rule.update(True,0)
    assert rule.update(True,1)
    rule.update(False,2)
    assert not rule.update(True,3)
    rule.update(False,4);rule.update(False,6)
    assert not rule.update(True,7)
    assert rule.update(True,8)
    assert point_in_polygon(.5,.5,[(0,0),(1,0),(1,1),(0,1)])
    assert not point_in_polygon(2,2,[(0,0),(1,0),(1,1),(0,1)])

def test_durable_queue_keeps_event_number_and_removes_on_success(tmp_path,monkeypatch):
    queue=Outbox(tmp_path,'http://local','test',max_items=2)
    payload={'eventNo':'same-id','eventType':'FALL'}
    assert queue.enqueue('/api/v1/ai/events',payload,b'jpeg','snapshot')
    queue=Outbox(tmp_path,'http://local','test')
    seen=[]
    class Response:
        ok=True
        def json(self):return {'code':200,'data':{'id':'1'}}
    def send(url,**kw):seen.append(kw['data']);return Response()
    monkeypatch.setattr('algorithm.outbox.requests.post',send)
    queue.process_one()
    assert seen[0]['eventNo']=='same-id'
    assert queue.health()['queue']=={}
    assert not list(tmp_path.glob('*.jpg'))

def test_auth_failure_pauses_and_capacity_is_bounded(tmp_path,monkeypatch):
    q=Outbox(tmp_path,'http://local','test',max_items=1)
    assert q.enqueue('/api/v1/ai/events',{'eventNo':'1'})
    assert not q.enqueue('/api/v1/ai/events',{'eventNo':'2'})
    class Response:
        ok=False
        status_code=401
        def json(self):return {'code':401,'message':'bad key'}
    monkeypatch.setattr('algorithm.outbox.requests.post',lambda *a,**k:Response())
    q.process_one()
    assert q.health()['queue']=={'BLOCKED':1}
    assert q.health()['dropped']==1

def test_network_retry_preserves_uuid_and_disk_failure_is_visible(tmp_path,monkeypatch):
    import requests
    from pathlib import Path
    q=Outbox(tmp_path,'http://local','test')
    assert q.enqueue('/api/v1/ai/events',{'eventNo':'keep-original'})
    def timeout(*a,**k):raise requests.Timeout()
    monkeypatch.setattr('algorithm.outbox.requests.post',timeout)
    q.process_one()
    with q.connect() as db:
        job=db.execute('SELECT * FROM jobs').fetchone()
        assert job['state']=='PENDING' and job['attempts']==1
        assert json.loads(job['payload'])['eventNo']=='keep-original'
    def full(*args):raise OSError('disk full')
    monkeypatch.setattr(Path,'write_bytes',full)
    assert not q.enqueue('/api/v1/ai/events',{'eventNo':'new'},b'photo','snapshot')
    assert q.health()['dropped']==1 and q.health()['error']

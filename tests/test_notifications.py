import json,sys
from types import SimpleNamespace
from notifications import PushWorker

def test_push_contains_no_sensitive_details_and_stops_after_fifth_failure(monkeypatch):
    class PushFailure(Exception):
        response=SimpleNamespace(status_code=503)
    sent=[]
    def fail(**kw):sent.append(kw);raise PushFailure()
    monkeypatch.setitem(sys.modules,'pywebpush',SimpleNamespace(webpush=fail,WebPushException=PushFailure))
    worker=PushWorker('http://local','x'*32,'local-private.pem','mailto:admin@example.invalid')
    updates=[]
    def request(method,path,**kw):
        if method=='GET':return [{'id':'7','eventId':'9','attempts':4,'subscriptionJson':json.dumps({'endpoint':'https://fcm.googleapis.com/test'})}]
        updates.append(kw['json'])
    worker.request=request;worker.process()
    assert updates==[{'state':'FAILED','error':'推送服务 HTTP 503'}]
    payload=json.loads(sent[0]['data'])
    assert set(payload)=={'title','body','tag'}
    assert 'snapshot' not in sent[0]['data'] and 'personCode' not in sent[0]['data']

import sys
import time
import pytest
from webapp import create_app, BackendError

class FakeBackend:
    role='ADMIN'
    failure=None
    calls=[]
    def data(self,method,path,token=None,**kw):
        if self.failure:raise self.failure
        self.calls.append((method,path,token,kw))
        user={'id':'1','username':'real','realName':'管理员','role':self.role}
        if path.endswith('/login'):return {'token':'server-side-secret','expiresAt':time.time()+7200,'user':user}
        if path=='/health':return {'status':'UP'}
        return user
    def call(self,method,path,token=None,**kw):
        if self.failure:raise self.failure
        self.calls.append((method,path,token,kw))
        return type('FakeResponse',(),{
            'status_code':200,
            'content':b'{"code":200,"data":{}}',
            'headers':{'Content-Type':'application/json'},
            'close':lambda self:None,
            'iter_content':lambda self,chunk_size=65536:iter((self.content,)),
        })()

@pytest.fixture
def web(tmp_path):
    backend=FakeBackend()
    app=create_app({'TESTING':True,'SECRET_KEY':'x'*40,'BACKEND':backend,'SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(tmp_path/'session.sqlite')})
    return app,app.test_client(),backend

def login(client):
    page=client.get('/login')
    csrf=__import__('re').search(rb'name="csrf_token" value="([^"]+)"',page.data).group(1).decode()
    return client.post('/login',data={'username':'real','password':'secret','role':'family','csrf_token':csrf})

def test_ai_disabled_does_not_import_models(web):
    app,client,_=web
    assert client.get('/login').status_code==200
    assert app.extensions['ai_runtime'] is None
    assert 'algorithm.runtime' not in sys.modules
    assert 'ultralytics' not in sys.modules

def test_csrf_and_real_identity(web):
    _,client,_=web
    assert client.post('/login',data={'username':'admin'}).status_code==403
    assert login(client).status_code==302
    with client.session_transaction() as s:assert s['role']=='ADMIN'
    assert client.get('/dashboard').status_code==200
    assert b'server-side-secret' not in client.get('/dashboard').data
    assert client.post('/logout').status_code==403

def test_stale_browser_form_gets_fresh_login_instead_of_json(web):
    _,client,_=web
    response=client.post('/login',data={'username':'admin'},headers={'Sec-Fetch-Mode':'navigate'},follow_redirects=True)
    assert response.status_code==200
    assert '页面会话已经更新'.encode() in response.data
    assert response.content_type.startswith('text/html')

def test_login_token_survives_another_tab_replacing_session_cookie(web):
    app,first,_=web
    second=app.test_client()
    page=first.get('/login')
    token=__import__('re').search(rb'name="csrf_token" value="([^"]+)"',page.data).group(1).decode()
    second.get('/login')  # Different session, as when multiple tabs race after restart.
    response=second.post('/login',data={'username':'real','password':'secret','csrf_token':token})
    assert response.status_code==302
    assert response.location.endswith('/dashboard')

def test_camera_and_proxy_fail_closed(web):
    _,client,backend=web
    assert client.get('/api/camera_frame').status_code==401
    login(client)
    assert client.get('/api/v1/ai/config').status_code==404
    assert client.get('/api/v1/http://evil.invalid').status_code==404
    backend.role='FAMILY'
    assert client.get('/api/camera_frame').status_code==403
    assert client.get('/setting/users').status_code==403
    backend.failure=BackendError('unavailable',503)
    assert client.get('/api/v1/events/page').status_code==503

def test_sensitive_pages_refresh_current_role(web):
    _,client,backend=web
    login(client)
    backend.calls.clear()
    backend.role='FAMILY'
    assert client.get('/setting/users').status_code==403
    assert backend.calls[-1][1]=='/api/v1/auth/me'
    backend.role='ADMIN'
    assert client.get('/family/index').status_code==403
    assert backend.calls[-1][1]=='/api/v1/auth/me'

def test_token_expiry_clears_session(web):
    _,client,_=web
    login(client)
    with client.session_transaction() as s:s['expires_at']=time.time()-1
    assert client.get('/api/v1/events/page').status_code==401

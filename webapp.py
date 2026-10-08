"""Flask/Jinja gateway. Java owns all business data and permissions."""
from __future__ import annotations
import atexit
import os
import re
import secrets
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse
import requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, redirect, render_template, request, session, stream_with_context
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env.local')
API_PATHS = re.compile(r'^(auth/(me|password|ws-ticket)|events(?:/(?:page|latest|statistics|\d+(?:/(?:status|records|snapshot|video))?))?|statistics/(?:event-count|type-count|event-trend)|persons(?:/[\w-]+(?:/face)?)?|cameras(?:/[\w-]+)?|danger-zones(?:/[\w-]+)?|users(?:/\d+)?|family-bindings|analytics/(?:emotion|tracks|interactions)(?:/\d+)?|alert-rules|notifications/(?:subscriptions|public-key|jobs)|operation-logs)$')
PAGE_ROLES = {'/dashboard': ('dashboard_v2.html','监控看板','dashboard', {'ADMIN','STAFF'}), '/alert/real': ('events.html','实时告警','events',{'ADMIN','STAFF'}), '/alert/history': ('events.html','历史告警','events',{'ADMIN','STAFF'}), '/family/index': ('dashboard_v2.html','家属首页','family',{'FAMILY'}), '/family/alert': ('events.html','关联老人告警','events',{'FAMILY'}), '/monitor/live': ('monitor.html','实时监控与区域绘制','monitor',{'ADMIN','STAFF'}), '/person/list': ('persons.html','人员与人脸库','persons',{'ADMIN','STAFF'}), '/person/upload': ('persons.html','新增人员人脸信息','persons',{'ADMIN'}), '/setting/danger': ('management.html','摄像头与规则','settings',{'ADMIN'}), '/setting/users': ('management.html','用户与家属绑定','users',{'ADMIN'}), '/analysis/emotion': ('analytics.html','情绪趋势','emotion',{'ADMIN','STAFF','FAMILY'}), '/analysis/interaction': ('analytics.html','互动候选复核','interactions',{'ADMIN','STAFF','FAMILY'}), '/analysis/tracks': ('analytics.html','人员轨迹','tracks',{'ADMIN','STAFF'}), '/geofence/map': ('geofence/map.html','电子围栏地图','geofence',{'ADMIN','STAFF'})}
FRESH_AUTH_PATHS = frozenset(PAGE_ROLES) | {'/api/camera_frame', '/api/camera'}

class BackendError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status

class Backend:
    def __init__(self, url):
        parsed = urlparse(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise ValueError('JAVA_BASE_URL must be a fixed service origin')
        self.base = url.rstrip('/')

    def call(self, method, path, token=None, **kwargs):
        headers = kwargs.pop('headers', {})
        if token:
            headers['Authorization'] = 'Bearer ' + token
        try:
            return requests.request(method, self.base + path, headers=headers, timeout=(3, 15), allow_redirects=False, proxies={'http':'','https':''}, **kwargs)
        except requests.Timeout as exc:
            raise BackendError('Java服务请求超时', 504) from exc
        except requests.RequestException as exc:
            raise BackendError('无法连接Java服务，请先启动后端', 503) from exc

    def data(self, method, path, token=None, **kwargs):
        response = self.call(method, path, token, **kwargs)
        try:
            body = response.json()
        except ValueError as exc:
            raise BackendError('后端未返回有效JSON', 502) from exc
        if not response.ok or body.get('code') != 200:
            raise BackendError(body.get('message', '后端请求失败'), response.status_code if response.status_code >= 400 else 502)
        return body.get('data')

class AiClient:
    """HTTP client to the standalone AI service (ai_service.py).

    Keeps the same frame()/health() surface as the old in-process
    AlgorithmRuntime so the routes below do not change. The AI process owns
    all camera/inference threads, so CPU storms stay isolated from waitress.
    """
    def __init__(self, url):
        self.base = url.rstrip('/')

    def _get(self, path, **kwargs):
        try:
            response = requests.get(self.base + path, timeout=(3, 10), proxies={'http':'','https':''}, **kwargs)
        except requests.RequestException:
            return {'frame': None, 'status': 'ERROR', 'message': '算法服务不可用'}
        if not response.ok:
            return {'frame': None, 'status': 'ERROR', 'message': '算法服务 HTTP ' + str(response.status_code)}
        return response.json()

    def frame(self, code):
        return self._get('/frame', params={'cameraCode': code})

    def health(self):
        return self._get('/health')

def create_app(test_config=None):
    app = Flask(__name__)
    runtime = ROOT / 'runtime'
    runtime.mkdir(exist_ok=True)
    app.config.update(SECRET_KEY=os.getenv('FLASK_SECRET_KEY'), SQLALCHEMY_DATABASE_URI='sqlite:///' + (runtime / 'sessions.sqlite').as_posix(), SQLALCHEMY_TRACK_MODIFICATIONS=False, SESSION_TYPE='sqlalchemy', SESSION_PERMANENT=True, PERMANENT_SESSION_LIFETIME=timedelta(hours=2), SESSION_CLEANUP_N_REQUESTS=100, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', 'false').lower() == 'true', MAX_CONTENT_LENGTH=65*1024*1024, JAVA_BASE_URL=os.getenv('JAVA_BASE_URL', 'http://127.0.0.1:8080'), WS_PUBLIC_URL=os.getenv('WS_PUBLIC_URL', 'ws://127.0.0.1:8080/ws/events'), AI_ENABLED=os.getenv('AI_ENABLED', 'false').lower() == 'true', AI_SERVICE_URL=os.getenv('AI_SERVICE_URL', 'http://127.0.0.1:5002'))
    if test_config:
        app.config.update(test_config)
    app.config['SESSION_COOKIE_NAME'] = 'elder_care_session'
    if not app.config['SECRET_KEY'] or len(app.config['SECRET_KEY']) < 32:
        raise RuntimeError('先运行 scripts/setup-local.ps1；FLASK_SECRET_KEY至少32字符')
    app.config['SESSION_SQLALCHEMY'] = SQLAlchemy(app)
    Session(app)
    from sqlalchemy import event as _sa_event
    with app.app_context():
        _session_engine = app.config['SESSION_SQLALCHEMY'].engine
        if _session_engine.dialect.name == 'sqlite':
            @_sa_event.listens_for(_session_engine, 'connect')
            def _sqlite_session_pragmas(dbapi_conn, _record):
                _cur = dbapi_conn.cursor()
                _cur.execute('PRAGMA journal_mode=WAL')
                _cur.execute('PRAGMA busy_timeout=30000')
                _cur.execute('PRAGMA synchronous=NORMAL')
                _cur.close()
    login_csrf = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='elder-care-login-csrf')
    backend = app.config.get('BACKEND') or Backend(app.config['JAVA_BASE_URL'])
    app.extensions['backend'] = backend
    app.extensions['ai_runtime'] = None
    app.extensions['push_worker'] = None

    @app.context_processor
    def context():
        session.setdefault('csrf', secrets.token_urlsafe(32))
        return dict(csrf_token=session['csrf'], login_csrf_token=login_csrf.dumps('login'), app_config={'wsUrl': app.config['WS_PUBLIC_URL']})

    @app.errorhandler(BackendError)
    def backend_error(error):
        if error.status == 401:
            session.clear()
        if request.path.startswith('/api/') or request.path == '/health':
            return jsonify(code=error.status, message=str(error)), error.status
        return render_template('error.html', message=str(error)), error.status

    @app.before_request
    def protect():
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            csrf = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
            if request.endpoint == 'login':
                try:
                    valid_csrf = login_csrf.loads(csrf, max_age=900) == 'login'
                except (BadSignature, SignatureExpired):
                    valid_csrf = False
            else:
                valid_csrf = bool(session.get('csrf')) and secrets.compare_digest(csrf, session['csrf'])
            if not valid_csrf:
                # A form submitted from a tab opened before login/restart is a
                # top-level navigation. Keep CSRF enforcement, but replace the
                # raw JSON response with a fresh login page.
                if request.headers.get('Sec-Fetch-Mode') == 'navigate' and not request.path.startswith('/api/'):
                    session.clear()
                    return redirect('/login?reason=expired')
                if request.path == '/logout' and not session.get('csrf'):
                    session.clear()
                    return redirect('/login?reason=expired')
                return jsonify(code=403, message='页面验证已失效，请刷新重试'), 403
        if request.endpoint in {'static', 'login', 'health', 'service_worker'}:
            return
        if not session.get('token') or session.get('expires_at', 0) <= time.time():
            session.clear()
            if request.path.startswith('/api/'):
                return jsonify(code=401, message='请重新登录'), 401
            return redirect('/login')
        # Cache /auth/me per session for 30s. Every request (including the 500ms camera
        # frame polling) used to make a synchronous round-trip to Java here, which starves
        # the waitress threads when the CPU is saturated by the AI process.
        cached_user = session.get('user')
        fresh_authorization_required = request.path in FRESH_AUTH_PATHS
        if not fresh_authorization_required and isinstance(cached_user, dict) and session.get('auth_checked_at') and time.time() - session['auth_checked_at'] < 30:
            user = cached_user
        else:
            user = backend.data('GET', '/api/v1/auth/me', session['token'])
            session['auth_checked_at'] = time.time()
            if session.get('role') != user['role'] or session.get('username') != user['realName']:
                session.update(user=user, role=user['role'], username=user['realName'])

    @app.after_request
    def headers(response):
        response.headers.update({'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY'})
        if not request.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        error = '页面会话已经更新，请重新输入账号和密码。' if request.args.get('reason') == 'expired' else None
        if request.method == 'POST':
            try:
                data = backend.data('POST', '/api/v1/auth/login', json={'username': request.form.get('username', ''), 'password': request.form.get('password', '')})
                app.session_interface.regenerate(session)
                session.clear()
                session.update(token=data['token'], expires_at=data['expiresAt'], user=data['user'], username=data['user']['realName'], role=data['user']['role'], csrf=secrets.token_urlsafe(32))
                return redirect('/family/index' if session['role'] == 'FAMILY' else '/dashboard')
            except BackendError as exc:
                error = str(exc)
        return render_template('login_v2.html', error=error)

    @app.post('/logout')
    def logout():
        backend.data('POST', '/api/v1/auth/logout', session['token'])
        session.clear()
        return redirect('/login')

    @app.get('/')
    def index():
        return redirect('/family/index' if session.get('role') == 'FAMILY' else '/dashboard')

    def page_view(template, title, page, roles):
        def view():
            if session['role'] not in roles:
                return render_template('error.html', message='无权访问此页面'), 403
            return render_template(template, title=title, page=page)
        return view
    for path, args in PAGE_ROLES.items():
        app.add_url_rule(path, path, page_view(*args))

    @app.route('/api/v1/<path:path>', methods=['GET','POST','PUT','DELETE'])
    def proxy(path):
        if not API_PATHS.fullmatch(path):
            return jsonify(code=404, message='不支持的业务接口'), 404
        h = {k: request.headers[k] for k in ('Range','If-Range') if k in request.headers}
        kw = dict(params=request.args, headers=h)
        if request.files:
            kw['files'] = [(n,(f.filename,f.stream,f.mimetype)) for n,f in request.files.items(multi=True)]
            kw['data'] = request.form
        elif request.is_json:
            kw['json'] = request.get_json()
        elif request.method not in {'GET','HEAD'}:
            kw['data'] = request.get_data()
            h['Content-Type'] = request.content_type or 'application/octet-stream'
        streaming=request.method=='GET' and path.endswith(('/snapshot','/video'))
        result = backend.call(request.method, '/api/v1/' + path, session['token'], stream=streaming, **kw)
        if result.status_code == 401:
            session.clear()
        def chunks():
            try:
                yield from result.iter_content(chunk_size=64*1024)
            finally:
                result.close()
        return Response(stream_with_context(chunks()) if streaming else result.content, status=result.status_code, headers={k:v for k,v in result.headers.items() if k.lower() in {'content-type','content-range','accept-ranges'}})

    @app.get('/api/camera_frame')
    @app.get('/api/camera')
    def frame():
        if session['role'] not in {'ADMIN','STAFF'}:
            return jsonify(code=403, message='家属不可读取公共监控画面'), 403
        ai = app.extensions['ai_runtime']
        return jsonify(ai.frame(request.args.get('cameraCode','CAM001')) if ai else {'frame':None,'status':'DISABLED','message':'算法未启用'})

    @app.get('/health')
    def health():
        try:
            state = backend.data('GET','/health')
        except BackendError:
            state = {'status':'DOWN'}
        ai = app.extensions['ai_runtime']
        push=app.extensions['push_worker']
        return jsonify(web='UP',backend=state,algorithm=ai.health() if ai else {'status':'DISABLED'},notifications={'status':('ERROR' if push.error else 'RUNNING'),'message':push.error} if push else {'status':'DISABLED'}), (200 if state['status']=='UP' else 503)

    @app.get('/service-worker.js')
    def service_worker():
        return app.send_static_file('js/service-worker.js')
    return app

def main():
    app = create_app()
    if os.getenv('NOTIFICATION_ENABLED','false').lower()=='true':
        from notifications import PushWorker
        worker=PushWorker(app.config['JAVA_BASE_URL'],os.getenv('AI_SERVICE_KEY',''),os.getenv('VAPID_PRIVATE_KEY',''),os.getenv('VAPID_SUBJECT',''))
        app.extensions['push_worker']=worker
        worker.start()
        atexit.register(worker.stop)
    if app.config['AI_ENABLED']:
        # The AI process (ai_service.py) owns all camera/inference threads.
        # Web only talks to it over HTTP, so its CPU load can never starve waitress.
        ai = AiClient(app.config['AI_SERVICE_URL'])
        app.extensions['ai_runtime'] = ai
    from waitress import serve
    host = os.getenv('HOST','0.0.0.0')
    port = int(os.getenv('PORT','5000'))
    print(f'Web前端已就绪: http://{host}:{port}/', flush=True)
    serve(app,host=host,port=port,threads=8)

if __name__ == '__main__':
    main()

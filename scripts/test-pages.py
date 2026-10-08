"""Authenticated HTTP checks for all served Jinja pages and local assets.
This is not a substitute for a browser click/visual acceptance test.
"""
import os,re
from pathlib import Path
from html.parser import HTMLParser
import requests
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parent.parent;load_dotenv(ROOT/'.env.local')
base='http://127.0.0.1:'+os.getenv('PORT','5000')
s=requests.Session();s.trust_env=False
r=s.get(base+'/login',timeout=10);csrf=re.search(r'name="csrf_token" value="([^"]+)"',r.text)[1]
r=s.post(base+'/login',data={'username':'admin','password':os.environ['BOOTSTRAP_ADMIN_PASSWORD'],'csrf_token':csrf},timeout=10)
assert r.url.endswith('/dashboard')
paths=['/dashboard','/alert/real','/alert/history','/monitor/live','/person/list','/person/upload','/setting/danger','/setting/users','/analysis/emotion','/analysis/interaction','/analysis/tracks']
assets=set()
class Parser(HTMLParser):
    def handle_starttag(self,tag,attrs):
        for key,value in attrs:
            if key in ('href','src') and value.startswith('/static/'):assets.add(value)
for path in paths:
    r=s.get(base+path,timeout=10);assert r.status_code==200,(path,r.status_code)
    assert 'csrf-token' in r.text and 'data-page=' in r.text
    assert 'socket.io' not in r.text
    Parser().feed(r.text)
for asset in assets:
    r=s.get(base+asset,timeout=10);assert r.status_code==200,asset
print('PASS:',len(paths),'authenticated pages and',len(assets),'local assets; browser clicks not covered')

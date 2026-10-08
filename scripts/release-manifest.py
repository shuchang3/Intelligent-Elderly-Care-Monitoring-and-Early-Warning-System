"""Hash the deliverable source, built JAR and model files without reading secrets."""
import hashlib,json,subprocess
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
files=[]
for folder in ['algorithm','configs','backend/src','backend/.mvn','.run','scripts','static/js','static/css','templates','tests','docs','deploy']:
    for path in (ROOT/folder).rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix not in {'.pyc','.log'}:files.append(path)
for pattern in ['requirements*.txt','app.py','webapp.py','notifications.py','README.md','.env.example','backend/pom.xml','backend/mvnw','backend/mvnw.cmd']:
    files.extend(ROOT.glob(pattern))
sources={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(set(files))}
jar=ROOT/'backend/target/elder-care-backend.jar'
models={}
for p in [ROOT/'yolov8n-pose.pt',Path.home()/'.deepface/weights/facial_expression_model_weights.h5']:
    models[p.name]={'present':p.is_file(),'sha256':sha(p) if p.is_file() else None}
base=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True).stdout.strip()
modified=bool(subprocess.run(['git','status','--porcelain'],cwd=ROOT,text=True,capture_output=True).stdout.strip())
manifest={'version':'1.1.0-integration','generatedAt':datetime.now(timezone.utc).isoformat(),'gitBase':base,'workingTreeModified':modified,'sourceAggregateSha256':hashlib.sha256(json.dumps(sources,sort_keys=True).encode()).hexdigest(),'sourceFiles':sources,'jar':{'file':'backend/target/elder-care-backend.jar','sha256':sha(jar)},'models':models,'excluded':['.env.local','runtime','backend/uploads','.venv','.venv-web','.venv-ai','known_faces','output/recognition']}
out=ROOT/'output/release';out.mkdir(parents=True,exist_ok=True)
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
print('Release manifest created; source files:',len(sources))

[CmdletBinding()]
param(
    [switch]$Recreate
)

$ErrorActionPreference='Stop'
$root=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$environment=Join-Path $root '.venv-ai'
$python=Join-Path $environment 'Scripts\python.exe'
$bootstrap=Join-Path $root '.venv-web\Scripts\python.exe'

if(-not(Test-Path -LiteralPath $bootstrap -PathType Leaf)){
    throw '缺少可运行的Python 3.12引导解释器：.venv-web\Scripts\python.exe'
}
if($Recreate -and (Test-Path -LiteralPath $environment)){
    $resolved=[IO.Path]::GetFullPath($environment)
    $expected=[IO.Path]::GetFullPath((Join-Path $root '.venv-ai'))
    if($resolved -ne $expected){throw '拒绝删除非本项目AI环境'}
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
if(-not(Test-Path -LiteralPath $python -PathType Leaf)){
    & $bootstrap -m venv $environment
}

& $python -m pip install --upgrade pip
& $python -m pip install torch==2.13.0 torchvision==0.28.0 --index-url https://download.pytorch.org/whl/test/cu126
& $python -m pip install -r (Join-Path $root 'requirements-ai-runtime.txt')
# face-recognition declares ``dlib`` although dlib-bin provides the same
# importable module on Windows. Avoid an unnecessary local C++ build.
& $python -m pip install face-recognition==1.3.0 --no-deps
$dependencyIssues=(& $python -m pip check 2>&1 | Out-String).Trim()
if($LASTEXITCODE -ne 0 -and $dependencyIssues -notmatch '^face-recognition 1\.3\.0 requires dlib, which is not installed\.$'){
    throw "AI依赖存在冲突：$dependencyIssues"
}
$env:YOLO_CONFIG_DIR=Join-Path $root '.ultralytics'
& $python -c "import json,torch,flask,cv2,ultralytics,face_recognition,deepface,deep_sort_realtime,imageio_ffmpeg; print(json.dumps({'torch':torch.__version__,'cudaAvailable':torch.cuda.is_available(),'cudaVersion':torch.version.cuda,'device':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None},ensure_ascii=False))"

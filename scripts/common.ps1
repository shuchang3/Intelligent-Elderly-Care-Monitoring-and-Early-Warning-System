Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))

function Import-LocalEnvironment {
    $file = Join-Path $ProjectRoot '.env.local'
    if (-not (Test-Path -LiteralPath $file)) { throw '请先运行 scripts/setup-local.ps1 创建本地配置。' }
    foreach ($line in [IO.File]::ReadAllLines($file)) {
        if ($line -match '^\s*([A-Z][A-Z0-9_]*)=(.*)$') {
            # Literal values only: never evaluate shell code from configuration.
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim().Trim('"').Trim("'"), 'Process')
        }
    }
    # Local traffic must not be sent through workstation HTTP proxies.
    $env:NO_PROXY='127.0.0.1,localhost,::1'
}
function Resolve-PythonPath {
    param([string[]]$Candidates, [string]$ImportCheck, [string]$NotFoundMessage)
    foreach ($path in $Candidates) {
        if (Test-Path -LiteralPath $path) {
            $prev = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            & $path -c $ImportCheck 1>$null 2>$null
            $ok = ($LASTEXITCODE -eq 0)
            $ErrorActionPreference = $prev
            if ($ok) { return $path }
        }
    }
    throw $NotFoundMessage
}
function Get-WebPython {
    $candidates = @()
    if ($env:PYTHON_EXE) { $candidates += $env:PYTHON_EXE }
    $candidates += (Join-Path $ProjectRoot '.venv/Scripts/python.exe')
    $candidates += (Join-Path $ProjectRoot '.venv-web/Scripts/python.exe')
    Resolve-PythonPath $candidates 'import flask, flask_session, flask_sqlalchemy, requests, waitress, dotenv' '未找到安装网页依赖的Python。先用可用解释器安装 requirements-web.txt；不会自动删除原虚拟环境。'
}
function Get-AiPython {
    if ($env:PYTHON_EXE) { $candidates = @($env:PYTHON_EXE) } else { $candidates = @() }
    $candidates += (Join-Path $ProjectRoot '.venv-ai/Scripts/python.exe')
    Resolve-PythonPath $candidates 'import flask, waitress, dotenv, torch, cv2, ultralytics, face_recognition, deepface, deep_sort_realtime, imageio_ffmpeg' '未找到完整算法环境。请先运行 scripts/setup-ai-env.ps1。'
}
function Get-ProjectPython { Get-WebPython }
function Assert-PortFree([int]$Port) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if ($listener) { throw "端口 $Port 已被占用；不会停止未知进程。" }
}
function Save-ProcessRecord($Process, [string]$Name) {
    $folder = Join-Path $ProjectRoot 'runtime/pids'
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    @{ pid=$Process.Id; started=$Process.StartTime.ToUniversalTime().ToString('o'); name=$Name; root=$ProjectRoot } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $folder "$Name.json") -Encoding utf8
}
function Wait-Health([string]$Url, $Process, [int]$Attempts=60) {
    for ($i=0;$i -lt $Attempts;$i++) {
        $Process.Refresh()
        if ($Process.HasExited) { throw '服务启动失败，请检查 runtime/logs 中的日志。' }
        try { $r=Invoke-WebRequest -Uri $Url -TimeoutSec 2 -UseBasicParsing; if ($r.StatusCode -eq 200) { return } } catch {}
        Start-Sleep -Milliseconds 500
    }
    throw "服务健康检查超时：$Url"
}

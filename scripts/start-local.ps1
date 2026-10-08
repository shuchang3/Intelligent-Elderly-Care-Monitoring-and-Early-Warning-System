param([switch]$EnableAI)
. (Join-Path $PSScriptRoot 'common.ps1')
Import-LocalEnvironment
if($EnableAI){$env:AI_ENABLED='true'}
$webPort=if($env:PORT){[int]$env:PORT}else{5000}
$backendPort=if($env:BACKEND_PORT){[int]$env:BACKEND_PORT}else{8080}
$aiPort=if($env:AI_PORT){[int]$env:AI_PORT}else{5002}
Assert-PortFree $webPort
Assert-PortFree $backendPort
if($EnableAI){ Assert-PortFree $aiPort }
$tcp=New-Object Net.Sockets.TcpClient
try { $tcp.Connect('127.0.0.1',3306) } catch { throw '请先启动MySQL；脚本不会修改系统服务设置。' } finally { $tcp.Dispose() }
& (Join-Path $PSScriptRoot 'start-backend.ps1')
# start-backend.ps1 re-runs Import-LocalEnvironment and would reset AI_ENABLED
# from .env.local (false). Re-apply the switch so the web process below starts
# with the AI client enabled.
if($EnableAI){$env:AI_ENABLED='true'}
$logs=Join-Path $ProjectRoot 'runtime/logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
if($EnableAI){
    $env:YOLO_CONFIG_DIR=Join-Path $ProjectRoot '.ultralytics'
    $aiPython=Get-AiPython
    $aiProcess=Start-Process -FilePath $aiPython -ArgumentList @('-u','ai_service.py') -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'ai.out.log') -RedirectStandardError (Join-Path $logs 'ai.err.log') -PassThru
    Save-ProcessRecord $aiProcess 'ai'
    try { Wait-Health "http://127.0.0.1:$aiPort/health" $aiProcess 360 } catch { if(-not $aiProcess.HasExited){$aiProcess.Kill()};throw }
    Write-Host "算法服务已就绪：http://127.0.0.1:$aiPort/health"
}
$python=Get-WebPython
try {
    $process=Start-Process -FilePath $python -ArgumentList @('-u','app.py') -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'web.out.log') -RedirectStandardError (Join-Path $logs 'web.err.log') -PassThru
    Save-ProcessRecord $process 'web'
    Wait-Health "http://127.0.0.1:$webPort/health" $process $(if($EnableAI){360}else{60})
} catch { & (Join-Path $PSScriptRoot 'stop-local.ps1'); throw }
Write-Host "平台已启动，请用浏览器打开 http://127.0.0.1:$webPort"
Write-Host "算法开关：$env:AI_ENABLED；日志：runtime/logs"

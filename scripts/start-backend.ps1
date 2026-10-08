. (Join-Path $PSScriptRoot 'common.ps1')
Import-LocalEnvironment
$backendPort=if($env:BACKEND_PORT){[int]$env:BACKEND_PORT}else{8080}
Assert-PortFree $backendPort
$logs=Join-Path $ProjectRoot 'runtime/logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$jar=Join-Path $ProjectRoot 'backend/target/elder-care-backend.jar'
if (-not(Test-Path -LiteralPath $jar)) { throw '请先构建后端JAR' }
$java=(Get-Command java -ErrorAction Stop).Source
$process=Start-Process -FilePath $java -ArgumentList @('-jar',('"'+$jar+'"'),'--spring.profiles.active=local',"--server.port=$backendPort") -WorkingDirectory (Join-Path $ProjectRoot 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'backend.out.log') -RedirectStandardError (Join-Path $logs 'backend.err.log') -PassThru
Save-ProcessRecord $process 'backend'
try { Wait-Health "http://127.0.0.1:$backendPort/health" $process } catch { if(-not $process.HasExited){$process.Kill()};throw }
Write-Host "Java已就绪：http://127.0.0.1:$backendPort/health"

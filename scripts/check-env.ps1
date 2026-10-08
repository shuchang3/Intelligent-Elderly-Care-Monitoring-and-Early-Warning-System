. (Join-Path $PSScriptRoot 'common.ps1')
Import-LocalEnvironment
$env:YOLO_CONFIG_DIR=Join-Path $ProjectRoot '.ultralytics'
Write-Host "项目：$ProjectRoot"
& java -version
if ($LASTEXITCODE -ne 0) { throw '需要JDK21' }
$python=Get-ProjectPython
& $python --version
& $python -m pip check
if ($LASTEXITCODE -ne 0) {
    $issues=(& $python -m pip check 2>&1 | Out-String).Trim()
    if($issues -match '^face-recognition 1\.3\.0 requires dlib, which is not installed\.$'){
        & $python -c "import dlib, face_recognition; print('dlib-bin runtime OK')"
        if($LASTEXITCODE -ne 0){throw 'dlib实际导入失败'}
        Write-Warning '已确认使用dlib-bin提供dlib模块；pip按发行包名仍报告缺少dlib。此差异保留在验收说明中。'
    }else{throw 'Python依赖存在未验证冲突'}
}
$service=Get-Service -Name MySQL80 -ErrorAction SilentlyContinue
if ($service) { Write-Host "MySQL80: $($service.Status)" } else { Write-Host '未发现MySQL80服务，请确认数据库进程。' }
$webPort=if($env:PORT){[int]$env:PORT}else{5000}
$backendPort=if($env:BACKEND_PORT){[int]$env:BACKEND_PORT}else{8080}
foreach($port in @(3306,$webPort,$backendPort)) {
    $tcp=New-Object Net.Sockets.TcpClient
    try { $connected=$tcp.ConnectAsync('127.0.0.1',$port).Wait(1000); Write-Host "端口 $port 已监听：$($connected -and $tcp.Connected)" } catch { Write-Host "端口 $port 尚未监听" } finally { $tcp.Dispose() }
}
Write-Host "模型文件：$(Test-Path -LiteralPath (Join-Path $ProjectRoot 'yolov8n-pose.pt'))"
if($env:AI_ENABLED -eq 'true') {
    & $python -c "import cv2, torch, ultralytics, face_recognition, deepface, deep_sort_realtime, imageio_ffmpeg; print('AI imports OK')"
    if($LASTEXITCODE -ne 0) { throw '算法依赖不完整' }
}
Write-Host '检查结束。此脚本没有修改数据库、虚拟环境或防火墙。'

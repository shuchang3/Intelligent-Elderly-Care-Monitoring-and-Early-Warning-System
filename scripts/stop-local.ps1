. (Join-Path $PSScriptRoot 'common.ps1')
foreach($name in @('web','backend','ai')) {
    $path=Join-Path $ProjectRoot "runtime/pids/$name.json"
    if(-not(Test-Path -LiteralPath $path)){continue}
    $record=Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    if($record.root -ne $ProjectRoot){throw '进程记录不属于当前项目'}
    $process=Get-Process -Id $record.pid -ErrorAction SilentlyContinue
    if($process){
        # ConvertFrom-Json may deserialize an ISO timestamp into DateTime, so a
        # string comparison changes formatting even when the instant is equal.
        $recorded=[DateTimeOffset]$record.started
        $actual=[DateTimeOffset]$process.StartTime.ToUniversalTime()
        if([Math]::Abs(($actual-$recorded).TotalMilliseconds) -gt 1){throw "PID已被其他进程复用，拒绝停止：$name"}
        # Python virtual environments may create a child interpreter. The verified
        # PID and start time identify our process tree, never an arbitrary port.
        & taskkill.exe /PID $process.Id /T /F | Out-Null
        if($LASTEXITCODE -ne 0){throw "停止本项目进程失败：$name"}
    }
    Remove-Item -LiteralPath $path
}
Write-Host '仅停止了本项目记录的服务；MySQL和其他程序保持不变。'

. (Join-Path $PSScriptRoot 'common.ps1')
Push-Location (Join-Path $ProjectRoot 'backend')
try {
    & .\mvnw.cmd -B -ntp clean verify
    if ($LASTEXITCODE -ne 0) { throw '后端构建或测试失败' }
} finally { Pop-Location }

param([string]$DatabaseUser='root',[string]$AdminPassword='123456',[string]$StaffPassword='123456')
. (Join-Path $PSScriptRoot 'common.ps1')
$config = Join-Path $ProjectRoot '.env.local'
if (Test-Path -LiteralPath $config) { throw '.env.local 已存在，拒绝覆盖。请直接编辑原文件。' }
if (-not $env:DB_PASSWORD) {
    $secure = Read-Host '请输入本机MySQL密码（不会显示）' -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $env:DB_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}
function New-LocalSecret {
    $bytes=New-Object byte[] 32
    $rng=[Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return [BitConverter]::ToString($bytes).Replace('-','').ToLowerInvariant()
}
$settings=[ordered]@{
    DB_URL='jdbc:mysql://127.0.0.1:3306/elder_care_dev?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai'
    DB_USERNAME=$DatabaseUser; DB_PASSWORD=$env:DB_PASSWORD
    JWT_SECRET=(New-LocalSecret); AI_SERVICE_KEY=(New-LocalSecret); FLASK_SECRET_KEY=(New-LocalSecret)
    BOOTSTRAP_ADMIN_PASSWORD=$AdminPassword; BOOTSTRAP_STAFF_PASSWORD=$StaffPassword
    JAVA_BASE_URL='http://127.0.0.1:8080'; WS_PUBLIC_URL='ws://127.0.0.1:8080/ws/events'
    ALLOWED_ORIGINS='http://127.0.0.1:5000,http://localhost:5000'; AI_ENABLED='false'; AI_NODE_CODE='NODE001'
    REDIS_ENABLED='false'; COOKIE_SECURE='false'; HOST='127.0.0.1'; PORT='5000'; BACKEND_PORT='8080'; NOTIFICATION_ENABLED='false'
}
$lines=foreach($item in $settings.GetEnumerator()) { if ($item.Value -match '[\r\n]') { throw '配置值不允许换行' }; "$($item.Key)=$($item.Value)" }
[IO.File]::WriteAllLines($config,$lines,(New-Object Text.UTF8Encoding $false))
# Restrict local secrets to the current Windows user and SYSTEM.
$identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $config '/inheritance:r' '/grant:r' ($identity+':(F)') 'SYSTEM:(F)' | Out-Null
if($LASTEXITCODE -ne 0){throw '配置已生成，但文件权限设置失败；请保护 .env.local 后再启动。'}
Write-Host '已创建 .env.local（不会自动建库）。admin / staff01 初始密码保存在该文件内，请勿发送给他人。'

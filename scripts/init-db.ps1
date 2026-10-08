param([string]$MySqlExe='C:/Program Files/MySQL/MySQL Server 8.0/bin/mysql.exe')
. (Join-Path $PSScriptRoot 'common.ps1')
Import-LocalEnvironment
if ($env:DB_URL -notmatch '^jdbc:mysql://127\.0\.0\.1:3306/elder_care_dev(?:\?|$)') { throw '本地初始化只允许独立 elder_care_dev 库，不允许旧 elder_care 库。' }
if (-not (Test-Path -LiteralPath $MySqlExe)) { throw '请通过 -MySqlExe 指定本机 mysql.exe' }
$jar=Join-Path $ProjectRoot 'backend/target/elder-care-backend.jar'
if (-not(Test-Path -LiteralPath $jar)) { throw '先执行 scripts/build-backend.ps1' }
$env:MYSQL_PWD=$env:DB_PASSWORD
try {
    & $MySqlExe --host=127.0.0.1 --port=3306 "--user=$env:DB_USERNAME" '--execute=CREATE DATABASE IF NOT EXISTS elder_care_dev CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;'
    if($LASTEXITCODE -ne 0) { throw '创建独立开发库失败，未执行表初始化' }
} finally { Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue }
Push-Location (Join-Path $ProjectRoot 'backend')
try { & java -jar $jar --app.initialize=true --spring.main.web-application-type=none; if($LASTEXITCODE -ne 0) { throw '初始化失败，请检查日志；禁止重新导入旧DROP TABLE脚本。' } } finally { Pop-Location }

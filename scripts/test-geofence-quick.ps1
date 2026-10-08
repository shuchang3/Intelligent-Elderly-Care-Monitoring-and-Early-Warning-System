# Geofence Quick Test Script
# This script will reinitialize database and run tests

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Geofence Feature - Quick Test" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check environment
Write-Host "[1/5] Checking environment..." -ForegroundColor Yellow
if (-not (Test-Path ".env.local")) {
    Write-Host "ERROR: Missing .env.local file. Please run scripts/setup-local.ps1 first" -ForegroundColor Red
    exit 1
}

# Load environment variables
. .\.venv\Scripts\Activate.ps1
$envContent = Get-Content .env.local
foreach ($line in $envContent) {
    if ($line -match '^([^=]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2].Trim('"'), 'Process')
    }
}

Write-Host "OK: Environment loaded" -ForegroundColor Green
Write-Host ""

# Reinitialize database
Write-Host "[2/5] Reinitializing database..." -ForegroundColor Yellow
$confirm = Read-Host "This will clear existing data. Continue? (y/n)"
if ($confirm -ne "y") {
    Write-Host "Cancelled" -ForegroundColor Yellow
    exit 0
}

try {
    .\scripts\init-db.ps1
    Write-Host "OK: Database initialized" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Database initialization failed: $_" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Build backend
Write-Host "[3/5] Building Java backend..." -ForegroundColor Yellow
try {
    .\scripts\build-backend.ps1
    Write-Host "OK: Backend build completed" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Backend build failed: $_" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Start services
Write-Host "[4/5] Starting services..." -ForegroundColor Yellow
Write-Host "  -> Java Backend (port: $env:BACKEND_PORT)" -ForegroundColor Gray
Write-Host "  -> AI Service (port: $env:AI_PORT)" -ForegroundColor Gray
Write-Host ""

# Start Java backend in background
Start-Process powershell -ArgumentList "-NoExit", "-Command", "& {.\scripts\start-backend.ps1}" -WindowStyle Normal
Start-Sleep -Seconds 3

# Start AI service
Start-Process python -ArgumentList "ai_service.py" -WindowStyle Normal
Start-Sleep -Seconds 5

Write-Host "OK: Services started" -ForegroundColor Green
Write-Host ""

# Run test
Write-Host "[5/5] Running geofence test..." -ForegroundColor Yellow
Write-Host ""

python scripts/test-geofence.py

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Test Completed!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Visit these pages to view results:" -ForegroundColor Yellow
Write-Host "  - Geofence Map: http://localhost:$env:PORT/geofence/map" -ForegroundColor White
Write-Host "  - Real-time Alerts: http://localhost:$env:PORT/alert/real" -ForegroundColor White
Write-Host "  - Alert History: http://localhost:$env:PORT/alert/history" -ForegroundColor White
Write-Host ""
Write-Host "Press any key to stop services..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

# Stop services
Write-Host "Stopping services..." -ForegroundColor Yellow
Stop-Process -Name "java" -ErrorAction SilentlyContinue
Stop-Process -Name "python" -ErrorAction SilentlyContinue
Write-Host "OK: Services stopped" -ForegroundColor Green

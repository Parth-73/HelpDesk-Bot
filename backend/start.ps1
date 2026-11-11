param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Host 'Missing backend virtual environment. Follow README.md to install Python 3.12 and backend requirements.'
    exit 1
}
$envPath = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path -LiteralPath $envPath)) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot '.env.example') -Destination $envPath
}
@'
from app.config import Settings
import sys
try:
    settings = Settings()
except Exception:
    print('Invalid backend configuration. Check backend/.env against backend/.env.example.')
    sys.exit(1)
missing = [name for name, value in [('DATABASE_URL', settings.database_url.get_secret_value()), ('GEMINI_API_KEY', settings.gemini_api_key.get_secret_value())] if not value.strip()]
if missing:
    print('Fill these settings in backend/.env: ' + ', '.join(missing))
    print('Use your PostgreSQL connection string and your Google AI Studio API key. Keep both private.')
    sys.exit(1)
print('Required settings are present. Values have not been displayed; connectivity is checked when starting.')
'@ | & $pythonPath -
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($CheckOnly) { exit 0 }
& $pythonPath -m app.init_db
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Database initialization failed. Check the database URL, database password, SSL settings, and network access.'
    exit $LASTEXITCODE
}
Write-Host 'Starting backend. Open http://localhost:8000/api/ready to check readiness.'
& $pythonPath -m app
exit $LASTEXITCODE

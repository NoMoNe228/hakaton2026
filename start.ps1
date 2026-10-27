# Запуск сервиса «Суть»: сервер на http://127.0.0.1:8000
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path frontend\dist\index.html)) {
    Push-Location frontend; npm install; npm run build; Pop-Location
}
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000

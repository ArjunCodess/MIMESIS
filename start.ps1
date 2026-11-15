$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath 'apps/web/dist/index.html')) {
    throw 'The client is not built. Run npm install and npm run build first.'
}
Write-Host 'MIMESIS: http://127.0.0.1:8000'
Write-Host 'API reference: http://127.0.0.1:8000/docs'
python -m uvicorn services.api.main:app --host 127.0.0.1 --port 8000

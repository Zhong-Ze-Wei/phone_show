$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
uv sync --link-mode copy
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm --prefix frontend ci
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm --prefix frontend run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run --no-sync python app.py

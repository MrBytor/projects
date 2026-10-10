$ErrorActionPreference = 'Stop'
$appRuntime = Join-Path $env:LOCALAPPDATA 'EurasiaTeachingPlatform'
$appPython = Join-Path $appRuntime 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $appPython)) {
    python -m venv (Join-Path $appRuntime 'venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment.' }
}
& $appPython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $appPython (Join-Path $PSScriptRoot 'manage.py') migrate --noinput
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
& $appPython (Join-Path $PSScriptRoot 'manage.py') seed_demo
if ($LASTEXITCODE -ne 0) { throw 'Demo setup failed.' }
& $appPython (Join-Path $PSScriptRoot 'manage.py') seed_content
if ($LASTEXITCODE -ne 0) { throw 'Course materials setup failed.' }
Write-Host 'Open http://127.0.0.1:8765/ in your browser. Press Ctrl+C here to stop.'
try {
    & (Join-Path $PSScriptRoot 'render-presentations.ps1') -PythonPath $appPython
} catch {
    Write-Host "Presentation previews could not be prepared: $($_.Exception.Message). Existing previews and downloads remain available."
}
& $appPython (Join-Path $PSScriptRoot 'manage.py') runserver 127.0.0.1:8765 --noreload

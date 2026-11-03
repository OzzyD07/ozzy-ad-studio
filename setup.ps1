$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = '1'
New-Item -ItemType Directory -Force .tmp | Out-Null
$env:TEMP = Join-Path $PSScriptRoot '.tmp'
$env:TMP = $env:TEMP
python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Python sanal ortam kurulamadı.' }
& .\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Bağımlılıklar kurulamadı.' }
if (Get-Command node -ErrorAction SilentlyContinue) {
    Push-Location remotion
    npm ci --no-audit --no-fund
    $ok = $LASTEXITCODE -eq 0
    Pop-Location
    if (-not $ok) { throw 'Remotion paketleri kurulamadı.' }
} else {
    Write-Warning 'Node.js yok: Remotion (pipeline.py remotion) kullanılamaz. https://nodejs.org adresinden kurun.'
}
& .\.venv\Scripts\python.exe pipeline.py init
if ($LASTEXITCODE -ne 0) { throw 'Çalışma klasörü oluşturulamadı.' }
& .\.venv\Scripts\python.exe pipeline.py doctor
if ($LASTEXITCODE -ne 0) { throw 'Araç doğrulaması başarısız.' }

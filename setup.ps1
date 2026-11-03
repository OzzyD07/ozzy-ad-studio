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
& .\.venv\Scripts\python.exe pipeline.py init
if ($LASTEXITCODE -ne 0) { throw 'Çalışma klasörü oluşturulamadı.' }
& .\.venv\Scripts\python.exe pipeline.py doctor
if ($LASTEXITCODE -ne 0) { throw 'Araç doğrulaması başarısız.' }

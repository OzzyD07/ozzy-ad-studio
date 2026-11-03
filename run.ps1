Set-Location $PSScriptRoot
$env:PYTHONUTF8 = '1'
$python = '.\.venv\Scripts\python.exe'

if ($args.Count -gt 0) {
    & $python pipeline.py @args
    exit $LASTEXITCODE
}

# No arguments: a small menu for the everyday steps, so nobody has to remember commands.
function Invoke-Step([string[]]$Arguments) {
    Write-Host ''
    Write-Host ('> .\run.ps1 ' + ($Arguments -join ' ')) -ForegroundColor DarkGray
    & $python pipeline.py @Arguments
    Write-Host ''
}

$apps = @(& $python pipeline.py apps | ForEach-Object { ($_ -split '\s+')[0] } | Where-Object { $_ })
if ($apps.Count -eq 0) {
    Write-Host 'Henüz uygulama yok. Önce: .\run.ps1 new-app kisa-ad --name "Uygulama Adı"'
    exit 1
}
$app = $apps[0]
if ($apps.Count -gt 1) {
    Write-Host 'Uygulamalar:'
    for ($i = 0; $i -lt $apps.Count; $i++) { Write-Host ("  {0}) {1}" -f ($i + 1), $apps[$i]) }
    $pick = Read-Host 'Hangisi? (numara)'
    if ($pick -match '^\d+$' -and [int]$pick -ge 1 -and [int]$pick -le $apps.Count) { $app = $apps[[int]$pick - 1] }
}

while ($true) {
    Write-Host "OtoReklam - $app" -ForegroundColor Cyan
    Write-Host '  1) Durum (işler ve aşamaları)'
    Write-Host '  2) Panoyu aç (video, açıklama, hashtag, yayın saati)'
    Write-Host '  3) Teslim klasörünü güncelle'
    Write-Host '  4) Kare tablolarını oluştur (inceleme için)'
    Write-Host '  5) Promptları denetle'
    Write-Host '  6) Sıradaki işi üret (GPU kullanır)'
    Write-Host '  7) Platform sonuçlarını içe aktar (CSV)'
    Write-Host '  8) Yeni plan yap'
    Write-Host '  0) Çıkış'
    $choice = Read-Host 'Seçim'
    switch ($choice) {
        '1' { Invoke-Step @('--app', $app, 'status') }
        '2' {
            Invoke-Step @('--app', $app, 'pano')
            $board = Join-Path $PSScriptRoot "workspace\apps\$app\pano.html"
            if (Test-Path $board) { Start-Process $board }
        }
        '3' { Invoke-Step @('--app', $app, 'teslim') }
        '4' { Invoke-Step @('--app', $app, 'kareler') }
        '5' { Invoke-Step @('--app', $app, 'lint') }
        '6' {
            Invoke-Step @('--app', $app, 'run', '--limit', '1', '--dry-run')
            $ok = Read-Host 'Yukarıdaki iş video sunucusuna gönderilecek. Devam? (e/h)'
            if ($ok -eq 'e') { Invoke-Step @('--app', $app, 'run', '--limit', '1') }
        }
        '7' {
            $csv = (Read-Host 'CSV dosyasının yolu').Trim('"')
            if ($csv) { Invoke-Step @('--app', $app, 'sonuc', $csv) }
        }
        '8' {
            $start = Read-Host 'Başlangıç tarihi (YYYY-AA-GG)'
            $days = Read-Host 'Kaç gün? (ör. 14)'
            if ($start -and $days) { Invoke-Step @('--app', $app, 'plan', '--start', $start, '--days', $days) }
        }
        '0' { exit 0 }
        default { Write-Host 'Geçersiz seçim.' }
    }
}

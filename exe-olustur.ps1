<#
.SYNOPSIS
    EX30 Yolculuk Görüntüleyici'yi Windows exe'sine paketler (PyInstaller).

.DESCRIPTION
    Sırasıyla: Python'u bul → eksik bağımlılıkları kur → testleri çalıştır →
    ikonu üret → exe'yi derle. Bir adım düşerse betik orada durur; yarım kalmış
    bir exe dist/ içinde bırakılmaz.

    Varsayılan çıktı tek dosyalık exe:
        dist\EX30 Yolculuk Görüntüleyici.exe
    Tek dosya kendini her açılışta geçici klasöre açtığı için ilk pencere
    birkaç saniye gecikiyor. Açılış hızı önemliyse -Klasor kullan: exe yanındaki
    dosyalarla gelir ve anında açılır.

.PARAMETER Klasor
    Tek dosya yerine klasör olarak paketler (hızlı açılış, çok dosya).

.PARAMETER TestleriAtla
    Derlemeden önce birim testlerini çalıştırma.

.PARAMETER Temizle
    build/, dist/ ve *.spec dosyalarını siler, derleme yapmaz.

.PARAMETER Calistir
    Derleme bitince exe'yi açar.

.EXAMPLE
    .\exe-olustur.ps1
.EXAMPLE
    .\exe-olustur.ps1 -Klasor -Calistir
.EXAMPLE
    .\exe-olustur.ps1 -Temizle
#>

[CmdletBinding()]
param(
    [switch]$Klasor,
    [switch]$TestleriAtla,
    [switch]$Temizle,
    [switch]$Calistir
)

# DİKKAT: $ErrorActionPreference = "Stop" bilerek kurulmadı. Windows PowerShell
# 5.1'de harici bir programın stderr'e yazdığı her satır ErrorRecord'a
# dönüşüyor; pip ve PyInstaller ilerleme çıktısını stderr'e bastığı için betik
# başarılı derlemenin ortasında düşerdi. Her adım $LASTEXITCODE ile denetleniyor.

Set-Location -LiteralPath $PSScriptRoot

$AppName = "EX30 Yolculuk Görüntüleyici"
$IconPath = Join-Path $PSScriptRoot "assets\ex30.ico"

function Adim([string]$metin) { Write-Host "==> $metin" -ForegroundColor Cyan }
function Bilgi([string]$metin) { Write-Host "    $metin" -ForegroundColor Gray }
function Basarili([string]$metin) { Write-Host "    $metin" -ForegroundColor Green }
function Uyari([string]$metin) { Write-Host "    $metin" -ForegroundColor Yellow }

function Dur([string]$metin) {
    Write-Host ""
    Write-Host "HATA: $metin" -ForegroundColor Red
    exit 1
}

# --- Temizlik -----------------------------------------------------------------

if ($Temizle) {
    Adim "Derleme çıktıları siliniyor"
    $hedefler = @("build", "dist")
    $hedefler += Get-ChildItem -LiteralPath $PSScriptRoot -Filter "*.spec" | ForEach-Object { $_.Name }
    foreach ($yol in $hedefler) {
        if (Test-Path -LiteralPath $yol) {
            Remove-Item -LiteralPath $yol -Recurse -Force
            Bilgi "silindi: $yol"
        }
    }
    Basarili "Temiz."
    exit 0
}

# --- Python -------------------------------------------------------------------

Adim "Python aranıyor"

# Başlatıcıyı ADIYLA çağırıyoruz, Get-Command'in verdiği tam yolla değil:
# bu makinede `py.exe` Microsoft Store'un takma adı (WindowsApps) ve tam yolla
# çağrıldığında argümanları yutup Python'u etkileşimli kipte açıyor. Adıyla
# çağırıp gerçek python.exe yolunu kendisinden soruyoruz; sonraki bütün
# çağrılar o yola gidiyor, takma ad devrede kalmıyor.
$Python = $null
foreach ($aday in @(@{ Ad = "py"; On = @("-3") }, @{ Ad = "python"; On = @() })) {
    if (-not (Get-Command $aday.Ad -ErrorAction SilentlyContinue)) { continue }
    $on = $aday.On
    $bulunan = & $aday.Ad @on "-c" "import sys; print(sys.executable)"
    if ($LASTEXITCODE -eq 0 -and $bulunan) {
        $Python = $bulunan.Trim()
        break
    }
}
if (-not $Python) { Dur "Python bulunamadı. python.org'dan 3.10+ kur ve tekrar dene." }

function Py {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$PyArgs)
    & $Python @PyArgs
}

# --- Bağımlılıklar ------------------------------------------------------------

Adim "Bağımlılıklar denetleniyor"

function Ortam {
    $rapor = @{}
    foreach ($satir in (Py "araclar\ortam-denetle.py")) {
        if ($satir -match "^([a-z]+)=(.*)$") { $rapor[$Matches[1]] = $Matches[2] }
    }
    return $rapor
}

$ortam = Ortam
if (-not $ortam.ContainsKey("python")) { Dur "Ortam denetlenemedi: araclar\ortam-denetle.py çalışmadı." }
Bilgi "Python $($ortam.python) — $($ortam.executable)"

if (-not $ortam.tkinter) {
    Dur "tkinter yok. Python'u 'tcl/tk and IDLE' seçeneğiyle yeniden kur."
}
Bilgi "tkinter: var"

if (-not $ortam.matplotlib) {
    Uyari "matplotlib yok, kuruluyor..."
    Py "-m" "pip" "install" "-r" "requirements.txt"
    if ($LASTEXITCODE -ne 0) { Dur "matplotlib kurulamadı." }
    $ortam = Ortam
    if (-not $ortam.matplotlib) { Dur "matplotlib kurulduktan sonra da görünmüyor." }
}
Bilgi "matplotlib: $($ortam.matplotlib)"

if (-not $ortam.pyinstaller) {
    Uyari "PyInstaller yok, kuruluyor..."
    Py "-m" "pip" "install" "--upgrade" "pyinstaller"
    if ($LASTEXITCODE -ne 0) { Dur "PyInstaller kurulamadı." }
    $ortam = Ortam
    if (-not $ortam.pyinstaller) { Dur "PyInstaller kurulduktan sonra da görünmüyor." }
}
Bilgi "PyInstaller: $($ortam.pyinstaller)"

# --- Testler ------------------------------------------------------------------

if ($TestleriAtla) {
    Uyari "Testler atlandı (-TestleriAtla)."
} else {
    Adim "Birim testleri"
    Py "-m" "unittest" "discover" "-s" "tests" "-q"
    if ($LASTEXITCODE -ne 0) {
        Dur "Testler geçmedi. Bozuk kodu exe'ye paketlemiyoruz; -TestleriAtla ile zorlayabilirsin."
    }
    Basarili "Testler geçti."
}

# --- İkon ---------------------------------------------------------------------

Adim "İkon"
if (Test-Path -LiteralPath $IconPath) {
    Bilgi "hazır: assets\ex30.ico"
} elseif ($ortam.pillow) {
    Py "araclar\ikon-uret.py" | Out-Null
    if (Test-Path -LiteralPath $IconPath) { Bilgi "üretildi: assets\ex30.ico" }
    else { Uyari "İkon üretilemedi; exe varsayılan simgeyle derlenecek." }
} else {
    Uyari "Pillow yok; exe varsayılan simgeyle derlenecek."
}

# --- Derleme ------------------------------------------------------------------

Adim "Exe derleniyor"
$kip = if ($Klasor) { "--onedir" } else { "--onefile" }
Bilgi "kip: $kip"

$argListesi = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--name", $AppName,
    $kip,
    # Konsol penceresi açılmasın: bu bir GUI uygulaması.
    "--windowed",
    # Örnek veri exe'nin içine gömülüyor; app.resource_path onu _MEIPASS'ten okuyor.
    "--add-data", "ornek\trips-ornek.txt;ornek"
)

if (Test-Path -LiteralPath $IconPath) {
    $argListesi += @("--icon", $IconPath)
}

# Kurulu olsalar bile pakete girmesinler: matplotlib'in öteki arayüz arka
# uçları ve ilgisiz ağır kütüphaneler exe'yi gereksiz büyütüyor.
foreach ($haric in @(
        "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
        "IPython", "notebook", "jupyter", "pandas", "scipy", "pytest"
    )) {
    $argListesi += @("--exclude-module", $haric)
}

$argListesi += "main.py"

Py @argListesi
if ($LASTEXITCODE -ne 0) { Dur "PyInstaller derlemeyi tamamlayamadı." }

$exe = if ($Klasor) {
    Join-Path $PSScriptRoot "dist\$AppName\$AppName.exe"
} else {
    Join-Path $PSScriptRoot "dist\$AppName.exe"
}
if (-not (Test-Path -LiteralPath $exe)) { Dur "Derleme bitti ama exe bulunamadı: $exe" }

$mb = [math]::Round((Get-Item -LiteralPath $exe).Length / 1MB, 1)
Write-Host ""
Basarili "Hazır: $exe  ($mb MB)"
if (-not $Klasor) {
    Bilgi "Tek dosya kipinde ilk açılış birkaç saniye sürer; -Klasor anında açılır."
}
Bilgi "Kullanım: exe'yi çalıştır, 'Dosya ekle' ile trips-*.txt seç. İngilizce açmak için: --lang en"

if ($Calistir) {
    Adim "Açılıyor"
    Start-Process -FilePath $exe
}

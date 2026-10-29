# Builds Clip Downloader into a Windows installer:  dist\installer\Clip-Downloader-Setup-<version>.exe
#   1. sets up .venv and the requirements (first run only)
#   2. fetches ffmpeg + ffprobe into bin\ if they aren't there or on PATH
#   3. builds the app with PyInstaller (build.ps1)
#   4. installs Inno Setup if needed (per user, via winget or the official installer) and compiles the setup
# Usage: double-click make_installer.bat, or  powershell -ExecutionPolicy Bypass -File packaging\windows\make_installer.ps1
param([switch]$Install)  # -Install: run the finished setup silently afterwards
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $root

function Step($t) { Write-Host ""; Write-Host "==> $t" -ForegroundColor Green }

# ---- 1. Python environment
$py = ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Step "Creating .venv"
    try { & py -3 -m venv .venv } catch { }
    if (-not (Test-Path $py)) { & python -m venv .venv }
    if (-not (Test-Path $py)) { throw "Python 3.12 or newer is needed: https://www.python.org/downloads/" }
}
Step "Installing requirements"
& $py -m pip install --upgrade pip --disable-pip-version-check -q
& $py -m pip install -r requirements.txt --disable-pip-version-check -q
if ($LASTEXITCODE) { throw "pip install failed" }

# ---- 2. ffmpeg
New-Item -ItemType Directory -Force bin | Out-Null
if (-not ((Test-Path bin\ffmpeg.exe) -and (Test-Path bin\ffprobe.exe))) {
    $ff = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
    $fp = (Get-Command ffprobe -ErrorAction SilentlyContinue).Source
    if ($ff -and $fp) {
        Step "Using ffmpeg from PATH"
        Copy-Item $ff bin\ffmpeg.exe -Force; Copy-Item $fp bin\ffprobe.exe -Force
    } else {
        Step "Downloading ffmpeg (gyan.dev release essentials)"
        $zip = Join-Path $env:TEMP "ffmpeg-essentials.zip"
        Invoke-WebRequest "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $zip
        $tmp = Join-Path $env:TEMP "ffmpeg-essentials"
        if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
        Expand-Archive $zip $tmp -Force
        foreach ($t in "ffmpeg.exe", "ffprobe.exe") {
            Copy-Item (Get-ChildItem $tmp -Recurse -Filter $t | Select-Object -First 1).FullName "bin\$t" -Force
        }
        Remove-Item $tmp -Recurse -Force; Remove-Item $zip -Force
    }
}

# ---- 3. PyInstaller build
$ver = (& $py -c "import clipdl; print(clipdl.__version__)").Trim()
Step "Building Clip Downloader $ver"
& (Join-Path $root "build.ps1")

# ---- 4. Inno Setup
function Find-Iscc {
    foreach ($p in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                     "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
        if ($p -and (Test-Path $p)) { return $p }
    }
    $c = Get-Command iscc -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}
$iscc = Find-Iscc
if (-not $iscc) {
    Step "Installing Inno Setup (needed once to make the installer)"
    $wg = Get-Command winget -ErrorAction SilentlyContinue
    if ($wg) {
        & winget install --id JRSoftware.InnoSetup -e --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Host
        $iscc = Find-Iscc
    }
    if (-not $iscc) {
        $is = Join-Path $env:TEMP "innosetup.exe"
        Invoke-WebRequest "https://jrsoftware.org/download.php/is.exe" -OutFile $is
        Start-Process $is -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER" -Wait
        $iscc = Find-Iscc
    }
    if (-not $iscc) { throw "Couldn't install Inno Setup. Get it from https://jrsoftware.org/isdl.php and run this again." }
}
Step "Compiling the installer"
& $iscc /Q "/DAppVersion=$ver" "packaging\windows\ClipDownloader.iss"
if ($LASTEXITCODE) { throw "Inno Setup failed" }
$setup = Resolve-Path "dist\installer\Clip-Downloader-Setup-$ver.exe"
Write-Host ""
Write-Host "Installer ready: $setup" -ForegroundColor Green

if ($Install) {
    Step "Installing"
    Start-Process $setup -ArgumentList "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/TASKS=desktopicon" -Wait
    Write-Host "Installed. Clip Downloader is on your Desktop and in the Start menu." -ForegroundColor Green
}

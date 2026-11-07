$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppHome = Join-Path $env:LOCALAPPDATA 'A-BEATS'
$Venv = Join-Path $AppHome 'venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$FfmpegExe = Join-Path $AppHome 'ffmpeg\bin\ffmpeg.exe'
$Requirements = Join-Path $Root 'requirements.txt'
$RequirementsMarker = Join-Path $AppHome 'requirements.sha256'
New-Item -ItemType Directory -Force -Path $AppHome | Out-Null

Write-Host ''
Write-Host '================================================' -ForegroundColor DarkMagenta
Write-Host ' A-BEATS - FIRST RUN / STARTUP' -ForegroundColor Magenta
Write-Host '================================================' -ForegroundColor DarkMagenta

function Find-Python {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($version in @('-3.12', '-3.13', '-3.11', '-3')) {
            & $launcher.Source $version -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 2)" 2>$null
            if ($LASTEXITCODE -eq 0) { return @{Exe=$launcher.Source; Args=@($version)} }
        }
    }
    $direct = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($direct) {
        & $direct.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 2)" 2>$null
        if ($LASTEXITCODE -eq 0) { return @{Exe=$direct.Source; Args=@()} }
    }
    $known = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe')
    )
    foreach ($candidate in $known) {
        if (Test-Path $candidate) {
            & $candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 2)" 2>$null
            if ($LASTEXITCODE -eq 0) { return @{Exe=$candidate; Args=@()} }
        }
    }
    return $null
}

$Python = Find-Python
if (-not $Python) {
    $Winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $Winget) {
        throw 'Python 3.10+ was not found and winget is unavailable. Install Python 3.12 x64 from python.org, then run START_A-BEATS.bat again.'
    }
    Write-Host 'Installing Python 3.12 for the current Windows user...' -ForegroundColor Yellow
    & $Winget.Source install --id Python.Python.3.12 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw 'Python installation did not complete successfully.' }
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
    $Python = Find-Python
    if (-not $Python) { throw 'Python was installed but could not be located. Restart Windows or install Python 3.12 manually, then run the launcher again.' }
}

if (-not (Test-Path $VenvPython)) {
    Write-Host 'Creating the A-BEATS Python environment...' -ForegroundColor Yellow
    $CreateVenvArgs = @($Python.Args) + @('-m', 'venv', $Venv)
    & $Python.Exe @CreateVenvArgs
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}

$CurrentRequirementsHash = (Get-FileHash -Algorithm SHA256 -Path $Requirements).Hash
$InstalledRequirementsHash = if (Test-Path $RequirementsMarker) { (Get-Content $RequirementsMarker -Raw).Trim() } else { '' }
if ($CurrentRequirementsHash -ne $InstalledRequirementsHash) {
    Write-Host 'Installing / updating application libraries (first run or application update)...' -ForegroundColor Yellow
    & $VenvPython -m pip install --disable-pip-version-check --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'pip could not be updated.' }
    & $VenvPython -m pip install --disable-pip-version-check -r $Requirements
    if ($LASTEXITCODE -ne 0) { throw 'Application libraries could not be installed. Check your Internet connection.' }
    Set-Content -Path $RequirementsMarker -Value $CurrentRequirementsHash -Encoding ASCII
} else {
    Write-Host 'Application libraries are already installed.' -ForegroundColor DarkGray
}

if (-not (Test-Path $FfmpegExe)) {
    Write-Host 'Downloading FFmpeg (required for MP4 rendering)...' -ForegroundColor Yellow
    $Zip = Join-Path $env:TEMP 'a-beats-ffmpeg-essentials.zip'
    $Extract = Join-Path $env:TEMP 'a-beats-ffmpeg-extract'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $Zip
    if (Test-Path $Extract) { Remove-Item $Extract -Recurse -Force }
    Expand-Archive -Path $Zip -DestinationPath $Extract -Force
    $Found = Get-ChildItem -Path $Extract -Filter 'ffmpeg.exe' -Recurse | Select-Object -First 1
    if (-not $Found) { throw 'The FFmpeg archive did not contain ffmpeg.exe.' }
    $FfmpegDir = Split-Path -Parent $FfmpegExe
    New-Item -ItemType Directory -Force -Path $FfmpegDir | Out-Null
    Copy-Item $Found.FullName $FfmpegExe -Force
    $Probe = Get-ChildItem -Path (Split-Path -Parent $Found.FullName) -Filter 'ffprobe.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($Probe) { Copy-Item $Probe.FullName (Join-Path $FfmpegDir 'ffprobe.exe') -Force }
    Remove-Item $Zip -Force -ErrorAction SilentlyContinue
    Remove-Item $Extract -Recurse -Force -ErrorAction SilentlyContinue
}

$env:ABEATS_HOME = $AppHome
Write-Host 'Starting A-BEATS...' -ForegroundColor Green
& $VenvPython (Join-Path $Root 'app\main.py')
if ($LASTEXITCODE -ne 0) { throw "A-BEATS closed with exit code $LASTEXITCODE." }

@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title A-BEATS - Windows Release Builder

echo ==============================================
echo  A-BEATS - WINDOWS RELEASE BUILDER
echo ==============================================
where py >nul 2>nul
if errorlevel 1 (
  echo Python Launcher not found. Install Python 3.12 x64 first.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" py -3.12 -m venv .venv
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt pytest pyinstaller
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m unittest discover -s tests -v
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pytest -q
if errorlevel 1 goto failed

set "FFMPEG_HOME=%LOCALAPPDATA%\A-BEATS\ffmpeg\bin"
if not exist "%FFMPEG_HOME%\ffmpeg.exe" (
  echo Downloading FFmpeg for the release bundle...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $z=Join-Path $env:TEMP 'abeats-ffmpeg.zip'; $x=Join-Path $env:TEMP 'abeats-ffmpeg'; Invoke-WebRequest -UseBasicParsing 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $z; if(Test-Path $x){Remove-Item $x -Recurse -Force}; Expand-Archive $z $x -Force; $f=Get-ChildItem $x -Filter ffmpeg.exe -Recurse | Select-Object -First 1; if(!$f){throw 'ffmpeg.exe not found'}; New-Item -ItemType Directory -Force '%FFMPEG_HOME%' | Out-Null; Copy-Item $f.FullName '%FFMPEG_HOME%\ffmpeg.exe' -Force; $p=Get-ChildItem (Split-Path $f.FullName) -Filter ffprobe.exe -ErrorAction SilentlyContinue | Select-Object -First 1; if($p){Copy-Item $p.FullName '%FFMPEG_HOME%\ffprobe.exe' -Force}; Remove-Item $z -Force; Remove-Item $x -Recurse -Force"
  if errorlevel 1 goto failed
)

if exist dist rmdir /s /q dist
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name A-BEATS --icon assets\a_beats.ico --add-data "assets;assets" --collect-all googleapiclient --collect-all google_auth_oauthlib --collect-all google.auth --collect-all tzdata --collect-all PIL --hidden-import google.auth.transport.requests --hidden-import google_auth_oauthlib.flow --hidden-import core --hidden-import quota --hidden-import youtube_api --hidden-import itunes_discography --hidden-import token_store app\main.py
if errorlevel 1 goto failed
if exist "%FFMPEG_HOME%\ffmpeg.exe" (
  mkdir "dist\A-BEATS\ffmpeg\bin" 2>nul
  copy /Y "%FFMPEG_HOME%\ffmpeg.exe" "dist\A-BEATS\ffmpeg\bin\ffmpeg.exe" >nul
  if exist "%FFMPEG_HOME%\ffprobe.exe" copy /Y "%FFMPEG_HOME%\ffprobe.exe" "dist\A-BEATS\ffmpeg\bin\ffprobe.exe" >nul
)
for %%F in (README.md PRIVACY.md VERSION CHANGELOG.md THIRD_PARTY_NOTICES.md) do copy /Y "%%F" "dist\A-BEATS\%%F" >nul

echo.
echo SUCCESS: dist\A-BEATS\A-BEATS.exe
echo Copy the complete dist\A-BEATS folder, not only the EXE.
set "ISCC_EXE="
where ISCC.exe >nul 2>nul
if not errorlevel 1 set "ISCC_EXE=ISCC.exe"
if not defined ISCC_EXE if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC_EXE if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if defined ISCC_EXE (
  "%ISCC_EXE%" BUILD_INSTALLER.iss
  if errorlevel 1 goto failed
  echo Installer created in installer_output.
) else (
  echo Inno Setup 6 was not found. Install it and compile BUILD_INSTALLER.iss for Setup.exe.
)
pause
exit /b 0
:failed
echo.
echo BUILD FAILED. Read the error above.
pause
exit /b 1

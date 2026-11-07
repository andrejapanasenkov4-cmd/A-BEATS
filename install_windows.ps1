$ErrorActionPreference = 'Stop'
$Source = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallRoot = Join-Path $env:LOCALAPPDATA 'Programs\A-BEATS'
$StartMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\A-BEATS'
$DesktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'A-BEATS.lnk'
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

Write-Host 'Installing A-BEATS for the current Windows user...' -ForegroundColor Magenta
$SourceFull = [System.IO.Path]::GetFullPath($Source).TrimEnd('\')
$InstallFull = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
if ($SourceFull -ne $InstallFull) {
    & robocopy $SourceFull $InstallFull /E /R:2 /W:2 /NFL /NDL /NJH /NJS /NP /XD '.git' '.venv' '__pycache__' 'build' 'dist' 'installer_output' /XF '*.pyc'
    if ($LASTEXITCODE -ge 8) { throw "File copy failed (robocopy code $LASTEXITCODE)." }
} else {
    Write-Host 'Application is already in the install folder; refreshing shortcuts only.' -ForegroundColor DarkGray
}

New-Item -ItemType Directory -Force -Path $StartMenu | Out-Null
$Shell = New-Object -ComObject WScript.Shell
foreach ($ShortcutPath in @($DesktopShortcut, (Join-Path $StartMenu 'A-BEATS.lnk'))) {
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = Join-Path $InstallRoot 'START_A-BEATS.bat'
    $Shortcut.WorkingDirectory = $InstallRoot
    $Shortcut.IconLocation = Join-Path $InstallRoot 'assets\a_beats.ico'
    $Shortcut.Description = 'A-BEATS — YouTube Beat Publisher'
    $Shortcut.Save()
}
Write-Host 'A-BEATS installed. Starting the first-run setup...' -ForegroundColor Green
$Launcher = Join-Path $InstallRoot 'START_A-BEATS.bat'
Start-Process -FilePath $env:ComSpec -ArgumentList @('/c', "`"$Launcher`"") -WorkingDirectory $InstallRoot
Write-Host "Installed to: $InstallRoot"

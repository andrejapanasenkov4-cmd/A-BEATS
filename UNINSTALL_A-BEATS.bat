@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $answer=Read-Host 'Remove A-BEATS program files? User data will be kept. Type Y to continue'; if($answer -ne 'Y'){Write-Host 'Cancelled.'; exit 0}; $app=Join-Path $env:LOCALAPPDATA 'Programs\A-BEATS'; $sm=Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\A-BEATS'; $desk=Join-Path ([Environment]::GetFolderPath('Desktop')) 'A-BEATS.lnk'; if(Test-Path $app){Remove-Item $app -Recurse -Force}; if(Test-Path $sm){Remove-Item $sm -Recurse -Force}; if(Test-Path $desk){Remove-Item $desk -Force}; Write-Host 'A-BEATS program files removed. User data and YouTube videos were not deleted.'"
if errorlevel 1 pause
endlocal

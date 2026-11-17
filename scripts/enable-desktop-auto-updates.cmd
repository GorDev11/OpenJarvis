@echo off
setlocal
rem One-time owner signing setup. Run by double-clicking in Explorer.
rem No private key is ever stored in this repository.
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0enable-desktop-auto-updates.ps1"
set "OJ_EXIT=%ERRORLEVEL%"
echo.
if not "%OJ_EXIT%"=="0" (
  echo Signed update setup was not completed. See the error above.
) else (
  echo One-time signing configuration finished. Check the signed GitHub workflow.
)
echo.
pause
exit /b %OJ_EXIT%

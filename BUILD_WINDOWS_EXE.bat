@echo off
setlocal
cd /d "%~dp0"
echo ========================================
echo GoScore v1.0 - Windows EXE Builder
echo ========================================
echo.
where py >nul 2>nul
if errorlevel 1 (
  echo Python Launcher was not found. Install Python 3.8 or newer from python.org and enable PATH.
  pause
  exit /b 1
)
py -3 -m pip install --upgrade pyinstaller
if errorlevel 1 goto failed
py -3 -m PyInstaller --clean --noconfirm GoScore.spec
if errorlevel 1 goto failed
echo.
echo Build complete: dist\GoScore.exe
echo Test this file on a Windows PC before distributing it.
pause
exit /b 0
:failed
echo.
echo Build failed. Copy the error above before asking for help.
pause
exit /b 1

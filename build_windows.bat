@echo off
REM Build the Windows .exe for Naukri Profile Manager.
REM Run this on a Windows machine (PyInstaller cannot cross-compile).
setlocal

cd /d "%~dp0"

echo [1/3] Creating virtual environment...
if not exist .venv (
    python -m venv .venv
) else (
    echo       .venv already exists.
)

call .venv\Scripts\activate.bat

echo [2/3] Installing dependencies + pyinstaller...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

echo [3/3] Building standalone .exe...
python build.py --onefile

echo.
echo Done. Look for: dist\NaukriProfileManager.exe
echo (A one-folder build is also produced if you drop --onefile.)
pause
endlocal
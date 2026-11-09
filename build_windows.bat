@echo off
REM Build the Windows .exe for Naukri Profile Manager.
REM Run this on a Windows machine (PyInstaller cannot cross-compile).
setlocal

cd /d "%~dp0"

echo [1/4] Creating virtual environment...
if not exist .venv (
    python -m venv .venv
) else (
    echo       .venv already exists.
)

call .venv\Scripts\activate.bat

echo [2/4] Installing dependencies + pyinstaller...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

echo [3/4] Building standalone .exe...
REM build.py verifies the artifact before returning: it fails if httpcloak's
REM native library (or one of its dependencies) is missing from the bundle.
python build.py --onefile

echo [4/4] Building one-folder distribution (no %TEMP% extraction)...
python build.py
python -c "import shutil; shutil.make_archive('dist/NaukriProfileManager-windows-ondir', 'zip', 'dist/NaukriProfileManager')"

echo.
echo Done. Look for:
echo   dist\NaukriProfileManager.exe          (single file)
echo   dist\NaukriProfileManager\             (one folder)
echo   dist\NaukriProfileManager-windows-ondir.zip
echo.
echo If the .exe will not start on your machine, unzip the one-folder build
echo and run NaukriProfileManager.exe from inside it.
pause
endlocal

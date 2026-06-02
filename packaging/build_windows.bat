@echo off
REM Build Steam Curator for Windows (.exe)
set ROOT=%~dp0..
cd /d %ROOT%

echo Installing dependencies...
pip install pyinstaller pillow customtkinter requests python-i18n ^
    google-auth google-auth-oauthlib google-api-python-client matplotlib

echo Building .exe...
pyinstaller packaging/build.spec --clean --noconfirm

echo Creating installer with NSIS (if available)...
where makensis >nul 2>&1
if %errorlevel% == 0 (
    makensis packaging/installer.nsi
    echo Done: dist/SteamCurator-Windows-Setup.exe
) else (
    echo NSIS not found - distributing folder: dist/SteamCurator/
    echo To install NSIS: https://nsis.sourceforge.io/
)

echo Done!
pause

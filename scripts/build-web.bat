@echo off
REM ---------------------------------------------------------------------------
REM build-web.bat — Windows build script for the VCF Readiness Browser UI
REM
REM Produces a single double-click executable that starts a local web server
REM and opens your browser automatically. No Tkinter required.
REM
REM Output: dist\VCF-Readiness-Web-v<version>-win.exe
REM         dist\VCF-Readiness-Web-v<version>-win.zip
REM         logs\build-web.log
REM
REM Usage: double-click build-web.bat  (or run from Command Prompt)
REM
REM Optional code signing — removes the SmartScreen "unrecognized app" warning.
REM   set SIGN_PFX=C:\certs\codesign.pfx
REM   set SIGN_PFX_PASSWORD=yourpassword
REM ---------------------------------------------------------------------------

cd /d "%~dp0"
if not exist "vcf_hci" if exist "..\vcf_hci" cd /d "%~dp0.."

REM ---------------------------------------------------------------------------
REM Rotating Build Logs (keeps build-web.log, build-web.1.log, build-web.2.log)
REM ---------------------------------------------------------------------------
if not "%_BUILD_LOGGED%"=="1" if not "%NONINTERACTIVE%"=="1" (
    if not exist "logs" mkdir "logs"
    if exist "logs\build-web.2.log" del "logs\build-web.2.log"
    if exist "logs\build-web.1.log" move /y "logs\build-web.1.log" "logs\build-web.2.log" >nul
    if exist "logs\build-web.log" move /y "logs\build-web.log" "logs\build-web.1.log" >nul
    set _BUILD_LOGGED=1
    where powershell >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "& { & '%~f0' %* | Tee-Object -FilePath 'logs\build-web.log' }"
        exit /b %ERRORLEVEL%
    )
)

setlocal enabledelayedexpansion

set ENTRY=vcfr_web.py
set TIMESTAMP_URL=http://timestamp.digicert.com

echo =^> Checking Python...
python --version
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found.
    echo         Install from https://www.python.org/downloads/
    echo         Be sure to check "Add python.exe to PATH" during installation.
    if not defined CI if not "%NONINTERACTIVE%"=="1" pause
    exit /b 1
)

REM Extract tool version dynamically from package
for /f "tokens=*" %%v in ('python -c "import sys; sys.path.insert(0, '.'); from vcf_hci.constants import TOOL_VERSION; print(TOOL_VERSION)" 2^>nul') do set VERSION=%%v
if "%VERSION%"=="" (
    for /f "tokens=*" %%v in ('python -c "from vcf_hci.constants import TOOL_VERSION; print(TOOL_VERSION)" 2^>nul') do set VERSION=%%v
)
if "%VERSION%"=="" set VERSION=7.2.0

set NAME=VCF-Readiness-Web-v%VERSION%-win

echo =^> Checking / installing PyInstaller...
set PYINSTALLER_CMD=
where pyinstaller >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set PYINSTALLER_CMD=pyinstaller
) else (
    python -m PyInstaller --version >nul 2>&1
    if !ERRORLEVEL! equ 0 (
        set PYINSTALLER_CMD=python -m PyInstaller
    ) else (
        python -m pyinstaller --version >nul 2>&1
        if !ERRORLEVEL! equ 0 (
            set PYINSTALLER_CMD=python -m pyinstaller
        )
    )
)

if "%PYINSTALLER_CMD%"=="" (
    echo Installing PyInstaller via pip...
    python -m pip install "pyinstaller==6.*"
    where pyinstaller >nul 2>&1
    if !ERRORLEVEL! equ 0 (
        set PYINSTALLER_CMD=pyinstaller
    ) else (
        python -m PyInstaller --version >nul 2>&1
        if !ERRORLEVEL! equ 0 (
            set PYINSTALLER_CMD=python -m PyInstaller
        ) else (
            python -m pyinstaller --version >nul 2>&1
            if !ERRORLEVEL! equ 0 (
                set PYINSTALLER_CMD=python -m pyinstaller
            )
        )
    )
)

if "%PYINSTALLER_CMD%"=="" (
    echo [ERROR] PyInstaller could not be found or installed.
    echo         Please run: python -m pip install "pyinstaller==6.*"
    if not defined CI if not "%NONINTERACTIVE%"=="1" pause
    exit /b 1
)

%PYINSTALLER_CMD% --version

echo =^> Bundling documentation...
python tools\bundle_docs.py

echo =^> Cleaning intermediate scratch files...
if exist build rmdir /s /q build
if not exist dist mkdir dist
if exist "dist\%NAME%.exe" del "dist\%NAME%.exe"
if exist "dist\%NAME%.zip" del "dist\%NAME%.zip"
if exist "%NAME%.spec" del "%NAME%.spec"
if exist "VCF-Readiness-Web*.spec" del "VCF-Readiness-Web*.spec"

echo =^> Building %NAME%.exe...
%PYINSTALLER_CMD% ^
    --onefile ^
    --name "%NAME%" ^
    --collect-all vcf_hci ^
    "%ENTRY%"

if not exist "dist\%NAME%.exe" (
    echo [ERROR] Build failed - dist\%NAME%.exe not found.
    if not defined CI if not "%NONINTERACTIVE%"=="1" pause
    exit /b 1
)
echo.
echo =^> Build complete: dist\%NAME%.exe

REM ---------------------------------------------------------------------------
REM Code signing (only when a cert is configured)
REM ---------------------------------------------------------------------------
if "%SIGN_PFX%%SIGN_SUBJECT%"=="" goto :nosign

REM signtool ships with the Windows SDK and is usually not on PATH
set SIGNTOOL=signtool
where signtool >nul 2>&1
if %ERRORLEVEL% neq 0 (
    for /f "delims=" %%F in ('dir /b /s "%ProgramFiles(x86)%\Windows Kits\10\bin\*\x64\signtool.exe" 2^>nul') do set SIGNTOOL=%%F
)
if not defined SIGNTOOL goto :nosigntool
"%SIGNTOOL%" /? >nul 2>&1
if %ERRORLEVEL% neq 0 goto :nosigntool

echo =^> Signing dist\%NAME%.exe
if not "%SIGN_PFX%"=="" (
    "%SIGNTOOL%" sign /f "%SIGN_PFX%" /p "%SIGN_PFX_PASSWORD%" ^
        /fd SHA256 /tr "%TIMESTAMP_URL%" /td SHA256 ^
        "dist\%NAME%.exe"
) else (
    "%SIGNTOOL%" sign /n "%SIGN_SUBJECT%" ^
        /fd SHA256 /tr "%TIMESTAMP_URL%" /td SHA256 ^
        "dist\%NAME%.exe"
)
if %ERRORLEVEL% neq 0 (
    echo [WARN] Signing failed - the unsigned exe in dist\ is still usable.
    goto :zip
)
"%SIGNTOOL%" verify /pa "dist\%NAME%.exe"
echo     Signed OK.
goto :zip

:nosigntool
echo [WARN] signtool.exe not found. Install the Windows SDK to enable signing.
echo        The unsigned exe in dist\ is still usable.
goto :zip

:nosign
echo.
echo     Unsigned build. Users may see a SmartScreen warning on first launch.
echo     They can bypass it with: More info ^> Run anyway.
echo     Set SIGN_PFX or SIGN_SUBJECT to sign. See the header of this file.

:zip
echo.
echo =^> Packaging release archive dist\%NAME%.zip...
python -c "import zipfile; z = zipfile.ZipFile(r'dist\%NAME%.zip', 'w', zipfile.ZIP_DEFLATED); z.write(r'dist\%NAME%.exe', arcname=r'%NAME%.exe'); z.close()"
if exist "dist\%NAME%.zip" (
    echo     Created dist\%NAME%.zip
) else (
    echo [WARN] Could not create zip archive dist\%NAME%.zip
)

echo.
echo =^> Staging build into bin\...
if not exist bin mkdir bin
copy /y "dist\%NAME%.exe" "bin\%NAME%.exe" >nul

echo.
echo =^> Running post-build cleanup (retaining last 3 versions)...
python tools\clean_build_artifacts.py --keep 3 --platform win

echo.
echo     Double-click dist\%NAME%.exe to launch.
echo     Or extract dist\%NAME%.zip
echo     Build log saved to logs\build-web.log
if not defined CI if not "%NONINTERACTIVE%"=="1" pause

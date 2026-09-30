@echo off
REM ---------------------------------------------------------------------------
REM build.bat — Wrapper shim for VCF Readiness Assessment Tool Build
REM Delegating to build-web.bat for the recommended Browser UI binary.
REM ---------------------------------------------------------------------------
echo ==^> Delegating build to build-web.bat (Browser UI binary)...
echo.
if exist "%~dp0build-web.bat" (
    call "%~dp0build-web.bat" %*
) else if exist "%~dp0..\build-web.bat" (
    call "%~dp0..\build-web.bat" %*
) else (
    call "%~dp0build-web.bat" %*
)

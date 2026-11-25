@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Сборка Sonar в exe. Параметры передаются в build.py, например: build.bat --no-install
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 build.py %*
) else (
    python build.py %*
)
echo.
pause

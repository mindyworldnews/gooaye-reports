@echo off
cd /d "%~dp0"

if errorlevel 1 (
    echo %date% %time% [ERROR] Cannot change directory >> "%USERPROFILE%\gooaye_error.log"
    exit /b 1
)

echo ============================================================ >> "%~dp0run.log"
echo Start: %date% %time% >> "%~dp0run.log"
echo ============================================================ >> "%~dp0run.log"

"C:\Users\User\AppData\Local\Programs\Python\Python314\python.exe" "%~dp0main.py" >> "%~dp0run.log" 2>&1

echo End: %date% %time% >> "%~dp0run.log"
echo. >> "%~dp0run.log"

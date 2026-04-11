@echo off
chcp 65001 >nul

set BATFILE=Z:\我的雲端硬碟\ClaudeWorkspace\tools\股癌分析器\run.bat
set TASKNAME_WED=GooayeAnalyzer_Wed
set TASKNAME_SAT=GooayeAnalyzer_Sat

schtasks /delete /tn %TASKNAME_WED% /f 2>nul
schtasks /delete /tn %TASKNAME_SAT% /f 2>nul

schtasks /create /tn %TASKNAME_WED% /tr "\"%BATFILE%\"" /sc weekly /d WED /st 17:30 /f
schtasks /create /tn %TASKNAME_SAT% /tr "\"%BATFILE%\"" /sc weekly /d SAT /st 17:30 /f

echo.
echo Done! Tasks created:
echo   %TASKNAME_WED% - every Wednesday 17:30
echo   %TASKNAME_SAT% - every Saturday 17:30
pause

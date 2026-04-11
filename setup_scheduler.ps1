# setup_scheduler.ps1
# 設定 Windows 工作排程器：每週三、週六 17:30 自動執行股癌分析器
# 請用「以系統管理員身份執行 PowerShell」來跑這個腳本

$TaskName = "GooayeAnalyzer"
$BatchFile = "Z:\我的雲端硬碟\ClaudeWorkspace\tools\股癌分析器\run.bat"

# 如果舊的排程存在，先刪除
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "已刪除舊排程：$TaskName"
}

# 動作：執行 run.bat
$Action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$BatchFile`"" `
    -WorkingDirectory (Split-Path $BatchFile)

# 觸發條件 1：每週三 17:30
$TriggerWed = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Wednesday `
    -At "17:30"

# 觸發條件 2：每週六 17:30
$TriggerSat = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Saturday `
    -At "17:30"

# 設定：以目前登入使用者執行，不顯示視窗
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

# 主體：用目前使用者執行
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

# 建立排程
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $TriggerWed, $TriggerSat `
    -Settings $Settings `
    -Principal $Principal `
    -Description "股癌 Podcast 分析器 - 每週三、週六 17:30 自動執行"

Write-Host ""
Write-Host "排程設定完成！" -ForegroundColor Green
Write-Host "  任務名稱：$TaskName"
Write-Host "  執行時間：每週三、週六 17:30"
Write-Host "  執行檔案：$BatchFile"
Write-Host ""
Write-Host "可到「工作排程器」>「工作排程器程式庫」查看或手動執行"

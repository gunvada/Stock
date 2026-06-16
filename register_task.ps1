# 매일 한국시간 22:00(미국 장 개장 22:30 직전)에 스캐너를 자동 실행하도록
# Windows 작업 스케줄러에 등록한다. PowerShell에서 1회 실행:
#   powershell -ExecutionPolicy Bypass -File .\register_task.ps1
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RunScript = Join-Path $ScriptDir "run_scan.ps1"
$TaskName  = "VolumeSurgeScanner"

$Action  = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$RunScript`""

# 매일 22:00 KST (이 PC 시간대가 한국 표준시여야 함). 필요시 -At 시간 변경.
$Trigger = New-ScheduledTaskTrigger -Daily -At 22:00

$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Settings $Settings -Description "미국 거래량 폭증주 일일 스캔" -Force

Write-Output "등록 완료: '$TaskName' (매일 22:00 실행)"
Write-Output "확인:  Get-ScheduledTask -TaskName $TaskName"
Write-Output "즉시 실행 테스트:  Start-ScheduledTask -TaskName $TaskName"
Write-Output "삭제:  Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"

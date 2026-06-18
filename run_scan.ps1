# 눌림목(흡수) 반등 스캐너 실행 래퍼 (Windows 작업 스케줄러에서 호출)
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

$LogDir = Join-Path $ScriptDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDir "scan_$Stamp.log"

Write-Output "실행 시작: $(Get-Date)" | Tee-Object -FilePath $LogFile
python "$ScriptDir\pullback_scanner.py" 2>&1 | Tee-Object -FilePath $LogFile -Append
python "$ScriptDir\dashboard.py" 2>&1 | Tee-Object -FilePath $LogFile -Append   # 산출물 대시보드 갱신
Write-Output "실행 종료: $(Get-Date)" | Tee-Object -FilePath $LogFile -Append

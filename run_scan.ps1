# 눌림목(흡수) 반등 스캐너 실행 래퍼 (Windows 작업 스케줄러에서 호출)
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

$LogDir = Join-Path $ScriptDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDir "scan_$Stamp.log"

Write-Output "실행 시작: $(Get-Date)" | Tee-Object -FilePath $LogFile
# 무인 일일 파이프라인: 스캔→추천(희석/공매도 점검)→프리마켓 자동매매 기록→대시보드.
# 멱등 — 하루 1~2회(데이터 공개 후, 그리고 ET 09:29 매매창 종료 후) 호출 권장.
python "$ScriptDir\run_daily.py" 2>&1 | Tee-Object -FilePath $LogFile -Append
Write-Output "실행 종료: $(Get-Date)" | Tee-Object -FilePath $LogFile -Append

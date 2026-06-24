# -*- coding: utf-8 -*-
"""
매일 무인 자동 러너  (Daily Unattended Runner)
================================================
하루 한 번(또는 폴러가 반복 호출) 실행하면, 그 시점에 가능한 일을 멱등하게 처리한다:

  1) 최신 정규장 데이터가 풀렸으면  → scanner.py 로 스캔 (surge_<신호일>.csv)
  2) 새 surge 가 생겼으면           → recommend.py 로 픽 생성(+희석/공매도 점검)
  3) 매매창(ET 09:29)이 끝난 추천   → auto_trade.py 로 프리마켓 자동매매 기록
  4) dashboard.py 로 대시보드 갱신

이미 완료된 단계는 건너뛴다(중복 방지). 클라우드 컨테이너는 휘발성이라 진짜
'매일 무인'은 사용자 PC의 작업 스케줄러(run_scan.ps1)나 외부 cron 에서 이 스크립트를
하루 1~2회 호출하는 방식이 안정적이다.

사용법: python run_daily.py
"""
import os
import re
import sys
import glob
import subprocess
import datetime as dt

import scanner

try:
    sys.stdout.reconfigure(encoding="utf-8")
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:
    ET = None

PY = sys.executable


def run(script, *args):
    print(f"\n>>> {script} {' '.join(args)}")
    r = subprocess.run([PY, os.path.join(scanner.BASE_DIR, script), *args])
    return r.returncode == 0


def latest_date(prefix):
    fs = sorted(glob.glob(os.path.join(scanner.OUTPUT_DIR, f"{prefix}_*.csv")))
    fs = [f for f in fs if re.search(rf"{prefix}_(\d{{4}}-\d{{2}}-\d{{2}})\.csv$", os.path.basename(f))]
    return (re.search(r"_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(fs[-1])).group(1)
            if fs else None)


def main():
    cfg = scanner.load_config()
    key = cfg["polygon_api_key"]

    # 1) 최신 거래일 데이터가 풀렸는데 아직 스캔 안 했으면 스캔
    import requests
    today = dt.date.today()
    newest = None
    for back in range(1, 6):
        d = today - dt.timedelta(days=back)
        if d.weekday() >= 5:
            continue
        ds = d.isoformat()
        j = requests.get(scanner.POLY_GROUPED.format(date=ds),
                         params={"adjusted": "true", "apiKey": key}, timeout=30).json()
        if j.get("status") == "OK" and len(j.get("results", []) or []) > 100:
            newest = ds
            break
    have_surge = latest_date("surge")
    if newest and newest != have_surge:
        print(f"[1] 신규 거래일 {newest} 감지 → 스캔")
        run("scanner.py")
        run("recommend.py")
    else:
        print(f"[1] 스캔 최신 상태(surge={have_surge}, 최신거래일={newest}) — 건너뜀")

    # 3) 매매창 끝난 추천 자동매매 기록 (auto_trade 가 멱등 처리)
    print("[2] 프리마켓 자동매매 기록 시도 (ET 09:29 지난 매매일만)")
    run("auto_trade.py")

    # 4) 대시보드 갱신
    print("[3] 대시보드 갱신")
    run("dashboard.py")
    print("\n[완료] run_daily 종료")


if __name__ == "__main__":
    main()

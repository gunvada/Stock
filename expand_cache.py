# -*- coding: utf-8 -*-
"""
백테스트용 grouped daily 캐시 확장기  (Cache Expander)
======================================================
output/cache/grouped_<date>.json 을 과거로 더 받아 백테스트 표본을 늘린다.
이미 캐시된 날짜는 건너뛰고, 가장 과거 캐시일 직전부터 거꾸로 거래일을 채운다.
무료 티어(5req/분) 보호로 콜당 ~13초.

사용법:
  python expand_cache.py            # 기본 90 신규 거래일 확보
  python expand_cache.py 2025-12-01 # 해당일까지 거꾸로 확보
  python expand_cache.py 60         # 60 신규 거래일 확보
"""
import os
import re
import sys
import json
import glob
import time
import datetime as dt

import requests

import scanner

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CACHE_DIR = os.path.join(scanner.OUTPUT_DIR, "cache")


def cached_dates():
    out = []
    for p in glob.glob(os.path.join(CACHE_DIR, "grouped_*.json")):
        m = re.search(r"grouped_(\d{4}-\d{2}-\d{2})\.json$", os.path.basename(p))
        if m:
            out.append(m.group(1))
    return sorted(out)


def fetch_and_cache(date, key):
    url = scanner.POLY_GROUPED.format(date=date)
    r = requests.get(url, params={"adjusted": "true", "apiKey": key}, timeout=30)
    j = r.json()
    if j.get("status") in ("OK", "DELAYED") and (j.get("results") or []):
        res = j["results"]
        with open(os.path.join(CACHE_DIR, f"grouped_{date}.json"), "w") as f:
            json.dump(res, f)
        return len(res)
    return 0  # 휴장/미인가/빈응답


def main():
    cfg = scanner.load_config()
    key = cfg["polygon_api_key"]
    os.makedirs(CACHE_DIR, exist_ok=True)

    target_date, target_n = None, 90
    if len(sys.argv) > 1:
        a = sys.argv[1]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a):
            target_date = a
        else:
            target_n = int(a)

    have = set(cached_dates())
    earliest = min(have) if have else dt.date.today().isoformat()
    print(f"[시작] 캐시 {len(have)}일 (최과거 {earliest}). 목표: "
          + (f"{target_date}까지" if target_date else f"신규 {target_n}거래일"))

    cursor = dt.date.fromisoformat(earliest) - dt.timedelta(days=1)
    new_count, scanned, empty_streak = 0, 0, 0
    while scanned < 400:
        if target_date and cursor.isoformat() < target_date:
            break
        if not target_date and new_count >= target_n:
            break
        if cursor.weekday() < 5:  # 평일만
            ds = cursor.isoformat()
            if ds not in have:
                n = fetch_and_cache(ds, key)
                if n > 100:
                    new_count += 1
                    empty_streak = 0
                    print(f"  [{ds}] {n:,}종목 캐시 ({new_count} 신규)")
                else:
                    empty_streak += 1
                    print(f"  [{ds}] 빈응답/휴장/미인가 (streak {empty_streak})")
                    if empty_streak >= 8:
                        print("  [중단] 연속 빈응답 8회 — 무료티어 한계 도달 추정.")
                        break
                time.sleep(13)
        cursor -= dt.timedelta(days=1)
        scanned += 1

    total = len(cached_dates())
    print(f"[완료] 신규 {new_count}일 추가 → 총 {total}거래일 캐시.")


if __name__ == "__main__":
    main()

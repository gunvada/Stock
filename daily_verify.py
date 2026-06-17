# -*- coding: utf-8 -*-
"""
매일 자동 검증 (무인 실행용)
-----------------------------
output/pullback_<신호일>.csv 픽들 중, '매매일(신호일 다음 거래일)' 데이터가
이제 풀린 것을 자동 감지해 시초가매수→종가 결과를 비용 차감해 채점하고
output/verification_ledger.csv 에 누적 기록한다. 이미 채점한 건 건너뛴다.

비용: 왕복 수수료+슬리피지 2.5% 차감. 통계: 15거래일 표본 기준 룰.
"""
import os
import re
import sys
import glob
import datetime as dt

import requests
import pandas as pd

import scanner

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

COST = 2.5
TP, STOP = 10.0, 8.0
LEDGER = os.path.join(scanner.OUTPUT_DIR, "verification_ledger.csv")


def grouped_ok(date, key):
    r = requests.get(
        f"https://api.polygon.io/v2/aggs/grouped/locale/us/market/stocks/{date}",
        params={"adjusted": "true", "apiKey": key}, timeout=30)
    j = r.json()
    return j.get("status") == "OK" and len(j.get("results", []) or []) > 100


def daily_one(ticker, date, key):
    r = requests.get(
        f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{date}/{date}",
        params={"adjusted": "true", "apiKey": key}, timeout=30)
    res = r.json().get("results", []) or []
    return res[0] if res else None


def next_trading_date(signal_date, key):
    """신호일 다음 거래일 중 데이터가 풀린 첫 날을 찾는다(최대 6일 탐색)."""
    d = dt.date.fromisoformat(signal_date)
    for _ in range(6):
        d += dt.timedelta(days=1)
        if d.weekday() >= 5:
            continue
        if grouped_ok(d.isoformat(), key):
            return d.isoformat()
        return None  # 다음 거래일인데 아직 데이터 없음 → 너무 이름
    return None


def score(picks, trade_date, key):
    rows = []
    for t in picks["ticker"]:
        b = daily_one(t, trade_date, key)
        if not b or b["o"] <= 0:
            continue
        o, h, l, c = b["o"], b["h"], b["l"], b["c"]
        oc = (c - o) / o * 100
        hi = (h - o) / o * 100
        lo = (l - o) / o * 100
        hit_tp, hit_stop = hi >= TP, lo <= -STOP
        gross = -STOP if hit_stop else (TP if hit_tp else oc)
        rows.append({"ticker": t, "open": round(o, 4), "close": round(c, 4),
                     "oc_%": round(oc, 1), "hi_%": round(hi, 1), "lo_%": round(lo, 1),
                     "tp_hit": int(hit_tp), "stop_hit": int(hit_stop),
                     "net_%": round(gross - COST, 1)})
    return rows


def main():
    cfg = scanner.load_config()
    key = cfg["polygon_api_key"]
    done = set()
    if os.path.exists(LEDGER):
        old = pd.read_csv(LEDGER)
        done = set(old["signal_date"].astype(str))
    else:
        old = pd.DataFrame()

    new_rows = []
    for path in sorted(glob.glob(os.path.join(scanner.OUTPUT_DIR, "pullback_*.csv"))):
        sig = os.path.basename(path)[len("pullback_"):-len(".csv")]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", sig):
            continue  # pullback_backtest_*.csv 등 '날짜형식이 아닌' 파일은 스킵
        if sig in done:
            continue
        picks = pd.read_csv(path)
        if picks.empty:
            continue
        trade_date = next_trading_date(sig, key)
        if not trade_date:
            print(f"[대기] {sig} 픽 {len(picks)}개 — 매매일 데이터 아직 미공개.")
            continue
        scored = score(picks, trade_date, key)
        if not scored:
            print(f"[대기] {sig} — {trade_date} 종목 데이터 없음.")
            continue
        for s in scored:
            new_rows.append({"signal_date": sig, "trade_date": trade_date, **s})
        df = pd.DataFrame(scored)
        print(f"[채점] {sig}→{trade_date}: {len(df)}종목 | 순익평균 {df['net_%'].mean():+.1f}% "
              f"| 승 {(df['net_%']>0).sum()}/{len(df)} | +10%도달 {df['tp_hit'].sum()} | 손절 {df['stop_hit'].sum()}")
        for s in scored:
            print(f"     {s['ticker']:6s} 시초→종가 {s['oc_%']:+.1f}% (장중최고 {s['hi_%']:+.1f}%) → 순익 {s['net_%']:+.1f}%")

    if new_rows:
        ledger = pd.concat([old, pd.DataFrame(new_rows)], ignore_index=True)
        ledger.to_csv(LEDGER, index=False, encoding="utf-8-sig")
        print("\n" + "=" * 70)
        print(f"  누적 검증 성적 (총 {len(ledger)}거래, 왕복비용 {COST}% 차감)")
        print("=" * 70)
        n = len(ledger)
        print(f"  순익 평균 : {ledger['net_%'].mean():+.2f}% / 거래")
        print(f"  승률      : {(ledger['net_%']>0).mean()*100:.0f}%  ({(ledger['net_%']>0).sum()}/{n})")
        print(f"  +10% 도달 : {ledger['tp_hit'].mean()*100:.0f}%   | 손절 도달: {ledger['stop_hit'].mean()*100:.0f}%")
        print(f"  (15일 표본 기대: 승률 60%, +10%도달 57%)")
        print(f"  장부: {LEDGER}")
    else:
        print("새로 채점할 픽 없음(모두 검증 완료이거나 데이터 대기 중).")


if __name__ == "__main__":
    main()

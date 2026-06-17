# -*- coding: utf-8 -*-
"""
프리마켓 픽 자동 채점  —  ET 06:30 진입 → 09:30 개장가 청산 (순수 모니터링)
=============================================================================
output/premarket_<날짜>.csv 픽을, 그 날 ET 06:30 첫 봉 시가에 진입하고
09:30 개장 첫 봉 시가에 청산한 기준으로 채점한다.
손절/익절 라인 없이 순수 시초→개장가 P&L + 창내 최고/최저 도달을 추적한다.
왕복비용 2.5% 차감. 채점된 날짜는 건너뛰고 output/premarket_ledger.csv 에 누적.

데이터: yfinance 1분봉(prepost=True). 최근 ~7일 이내 조회 가능.
        7일 이상 지난 픽은 Polygon 분봉 캐시(output/cache/)에서 폴백.

사용법: python premarket_verify.py
"""
import os
import re
import sys
import glob
import json
import time
import datetime as dt

import pandas as pd

import scanner
from premarket_scanner import pm_config

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

COST = 2.5
LEDGER = os.path.join(scanner.OUTPUT_DIR, "premarket_ledger.csv")
CACHE_DIR = os.path.join(scanner.OUTPUT_DIR, "cache")
ENTRY_ET = "06:30"   # 확정 최적 진입 시각(타이밍 스터디 결과)
OPEN_ET  = "09:30"   # 개장가 청산


# --------------------------------------------------------------------------- #
# 분봉 데이터 조회
# --------------------------------------------------------------------------- #
def _poly_cache_path(ticker, date):
    return os.path.join(CACHE_DIR, f"min_{ticker}_{date}.json")


def fetch_yfinance(ticker, date):
    """yfinance 1분봉(prepost) → ET timezone DataFrame. 최근 ~7일만 제공."""
    try:
        import yfinance as yf
        start = dt.date.fromisoformat(date)
        end = start + dt.timedelta(days=1)
        df = yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat(),
                                       interval="1m", prepost=True, auto_adjust=False)
        if df.empty:
            return None
        df = df.set_index(df.index.tz_convert("America/New_York"))
        df = df[df.index.strftime("%Y-%m-%d") == date]
        return df if not df.empty else None
    except Exception:
        return None


def fetch_polygon_min(ticker, date, key, sleep_s=13):
    """Polygon 1분봉(extended hours). 캐시 우선, 없으면 API 호출."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = _poly_cache_path(ticker, date)
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)
    import requests
    url = (f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/minute"
           f"/{date}/{date}")
    r = requests.get(url, params={"adjusted": "true", "extended_hours": "true",
                                  "limit": 1000, "apiKey": key}, timeout=30)
    results = r.json().get("results") or []
    if results:
        with open(cache, "w") as f:
            json.dump(results, f)
    time.sleep(sleep_s)
    return results


def day_bars_df(ticker, date, key):
    """1분봉 ET timezone DataFrame 반환. yfinance 우선, 구 날짜면 Polygon 폴백."""
    cutoff = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    df = fetch_yfinance(ticker, date)
    if df is not None and not df.empty:
        return df
    if not key or date > cutoff:
        return None
    # Polygon 폴백 (캐시 우선 → 최대 13s 대기)
    try:
        from zoneinfo import ZoneInfo
        ET = ZoneInfo("America/New_York")
    except Exception:
        import pytz
        ET = pytz.timezone("America/New_York")
    bars = fetch_polygon_min(ticker, date, key)
    if not bars:
        return None
    rows = []
    for b in bars:
        ts = dt.datetime.fromtimestamp(b["t"] / 1000, tz=ET)
        rows.append({"datetime": ts, "Open": b["o"], "High": b["h"],
                     "Low": b["l"], "Close": b["c"]})
    df = pd.DataFrame(rows).set_index("datetime")
    df = df[df.index.strftime("%Y-%m-%d") == date]
    return df if not df.empty else None


# --------------------------------------------------------------------------- #
# 채점 (ET 06:30 진입 → 09:30 개장가 청산)
# --------------------------------------------------------------------------- #
def score_et_entry(picks, date, key):
    """각 픽에 대해 ET 06:30 진입 → 09:30 개장가 청산 순수 모니터링."""
    rows = []
    for _, r in picks.iterrows():
        t = r["ticker"]
        df = day_bars_df(t, date, key)
        if df is None:
            continue

        # 진입: 06:30 ET 이후 첫 봉 시가
        pm_slice = df.between_time("06:30", "09:29")
        if pm_slice.empty:
            continue
        entry_px = float(pm_slice.iloc[0]["Open"])
        if entry_px <= 0:
            continue

        # 청산: 09:30 ET 개장 첫 봉 시가 (없으면 프리마켓 마지막 봉 종가)
        open_slice = df.between_time("09:30", "09:32")
        if not open_slice.empty:
            exit_px   = float(open_slice.iloc[0]["Open"])
            exit_note = "09:30개장가"
        else:
            exit_px   = float(pm_slice.iloc[-1]["Close"])
            exit_note = "PM종가"

        # 창내 최고/최저 (진입 이후 ~ 09:30 직전)
        hi = float(pm_slice["High"].max())
        lo = float(pm_slice["Low"].min())
        oc = (exit_px - entry_px) / entry_px * 100
        rows.append({
            "ticker":       t,
            "candle_signal": r.get("candle_signal", r.get("gap_%", "")),
            "gap_%":        r.get("gap_%", ""),
            "entry_px":     round(entry_px, 4),
            "exit_px":      round(exit_px, 4),
            "exit_mode":    exit_note,
            "oc_%":         round(oc, 1),
            "hi_%":         round((hi - entry_px) / entry_px * 100, 1),
            "lo_%":         round((lo - entry_px) / entry_px * 100, 1),
            "net_%":        round(oc - COST, 1),
        })
    return rows


# --------------------------------------------------------------------------- #
# 메인
# --------------------------------------------------------------------------- #
def main():
    cfg = scanner.load_config()
    pm_config(cfg)
    key = cfg.get("polygon_api_key", "")

    done = set()
    old = pd.DataFrame()
    if os.path.exists(LEDGER):
        old = pd.read_csv(LEDGER)
        if "date" in old.columns:
            done = set(old["date"].astype(str))

    today = dt.date.today().isoformat()
    new_rows = []
    for path in sorted(glob.glob(os.path.join(scanner.OUTPUT_DIR, "premarket_*.csv"))):
        date = os.path.basename(path)[len("premarket_"):-len(".csv")]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            continue
        if date in done or date >= today:
            continue
        picks = pd.read_csv(path)
        if picks.empty:
            continue

        print(f"[채점중] {date} 프리마켓 픽 {len(picks)}종목 (ET {ENTRY_ET} 진입→{OPEN_ET} 개장가 청산)...")
        scored = score_et_entry(picks, date, key)
        if not scored:
            print(f"  → 데이터 없음(휴장/조회불가 또는 {date}가 7일 이상 지남).")
            continue

        new_rows += [{"date": date, **s} for s in scored]
        d = pd.DataFrame(scored)
        print(f"  → {len(d)}종목 | 순익평균 {d['net_%'].mean():+.1f}% | "
              f"상승 {(d['net_%']>0).sum()}/{len(d)} | "
              f"장중최고평균 {d['hi_%'].mean():+.1f}% | 장중최저평균 {d['lo_%'].mean():+.1f}%")
        for s in scored:
            print(f"     {s['ticker']:6s}  진입 {s['entry_px']}  →  청산 {s['exit_px']} ({s['exit_mode']})"
                  f"  수익 {s['oc_%']:+.1f}%  (창내최고 {s['hi_%']:+.1f}%  최저 {s['lo_%']:+.1f}%)"
                  f"  순익 {s['net_%']:+.1f}%")

    if not new_rows:
        print("새로 채점할 프리마켓 픽 없음(모두 완료이거나 데이터 대기 중).")
        return

    ledger = pd.concat([old, pd.DataFrame(new_rows)], ignore_index=True)
    ledger.to_csv(LEDGER, index=False, encoding="utf-8-sig")
    n = len(ledger)
    print("\n" + "=" * 72)
    print(f"  프리마켓 누적 모니터링  (ET {ENTRY_ET} 진입→{OPEN_ET} 개장가 청산 / 총 {n}거래 / 비용 {COST}%)")
    print("=" * 72)
    print(f"  순익 평균  : {ledger['net_%'].mean():+.2f}% / 거래")
    print(f"  상승 비율  : {(ledger['net_%']>0).mean()*100:.0f}%  ({(ledger['net_%']>0).sum()}/{n})")
    print(f"  장중 최고  : {ledger['hi_%'].mean():+.1f}%  평균  |  장중 최저: {ledger['lo_%'].mean():+.1f}%  평균")
    print(f"  장부: {LEDGER}")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
10분봉 차트 검증 (Intraday 10-min verification)
------------------------------------------------
winners.csv 의 종목별 매매일 10분봉을 받아, 일봉 프록시로 추정한
'프리마켓 급등 → 본장 꾸준 상승'이 실제 장중 경로에서도 성립하는지 확인한다.

세션 구분(EDT, UTC-4 기준):
  프리마켓 08:00~13:30 UTC (=04:00~09:30 ET)
  정규장   13:30~20:00 UTC (=09:30~16:00 ET)
"""

import os
import sys
import json

import requests
import pandas as pd

import scanner

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

AGG = "https://api.polygon.io/v2/aggs/ticker/{t}/range/10/minute/{d}/{d}"
REG_START, REG_END = 13.5, 20.0   # UTC 시간(시단위, EDT)
PM_START = 8.0


def fetch_bars(ticker, date, cfg, session):
    import time as _t
    url = AGG.format(t=ticker, d=date)
    params = {"adjusted": "true", "sort": "asc", "limit": 50000,
              "apiKey": cfg["polygon_api_key"]}
    for _ in range(3):
        r = session.get(url, params=params, timeout=30)
        if r.status_code == 429:
            _t.sleep(15); continue
        if r.status_code != 200:
            return []
        _t.sleep(cfg["scan"].get("rate_sleep_seconds", 13))
        return r.json().get("results", []) or []
    return []


def utc_hour(ms):
    # epoch ms -> UTC 시(시단위 실수). datetime.utcfromtimestamp 사용 (Date.now 아님)
    import datetime as dt
    d = dt.datetime.utcfromtimestamp(ms / 1000)
    return d.hour + d.minute / 60.0, d


def analyze(bars):
    pm, reg = [], []
    for b in bars:
        h, _ = utc_hour(b["t"])
        if PM_START <= h < REG_START:
            pm.append(b)
        elif REG_START <= h < REG_END:
            reg.append(b)
    if len(reg) < 4:
        return None

    reg_open = reg[0]["o"]
    reg_close = reg[-1]["c"]
    highs = [b["h"] for b in reg]
    reg_high = max(highs)
    high_idx = highs.index(reg_high)
    n = len(reg)

    # 장중 경로(시초가 대비 누적%) — 각 봉 종가 기준
    path = [round((b["c"] - reg_open) / reg_open * 100, 2) for b in reg]

    total_gain = reg_close - reg_open
    first3 = reg[min(2, n - 1)]["c"] - reg_open  # 첫 30분(3봉) 상승분
    early_frac = (first3 / total_gain) if total_gain > 0 else 0.0
    t2high_frac = high_idx / (n - 1)             # 고점 도달 시점(0=시초,1=마감)

    # 최대 낙폭(러닝 피크 대비)
    peak = reg_open; max_dd = 0.0
    for b in reg:
        peak = max(peak, b["c"])
        dd = (peak - b["c"]) / peak * 100
        max_dd = max(max_dd, dd)
    green = sum(1 for b in reg if b["c"] >= b["o"]) / n * 100
    above_open = sum(1 for b in reg if b["c"] >= reg_open) / n * 100

    # 프리마켓
    pm_ret = None
    if pm:
        pm_first = pm[0]["o"]
        pm_high = max(b["h"] for b in pm)
        if pm_first > 0:
            pm_ret = (pm_high - pm_first) / pm_first * 100

    # 분류
    if total_gain <= 0:
        shape = "본장하락"
    elif early_frac > 0.75:
        shape = "초반급등후횡보"
    elif reg_close < 0.85 * reg_high and max_dd > 15:
        shape = "고점이탈/페이드"
    elif t2high_frac > 0.55 and above_open > 70:
        shape = "꾸준우상향"
    else:
        shape = "혼합형"

    return {
        "reg_open": round(reg_open, 3), "reg_close": round(reg_close, 3),
        "oc_%": round((reg_close - reg_open) / reg_open * 100, 1),
        "premkt_high_%": round(pm_ret, 1) if pm_ret is not None else None,
        "early_gain_frac": round(early_frac, 2),
        "time_to_high": round(t2high_frac, 2),
        "max_drawdown_%": round(max_dd, 1),
        "above_open_%": round(above_open, 0),
        "n_bars": n, "shape": shape, "path": path,
    }


def main():
    cfg = scanner.load_config()
    session = requests.Session()
    wpath = os.path.join(scanner.OUTPUT_DIR, "winners.csv")
    if not os.path.exists(wpath):
        sys.exit("winners.csv 없음. 먼저 python analyze_winners.py 실행.")
    win = pd.read_csv(wpath)

    print(f"[10분봉 검증] {len(win)} 종목 수집 (Polygon, ~{len(win)*13//60+1}분 소요)...")
    out_rows, paths = [], {}
    for _, r in win.iterrows():
        t, d = r["ticker"], r["date"]
        bars = fetch_bars(t, d, cfg, session)
        res = analyze(bars)
        if res is None:
            print(f"  [{d} {t}] 분봉 부족/없음")
            continue
        paths[f"{t} {d}"] = {"path": res.pop("path"), "shape": res["shape"], "oc": res["oc_%"]}
        out_rows.append({"date": d, "ticker": t, **res})
        print(f"  [{d} {t}] {res['shape']:10s} 본장 {res['oc_%']:+.1f}% "
              f"고점도달 {res['time_to_high']:.0%} 최대낙폭 {res['max_drawdown_%']:.0f}%")

    df = pd.DataFrame(out_rows)
    df.to_csv(os.path.join(scanner.OUTPUT_DIR, "chart_verify.csv"), index=False, encoding="utf-8-sig")
    with open(os.path.join(scanner.OUTPUT_DIR, "intraday_paths.json"), "w", encoding="utf-8") as f:
        json.dump(paths, f)

    print("\n" + "=" * 88)
    print("  10분봉 장중 경로 분류")
    print("=" * 88)
    cols = ["date", "ticker", "shape", "oc_%", "premkt_high_%",
            "early_gain_frac", "time_to_high", "max_drawdown_%", "above_open_%"]
    print(df[cols].to_string(index=False))
    print("-" * 88)
    print("  [형태 분포]  " + ", ".join(f"{k}:{v}" for k, v in df["shape"].value_counts().items()))
    print(f"  꾸준우상향 비율: {(df['shape']=='꾸준우상향').mean()*100:.0f}%")
    print(f"  저장: output/chart_verify.csv , output/intraday_paths.json")
    print("=" * 88)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
프리마켓 06:30→09:30 개장가 청산 백테스트  (Premarket Entry Backtest)
=======================================================================
다음날 종가보유 전략이 대표본에서 엣지가 없었으므로(analyze_candle_edge),
'펌프→페이드' 진단에 따라 **프리마켓 06:30 ET 진입 → 09:30 개장가 청산**
전략을 과거 표본으로 검증한다. 선별(캔들/종합점수)이 이 청산에서는 의미가
생기는지도 함께 본다.

대상 픽: candle_edge_analysis.csv 의 캔들통과(강한매수·매수관심) 종목을
         신호일별 종합점수 상위 N(기본 6)으로, 최근 L신호일(기본 60).
매매일  : 신호일 다음 거래일(grouped 캐시 날짜열 기준).
데이터  : Polygon 1분봉(extended_hours). output/cache/min_<t>_<date>.json 캐싱.
          무료티어 5req/분 → 캐시 미스당 ~13초.

사용법:
  python premarket_backtest.py            # 최근 60신호일 × top6
  python premarket_backtest.py 90 6       # 최근 90신호일 × top6
  python premarket_backtest.py 60 6 nofetch  # 캐시에 있는 것만으로 집계(무호출)
"""
import os
import re
import sys
import json
import time
import datetime as dt

import pandas as pd
import requests

import scanner
import premarket_timing_study as tstudy  # cached_premkt_minutes 재사용(동일 캐시 포맷)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

COST = 2.5
CACHE_DIR = os.path.join(scanner.OUTPUT_DIR, "cache")
EDGE_CSV = os.path.join(scanner.OUTPUT_DIR, "candle_edge_analysis.csv")
BUY = ["강한매수", "매수관심"]


def cache_trading_dates():
    """grouped 캐시의 거래일 정렬 리스트 → 신호일 다음 거래일 매핑용."""
    ds = []
    for p in os.listdir(CACHE_DIR):
        m = re.match(r"grouped_(\d{4}-\d{2}-\d{2})\.json$", p)
        if m:
            ds.append(m.group(1))
    return sorted(ds)


def _hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def fetch_min(ticker, date, cfg, session, do_fetch=True):
    """프리마켓 분봉 {bars:[{min,o,h,l,c}], open_px} — 캐시 우선(타이밍스터디 포맷)."""
    cache = os.path.join(CACHE_DIR, f"min_{ticker}_{date}.json")
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            return json.load(f)
    if not do_fetch or not cfg.get("polygon_api_key"):
        return None
    return tstudy.cached_premkt_minutes(ticker, date, cfg, session)


def simulate(md):
    """06:30 ET 진입 → 09:30 개장가(open_px) 청산. 반환 dict 또는 None."""
    if not md:
        return None
    bars, open_px = md.get("bars") or [], md.get("open_px")
    seq = [b for b in bars if _hm(b["min"]) >= _hm("06:30")]  # 06:30~09:29 프리마켓
    if not seq:
        return None
    entry = float(seq[0]["o"])
    if entry <= 0:
        return None
    if open_px:
        exit_px = float(open_px)      # 09:30 개장가
    else:
        exit_px = float(seq[-1]["c"]) # 폴백: 프리마켓 마지막 종가
    hi = max(float(b["h"]) for b in seq)
    lo = min(float(b["l"]) for b in seq)
    oc = (exit_px - entry) / entry * 100
    return {"entry": round(entry, 4), "exit": round(exit_px, 4),
            "oc_%": round(oc, 1), "hi_%": round((hi - entry) / entry * 100, 1),
            "lo_%": round((lo - entry) / entry * 100, 1),
            "net_%": round(oc - COST, 1)}


def grp(s):
    return f"n={len(s):4d} | 순익평균 {s.mean():+5.1f}% | 상승 {(s>0).mean()*100:4.0f}% | 장중최고평균 {s.attrs.get('hi',float('nan')):+.1f}%" \
        if False else f"n={len(s):4d} | 순익평균 {s.mean():+5.1f}% | 상승 {(s>0).mean()*100:4.0f}%"


def main():
    cfg = scanner.load_config()
    key = cfg.get("polygon_api_key", "")
    L = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    N = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    do_fetch = not (len(sys.argv) > 3 and sys.argv[3] == "nofetch")

    if not os.path.exists(EDGE_CSV):
        sys.exit("[오류] candle_edge_analysis.csv 없음 — 먼저 analyze_candle_edge.py 실행.")
    edge = pd.read_csv(EDGE_CSV)
    buy = edge[edge["verdict"].isin(BUY)].copy()
    sig_days = sorted(buy["date"].unique())[-L:]
    picks = (buy[buy["date"].isin(sig_days)]
             .sort_values("rank_score", ascending=False)
             .groupby("date").head(N))

    tdates = cache_trading_dates()
    nextmap = {tdates[i]: tdates[i + 1] for i in range(len(tdates) - 1)}
    session = requests.Session()

    print(f"[대상] 최근 {L}신호일 × top{N} 캔들통과 = {len(picks)}픽 "
          f"(ET 06:30 진입→09:30 개장가, 비용 {COST}%)")
    rows, miss = [], 0
    todo = len(picks)
    for k, (_, p) in enumerate(picks.iterrows(), 1):
        sig = p["date"]
        trade = nextmap.get(sig)
        if not trade:
            continue
        md = fetch_min(p["ticker"], trade, cfg, session, do_fetch=do_fetch)
        r = simulate(md)
        if r is None:
            miss += 1
            continue
        rows.append({"signal_date": sig, "trade_date": trade, "ticker": p["ticker"],
                     "verdict": p["verdict"], "rank_score": p["rank_score"], **r})
        if k % 25 == 0:
            print(f"  ...{k}/{todo} 처리 (집계가능 {len(rows)}, 미스 {miss})")

    if not rows:
        print("집계 가능한 픽이 없습니다(분봉 데이터 부족 — nofetch 모드거나 캐시 미스).")
        return
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(scanner.OUTPUT_DIR, "premarket_backtest.csv"),
               index=False, encoding="utf-8-sig")

    s = res["net_%"]
    print("\n" + "=" * 70)
    print(f"  프리마켓 06:30→09:30 개장가 청산 백테스트  ({len(res)}거래, 미스 {miss})")
    print("=" * 70)
    print(f"  순익 평균 : {s.mean():+.2f}% / 거래")
    print(f"  상승 비율 : {(s>0).mean()*100:.0f}%  ({(s>0).sum()}/{len(s)})")
    print(f"  장중 최고 평균: {res['hi_%'].mean():+.1f}%  | 장중 최저 평균: {res['lo_%'].mean():+.1f}%")
    print(f"  중앙값 순익  : {s.median():+.1f}%")
    print("-" * 70)
    print("  [신호 등급별]")
    for v in BUY:
        g = res[res["verdict"] == v]["net_%"]
        if len(g):
            print(f"    {v:6s} {grp(g)}")
    print("  [종합점수 분위별]")
    res["q"] = pd.qcut(res["rank_score"].rank(method="first"),
                       min(3, res["rank_score"].nunique()),
                       labels=["하위", "중위", "상위"][:min(3, res["rank_score"].nunique())])
    for q in res["q"].cat.categories:
        g = res[res["q"] == q]["net_%"]
        print(f"    {q:4s} {grp(g)}")
    print(f"\n  상세 CSV: {os.path.join(scanner.OUTPUT_DIR, 'premarket_backtest.csv')}")


if __name__ == "__main__":
    main()

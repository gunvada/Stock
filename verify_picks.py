# -*- coding: utf-8 -*-
"""
당일 추출 종목 검증기 (다음날 시초가 매수 결과 채점)
-----------------------------------------------------
사용법: python verify_picks.py SIGNAL_DATE TRADE_DATE
예:     python verify_picks.py 2026-06-15 2026-06-16

output/pullback_<SIGNAL_DATE>.csv 의 종목을 TRADE_DATE 시초가 매수했다고 보고
시초→종가, +10% 도달, -8% 손절 도달, 브래킷 결과를 수수료+슬리피지 차감해 채점.
"""
import os
import sys
import datetime as dt
from statistics import mean

import requests
import pandas as pd

import scanner

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROUND_TRIP_COST = 2.5   # 수수료+슬리피지 왕복 비용(%) — 저가 소형주 보수적 가정
TP, STOP = 10.0, 8.0


def daily_one(ticker, date, key):
    r = requests.get(
        f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{date}/{date}",
        params={"adjusted": "true", "apiKey": key}, timeout=30)
    res = r.json().get("results", []) or []
    return res[0] if res else None


def main():
    if len(sys.argv) < 3:
        sys.exit("사용법: python verify_picks.py SIGNAL_DATE TRADE_DATE (예: 2026-06-15 2026-06-16)")
    sig_date, trade_date = sys.argv[1], sys.argv[2]
    cfg = scanner.load_config()
    key = cfg["polygon_api_key"]
    picks_path = os.path.join(scanner.OUTPUT_DIR, f"pullback_{sig_date}.csv")
    if not os.path.exists(picks_path):
        sys.exit(f"{picks_path} 없음.")
    picks = pd.read_csv(picks_path)

    rows = []
    for t in picks["ticker"]:
        b = daily_one(t, trade_date, key)
        if not b or b["o"] <= 0:
            print(f"  [{t}] {trade_date} 데이터 없음(미마감/거래정지?)")
            continue
        o, h, l, c = b["o"], b["h"], b["l"], b["c"]
        oc = (c - o) / o * 100
        hi = (h - o) / o * 100
        lo = (l - o) / o * 100
        hit_tp = hi >= TP
        hit_stop = lo <= -STOP
        # 브래킷(보수적: 같은날 둘 다면 손절 우선), 비용 차감
        if hit_stop:
            gross = -STOP
        elif hit_tp:
            gross = TP
        else:
            gross = oc
        net = gross - ROUND_TRIP_COST
        rows.append({"티커": t, "시초": round(o, 3), "종가": round(c, 3),
                     "시초→종가%": round(oc, 1), "장중최고%": round(hi, 1), "장중최저%": round(lo, 1),
                     "+10%도달": "O" if hit_tp else "X", "-8%손절": "O" if hit_stop else "X",
                     "브래킷순익%(비용후)": round(net, 1)})
    if not rows:
        sys.exit("채점할 데이터 없음.")
    df = pd.DataFrame(rows)
    print("\n" + "=" * 86)
    print(f"  검증: {sig_date} 신호 → {trade_date} 시초가 매수 결과 (왕복비용 {ROUND_TRIP_COST}% 차감)")
    print("=" * 86)
    print(df.to_string(index=False))
    print("-" * 86)
    nets = df["브래킷순익%(비용후)"]
    wins = (nets > 0).sum()
    print(f"  종목 {len(df)}개 | 순익 평균 {nets.mean():+.1f}% | 승 {wins}/{len(df)} "
          f"| +10%도달 {(df['+10%도달']=='O').sum()}개 | 손절 {(df['-8%손절']=='O').sum()}개")
    print("=" * 86)
    print(f"  ※ 15일 표본 통계 기대: 다음날 승률 60% · +10%도달 57%. 오늘 결과와 비교.")


if __name__ == "__main__":
    main()

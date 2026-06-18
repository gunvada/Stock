# -*- coding: utf-8 -*-
"""
캔들신호·종합점수 변별력 검증  (Core Thesis: Candle/Composite Edge)
====================================================================
비(非)캔들 단일특성이 대표본에서 거의 무력했으므로, 이 도구의 핵심 가설
— "캔들신호(파동연상)+종합점수 상위픽이 실제로 다음날 수익률을 가른다" —
를 283일 폭증후보 전체로 직접 검증한다.

각 폭증후보(ratio≥watch) 신호일 D 에 대해:
  · candle_signals.evaluate 로 verdict/candle_score 산출(look-ahead 없음, D까지만)
  · rank_score = candle_score + log10(ratio)   (recommend.py 와 동일)
  · 성과 = 다음 거래일 시초→종가 순익(비용 2.5%)

집계:
  ① 신호 등급(verdict)별 성과
  ② 종합점수(rank_score) 5분위별 성과
  ③ 매일 종합점수 상위 N픽 집중 시 성과 (top1/3/6/10) — 실제 운용 방식
  ④ '캔들필터(강한매수·매수관심) 적용' vs '전체' 비교

데이터: output/cache/grouped_*.json (API 무호출).
사용법: python analyze_candle_edge.py [ratio_min]
"""
import os
import sys
import math

import numpy as np
import pandas as pd

import scanner
import candle_signals
from analyze_prior_runup import load_cache_long, COST

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BUY = ["강한매수", "매수관심"]


def build_scored(df, cfg, ratio_min=None):
    sc = cfg["scan"]
    lookback = sc.get("lookback_trading_days", 7)
    price_min, price_max = sc["price_min"], sc["price_max"]
    watch = ratio_min if ratio_min is not None else sc.get("watch_threshold", 10.0)

    rows = []
    for t, g in df.groupby("ticker"):
        g = g.sort_values("date").reset_index(drop=True)
        if len(g) < lookback + 2:
            continue
        # evaluate 용 컬럼명 매핑(open/high/low/close/volume)
        gg = g.rename(columns={"o": "open", "h": "high", "l": "low",
                               "c": "close", "v": "volume"})
        v, c, o = g["v"], g["c"], g["o"]
        baseline = v.shift(1).rolling(max(2, lookback - 1)).median()
        next_o = o.shift(-1)
        next_c = c.shift(-1)
        ratio = v / baseline
        dollar_vol = v * c

        for i in range(len(g)):
            if pd.isna(baseline.iloc[i]) or baseline.iloc[i] <= 0:
                continue
            if pd.isna(next_o.iloc[i]) or next_o.iloc[i] <= 0:
                continue
            cl = c.iloc[i]
            if not (price_min <= cl <= price_max):
                continue
            if baseline.iloc[i] < sc["min_baseline_avg_volume"]:
                continue
            if v.iloc[i] < sc["min_latest_volume"]:
                continue
            if dollar_vol.iloc[i] < sc["min_latest_dollar_volume"]:
                continue
            if ratio.iloc[i] < watch:
                continue

            # 신호일 D 까지의 history 로만 캔들 평가(look-ahead 없음)
            window = gg.iloc[max(0, i - lookback): i + 1]
            sig = candle_signals.evaluate(window, lookback=lookback)
            rk = round(sig["score"] + math.log10(max(ratio.iloc[i], 1)), 2)
            fwd = (next_c.iloc[i] - next_o.iloc[i]) / next_o.iloc[i] * 100 - COST
            rows.append({"ticker": t, "date": g["date"].iloc[i],
                         "ratio": round(ratio.iloc[i], 1),
                         "verdict": sig["verdict"], "candle_score": sig["score"],
                         "rank_score": rk, "fwd_oc_net_%": round(fwd, 1)})
    return pd.DataFrame(rows)


def grp(s):
    return f"n={len(s):5d} | 순익평균 {s.mean():+5.1f}% | 상승 {(s>0).mean()*100:4.0f}%"


def main():
    cfg = scanner.load_config()
    ratio_min = float(sys.argv[1]) if len(sys.argv) > 1 else None
    df = load_cache_long()
    ndays = df["date"].nunique()
    print(f"[데이터] {ndays}거래일 ({df['date'].min()}~{df['date'].max()})")
    sd = build_scored(df, cfg, ratio_min=ratio_min)
    if sd.empty:
        sys.exit("후보 없음.")
    sd.to_csv(os.path.join(scanner.OUTPUT_DIR, "candle_edge_analysis.csv"),
              index=False, encoding="utf-8-sig")

    base = sd["fwd_oc_net_%"]
    print(f"[표본] {len(sd)}건 / {sd['ticker'].nunique()}종목 / 기초성과 {grp(base)}\n")

    # ① 신호 등급별
    print("=" * 74)
    print("  ① 캔들 신호 등급(verdict)별 다음날 시초→종가 순익")
    print("=" * 74)
    order = ["강한매수", "매수관심", "중립", "매도주의", "강한매도"]
    for v in order:
        s = sd[sd["verdict"] == v]["fwd_oc_net_%"]
        if len(s):
            print(f"  {v:6s} {grp(s)}")

    # ② 종합점수 5분위
    print("\n" + "=" * 74)
    print("  ② 종합점수(rank_score) 5분위별 성과  (Q5=상위)")
    print("=" * 74)
    sd2 = sd.copy()
    sd2["q"] = pd.qcut(sd2["rank_score"].rank(method="first"), 5,
                       labels=["Q1(하)", "Q2", "Q3", "Q4", "Q5(상)"])
    for q in ["Q1(하)", "Q2", "Q3", "Q4", "Q5(상)"]:
        s = sd2[sd2["q"] == q]
        print(f"  {q:7s} rank중앙값 {s['rank_score'].median():+4.1f} | {grp(s['fwd_oc_net_%'])}")

    # ③ 매일 종합점수 상위 N픽 (캔들필터 적용 = 실제 운용)
    print("\n" + "=" * 74)
    print("  ③ 매일 종합점수 상위 N픽 집중 (캔들필터 강한매수·매수관심 적용 = 실제 운용)")
    print("=" * 74)
    buy = sd[sd["verdict"].isin(BUY)].copy()
    for N in [1, 3, 6, 10]:
        picks = (buy.sort_values("rank_score", ascending=False)
                 .groupby("date").head(N))
        s = picks["fwd_oc_net_%"]
        print(f"  top{N:<2d} {grp(s)} | 거래일수 {picks['date'].nunique()}")
    # 캔들필터만(무순위) vs 전체
    print("-" * 74)
    print(f"  캔들통과 전체   {grp(buy['fwd_oc_net_%'])}")
    print(f"  폭증후보 전체   {grp(base)}")

    print(f"\n  상세 CSV: {os.path.join(scanner.OUTPUT_DIR, 'candle_edge_analysis.csv')}")


if __name__ == "__main__":
    main()

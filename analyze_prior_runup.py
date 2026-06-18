# -*- coding: utf-8 -*-
"""
직전 상승률 코호트별 다음날 성과 분석  (Prior Run-up vs Forward Return)
=========================================================================
가설: "신호일까지 직전 7거래일 동안 이미 100%+ 오른 폭증주는 추가 상승
       여력이 적다(평균회귀)" → 사실이면 그런 종목을 추천에서 제외.

방법(look-ahead 없음):
  · 신호일 D 의 폭증 후보(scanner.py 와 동일한 거래량·가격·거래대금 필터,
    ratio ≥ watch_threshold)를 모은다.
  · 각 후보의 '직전 7거래일 가격상승률' = close[D] / close[D-7거래일] - 1.
  · 성과 = 다음 거래일 시초→종가 (실제로 먹는 값) 및 종가→종가(갭포함).
  · 직전상승률 코호트(구간)별로 평균 성과·승률을 비교.

데이터: output/cache/grouped_*.json (scanner 가 캐싱한 전종목 일봉). API 무호출.

사용법: python analyze_prior_runup.py
"""
import os
import re
import sys
import glob
import json

import numpy as np
import pandas as pd

import scanner

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

COST = 2.5  # 왕복 비용(%) — 순익 계산용


def load_cache_long():
    """output/cache/grouped_*.json 전부 → long DataFrame[ticker,date,o,h,l,c,v]."""
    rows = []
    for path in sorted(glob.glob(os.path.join(scanner.OUTPUT_DIR, "cache", "grouped_*.json"))):
        m = re.search(r"grouped_(\d{4}-\d{2}-\d{2})\.json$", os.path.basename(path))
        if not m:
            continue
        date = m.group(1)
        with open(path) as f:
            results = json.load(f)
        for it in results:
            rows.append({"ticker": it.get("T"), "date": date,
                         "o": it.get("o", 0) or 0, "h": it.get("h", 0) or 0,
                         "l": it.get("l", 0) or 0, "c": it.get("c", 0) or 0,
                         "v": it.get("v", 0) or 0})
    df = pd.DataFrame(rows).dropna(subset=["ticker"])
    return df.sort_values(["ticker", "date"]).reset_index(drop=True)


def build_candidates(df, cfg):
    """전종목 long df → 폭증 후보 행 + 직전7거래일상승률 + 다음날 성과."""
    sc = cfg["scan"]
    lookback = sc.get("lookback_trading_days", 7)
    price_min, price_max = sc["price_min"], sc["price_max"]
    watch = sc.get("watch_threshold", 10.0)

    out = []
    for t, g in df.groupby("ticker"):
        g = g.sort_values("date").reset_index(drop=True)
        if len(g) < lookback + 2:
            continue
        c = g["c"]; v = g["v"]; o = g["o"]
        # 직전 (lookback-1)거래일 거래량 중앙값 = baseline (당일 제외 → shift(1))
        baseline = v.shift(1).rolling(max(2, lookback - 1)).median()
        c7 = c.shift(7)                  # 7거래일 전 종가
        next_o = o.shift(-1)             # 다음 거래일 시초
        next_c = c.shift(-1)             # 다음 거래일 종가
        ratio = v / baseline
        dollar_vol = v * c

        for i in range(len(g)):
            if pd.isna(baseline.iloc[i]) or baseline.iloc[i] <= 0:
                continue
            if pd.isna(c7.iloc[i]) or c7.iloc[i] <= 0:
                continue
            if pd.isna(next_o.iloc[i]) or next_o.iloc[i] <= 0:
                continue
            cl = c.iloc[i]
            # scanner 와 동일 필터
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

            prior7 = (cl / c7.iloc[i] - 1) * 100         # 직전 7거래일 상승률(%)
            fwd_oc = (next_c.iloc[i] - next_o.iloc[i]) / next_o.iloc[i] * 100  # 시초→종가
            fwd_cc = (next_c.iloc[i] - cl) / cl * 100    # 종가→종가(갭포함)
            out.append({"ticker": t, "date": g["date"].iloc[i],
                        "ratio": round(ratio.iloc[i], 1),
                        "prior7_%": round(prior7, 1),
                        "fwd_oc_%": round(fwd_oc, 1),
                        "fwd_cc_%": round(fwd_cc, 1),
                        "fwd_oc_net_%": round(fwd_oc - COST, 1)})
    return pd.DataFrame(out)


def cohort_table(cand, col="fwd_oc_net_%"):
    bins = [-1e9, 0, 25, 50, 100, 200, 1e9]
    labels = ["하락", "0~25%", "25~50%", "50~100%", "100~200%", "200%+"]
    cand = cand.copy()
    cand["코호트"] = pd.cut(cand["prior7_%"], bins=bins, labels=labels)
    rows = []
    for lab in labels:
        g = cand[cand["코호트"] == lab]
        if len(g) == 0:
            continue
        rows.append({"직전7일상승": lab, "표본수": len(g),
                     "시초→종가순익평균": round(g[col].mean(), 1),
                     "상승비율%": round((g[col] > 0).mean() * 100, 0),
                     "종가→종가평균": round(g["fwd_cc_%"].mean(), 1),
                     "중앙값순익": round(g[col].median(), 1)})
    return pd.DataFrame(rows)


def main():
    cfg = scanner.load_config()
    df = load_cache_long()
    ndates = df["date"].nunique()
    print(f"[데이터] 캐시 {ndates}거래일 ({df['date'].min()}~{df['date'].max()}), 전종목 {df['ticker'].nunique():,}개")
    cand = build_candidates(df, cfg)
    if cand.empty:
        sys.exit("후보 없음 — 캐시 일수가 부족하거나 필터가 과함.")

    out_path = os.path.join(scanner.OUTPUT_DIR, "prior_runup_analysis.csv")
    cand.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"[표본] 폭증 후보(ratio≥{cfg['scan']['watch_threshold']:.0f}) 신호×종목 = {len(cand)}건 "
          f"(look-ahead 없음, 다음날 시초→종가)")
    print(f"  직전7일상승률 분포: 중앙값 {cand['prior7_%'].median():+.0f}% | "
          f"100%+ {(cand['prior7_%']>=100).sum()}건({(cand['prior7_%']>=100).mean()*100:.0f}%)")
    print("\n" + "=" * 78)
    print("  직전 7거래일 상승률 코호트별 → 다음날 시초→종가 성과 (왕복비용 2.5% 차감)")
    print("=" * 78)
    tbl = cohort_table(cand)
    print(tbl.to_string(index=False))
    print("-" * 78)

    # 가설 직접 검정: 100%+ vs 100%미만
    hi = cand[cand["prior7_%"] >= 100]["fwd_oc_net_%"]
    lo = cand[cand["prior7_%"] < 100]["fwd_oc_net_%"]
    print(f"  [가설검정] 직전 100%+ 상승 n={len(hi)}: 순익평균 {hi.mean():+.1f}% / 상승 {(hi>0).mean()*100:.0f}%")
    print(f"            직전 100%미만  n={len(lo)}: 순익평균 {lo.mean():+.1f}% / 상승 {(lo>0).mean()*100:.0f}%")
    diff = hi.mean() - lo.mean()
    print(f"            차이(100%+ - 100%미만): {diff:+.1f}%p", end="")
    # 간이 t검정(독립표본, 등분산 가정 없이 Welch 근사)
    if len(hi) > 1 and len(lo) > 1:
        import math
        se = math.sqrt(hi.var()/len(hi) + lo.var()/len(lo))
        t = diff / se if se > 0 else 0
        print(f"  | Welch t≈{t:+.2f} (|t|≥2면 유의 추정)")
    else:
        print()
    print(f"\n  상세 CSV: {out_path}")


if __name__ == "__main__":
    main()

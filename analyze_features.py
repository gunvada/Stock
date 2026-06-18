# -*- coding: utf-8 -*-
"""
후보 특성별 다음날 수익률 변별력 분석  (Feature → Forward Return)
==================================================================
"캔들 신호 외에, 어떤 통계적 기준을 추가하면 수익률 높은 폭증주를 선별할 수
있나"를 데이터로 검증한다. 각 후보(scanner 필터 동일, ratio≥watch)에 대해
신호일 D 의 여러 특성을 계산하고, 특성을 5분위로 나눠 다음날 시초→종가
순익(왕복비용 차감)이 단조적으로 갈리는지 본다.

look-ahead 없음(특성은 모두 D 시점까지의 정보, 성과는 D+1 시초→종가).
데이터: output/cache/grouped_*.json (API 무호출).

사용법: python analyze_features.py
"""
import os
import sys

import numpy as np
import pandas as pd

import scanner
from analyze_prior_runup import load_cache_long, COST


FEATURES = [
    ("ratio",            "거래량폭증배율"),
    ("dollar_surge_x",   "거래대금폭증배율"),
    ("avg_dollar_vol_M", "직전10일평균거래대금($M)"),
    ("dollar_vol_M",     "당일거래대금($M)"),
    ("intraday_chg_%",   "당일시초→종가(%)"),
    ("gap_%",            "당일갭(전일종가대비시초,%)"),
    ("close_pos",        "당일마감강도(0~1)"),
    ("range_%",          "당일변동폭(고저/시초,%)"),
    ("price",            "주가($)"),
    ("prior7_%",         "직전7거래일상승률(%)"),
    ("up_streak",        "연속상승일수"),
]


def build_features(df, cfg):
    sc = cfg["scan"]
    lookback = sc.get("lookback_trading_days", 7)
    dol_days = sc.get("dollar_baseline_days", 10)
    price_min, price_max = sc["price_min"], sc["price_max"]
    watch = sc.get("watch_threshold", 10.0)

    out = []
    for t, g in df.groupby("ticker"):
        g = g.sort_values("date").reset_index(drop=True)
        if len(g) < lookback + 2:
            continue
        o, h, l, c, v = g["o"], g["h"], g["l"], g["c"], g["v"]
        baseline = v.shift(1).rolling(max(2, lookback - 1)).median()
        c7 = c.shift(7)
        prev_c = c.shift(1)
        next_o = o.shift(-1)
        next_c = c.shift(-1)
        ratio = v / baseline
        dollar_vol = v * c
        # 직전 dol_days 평균 거래대금
        dol_series = (v * c)
        avg_dollar = dol_series.shift(1).rolling(dol_days).mean()
        # 연속 상승일수(당일 포함, 종가>전일종가 연속)
        up = (c > prev_c).astype(float)
        streak = up.copy()
        run = 0
        streak_vals = []
        for val in up:
            run = run + 1 if val == 1 else 0
            streak_vals.append(run)
        streak = pd.Series(streak_vals, index=up.index)

        for i in range(len(g)):
            if pd.isna(baseline.iloc[i]) or baseline.iloc[i] <= 0:
                continue
            if pd.isna(c7.iloc[i]) or c7.iloc[i] <= 0:
                continue
            if pd.isna(next_o.iloc[i]) or next_o.iloc[i] <= 0:
                continue
            if pd.isna(prev_c.iloc[i]) or prev_c.iloc[i] <= 0:
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

            rng = h.iloc[i] - l.iloc[i]
            avgd = avg_dollar.iloc[i] if not pd.isna(avg_dollar.iloc[i]) else np.nan
            row = {
                "ticker": t, "date": g["date"].iloc[i],
                "ratio": ratio.iloc[i],
                "dollar_surge_x": (dollar_vol.iloc[i] / avgd) if avgd and avgd > 0 else np.nan,
                "avg_dollar_vol_M": avgd / 1e6 if avgd else np.nan,
                "dollar_vol_M": dollar_vol.iloc[i] / 1e6,
                "intraday_chg_%": (cl - o.iloc[i]) / o.iloc[i] * 100 if o.iloc[i] else np.nan,
                "gap_%": (o.iloc[i] - prev_c.iloc[i]) / prev_c.iloc[i] * 100,
                "close_pos": (cl - l.iloc[i]) / rng if rng > 0 else np.nan,
                "range_%": rng / o.iloc[i] * 100 if o.iloc[i] else np.nan,
                "price": cl,
                "prior7_%": (cl / c7.iloc[i] - 1) * 100,
                "up_streak": streak.iloc[i],
                "fwd_oc_net_%": (next_c.iloc[i] - next_o.iloc[i]) / next_o.iloc[i] * 100 - COST,
            }
            out.append(row)
    return pd.DataFrame(out)


def quintile_table(cand, feat):
    s = cand[[feat, "fwd_oc_net_%"]].dropna()
    if len(s) < 25:
        return None
    try:
        s = s.copy()
        s["q"] = pd.qcut(s[feat].rank(method="first"), 5, labels=["Q1(저)", "Q2", "Q3", "Q4", "Q5(고)"])
    except Exception:
        return None
    rows = []
    for q in ["Q1(저)", "Q2", "Q3", "Q4", "Q5(고)"]:
        gg = s[s["q"] == q]
        rows.append((q, len(gg), round(gg[feat].median(), 2),
                     round(gg["fwd_oc_net_%"].mean(), 1),
                     round((gg["fwd_oc_net_%"] > 0).mean() * 100)))
    spread = rows[-1][3] - rows[0][3]
    corr = s[feat].corr(s["fwd_oc_net_%"])
    return rows, spread, corr


def main():
    cfg = scanner.load_config()
    df = load_cache_long()
    cand = build_features(df, cfg)
    if cand.empty:
        sys.exit("후보 없음.")
    out_path = os.path.join(scanner.OUTPUT_DIR, "feature_analysis.csv")
    cand.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"[표본] {len(cand)}건 (폭증후보 ratio≥{cfg['scan']['watch_threshold']:.0f}, "
          f"다음날 시초→종가 순익, 비용 {COST}%)")
    print(f"  전체 순익평균 {cand['fwd_oc_net_%'].mean():+.1f}% | 상승 {(cand['fwd_oc_net_%']>0).mean()*100:.0f}%\n")

    # 변별력 순으로 정렬해 요약
    summ = []
    for feat, kor in FEATURES:
        r = quintile_table(cand, feat)
        if r is None:
            continue
        rows, spread, corr = r
        summ.append((abs(spread), feat, kor, spread, corr, rows))

    summ.sort(reverse=True)
    print("=" * 80)
    print("  특성별 5분위 변별력 (Q5고분위 순익 − Q1저분위 순익 = 스프레드, 클수록 변별력↑)")
    print("=" * 80)
    print(f"{'특성':<24}{'스프레드':>9}{'상관계수':>9}   Q1→Q5 순익평균(%)")
    print("-" * 80)
    for _, feat, kor, spread, corr, rows in summ:
        means = "  ".join(f"{m:+.0f}" for (_, _, _, m, _) in rows)
        print(f"{kor:<22}{spread:>+9.1f}{corr:>+9.2f}   {means}")

    print("\n" + "=" * 80)
    print("  상위 변별 특성 상세 (5분위별 표본수·순익·상승률)")
    print("=" * 80)
    for _, feat, kor, spread, corr, rows in summ[:4]:
        print(f"\n● {kor}  (스프레드 {spread:+.1f}%p, 상관 {corr:+.2f})")
        print(f"   {'분위':<8}{'표본':>5}{'중앙값':>9}{'순익평균':>9}{'상승%':>7}")
        for q, n, med, mean, win in rows:
            print(f"   {q:<8}{n:>5}{med:>9.2f}{mean:>+8.1f}%{win:>6.0f}%")
    print(f"\n  상세 CSV: {out_path}")


if __name__ == "__main__":
    main()

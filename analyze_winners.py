# -*- coding: utf-8 -*-
"""
'프리마켓 급등 → 본장에서도 꾸준히 상승' 패턴 분석
------------------------------------------------------
일봉 OHLCV 로 다음을 프록시한다:
  프리마켓 급등  ≈ gap = (시초가 - 전일종가)/전일종가
  본장 꾸준 상승 ≈ open→close (+)  AND  종가가 당일 고가 근처(close_pos 높음)

15거래일치에서 위 패턴 종목을 뽑아 상위 ~10개의 공통점을 정리한다.
(grouped daily 응답을 output/cache 에 저장 → 재실행 시 API 재호출 없음)
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

CACHE_DIR = os.path.join(scanner.OUTPUT_DIR, "cache")

# 패턴 임계값
GAP_MIN = 10.0       # 프리마켓(갭) 최소 상승 %
OC_MIN = 3.0         # 본장 시초가→종가 최소 상승 %
CLOSE_POS_MIN = 0.6  # 종가가 당일 레인지 상위 40% 안 (강하게 마감)
TOP_N = 10


def cached_grouped(ds, cfg, session):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"grouped_{ds}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    res = scanner.fetch_grouped_day(ds, cfg["polygon_api_key"], session,
                                    cfg["scan"].get("rate_sleep_seconds", 13))
    if res:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(res, f)
    return res


def build_panel(cfg, session, n_calendar=21):
    import datetime as dt
    collected = {}
    cursor = dt.date.today() - dt.timedelta(days=1)
    n_fetch = 0
    print(f"[1/3] 데이터 로드(캐시 우선)...")
    for _ in range(n_calendar):
        if cursor.weekday() < 5:
            ds = cursor.isoformat()
            res = cached_grouped(ds, cfg, session)
            if res:
                collected[ds] = res
                n_fetch += 1
        cursor -= dt.timedelta(days=1)
    rows = []
    for ds, results in collected.items():
        for it in results:
            rows.append({"ticker": it.get("T"), "date": ds,
                         "o": it.get("o", 0) or 0, "h": it.get("h", 0) or 0,
                         "l": it.get("l", 0) or 0, "c": it.get("c", 0) or 0,
                         "v": it.get("v", 0) or 0})
    df = pd.DataFrame(rows).dropna(subset=["ticker"]).sort_values(["ticker", "date"])
    print(f"      {df['date'].nunique()} 거래일 / {df['ticker'].nunique():,} 종목")
    return df


def main():
    cfg = scanner.load_config()
    sc = cfg["scan"]
    session = requests.Session()
    df = build_panel(cfg, session)

    print("[2/3] 갭/장중/마감강도/거래량 지표 계산...")
    g = df.groupby("ticker")
    df["prev_close"] = g["c"].shift(1)
    df["base_vol"] = g["v"].transform(lambda s: s.shift(1).rolling(7, min_periods=3).median())
    df = df.dropna(subset=["prev_close", "base_vol"])
    df = df[(df["prev_close"] > 0) & (df["base_vol"] > 0) & (df["o"] > 0) & (df["h"] > df["l"])]

    df["gap_%"] = (df["o"] - df["prev_close"]) / df["prev_close"] * 100
    df["oc_%"] = (df["c"] - df["o"]) / df["o"] * 100
    df["total_%"] = (df["c"] - df["prev_close"]) / df["prev_close"] * 100
    df["close_pos"] = (df["c"] - df["l"]) / (df["h"] - df["l"])
    df["vol_ratio"] = df["v"] / df["base_vol"]
    df["dollar_M"] = df["v"] * df["c"] / 1e6

    # 소형/페니 유니버스 필터 (scanner 와 동일 취지)
    uni = df[(df["c"].between(sc["price_min"], sc["price_max"]))
             & (df["v"] >= sc["min_latest_volume"])
             & (df["dollar_M"] >= sc["min_latest_dollar_volume"] / 1e6)
             & (df["base_vol"] >= sc["min_baseline_avg_volume"])]

    # 패턴: 프리마켓 급등 + 본장 꾸준 상승 + 강하게 마감
    win = uni[(uni["gap_%"] >= GAP_MIN) & (uni["oc_%"] >= OC_MIN)
              & (uni["close_pos"] >= CLOSE_POS_MIN)].copy()
    # 랭킹: 본장 상승 + 마감강도 (갭만 큰 게 아니라 본장에서도 끌고간 종목 우대)
    win["score"] = win["oc_%"] + win["close_pos"] * 20
    win = win.sort_values("score", ascending=False).head(TOP_N)

    cols = ["date", "ticker", "prev_close", "o", "c", "gap_%", "oc_%",
            "total_%", "close_pos", "vol_ratio", "dollar_M"]
    show = win[cols].copy()
    for c in ["prev_close", "o", "c"]:
        show[c] = show[c].round(3)
    for c in ["gap_%", "oc_%", "total_%", "vol_ratio", "dollar_M"]:
        show[c] = show[c].round(1)
    show["close_pos"] = show["close_pos"].round(2)

    out = os.path.join(scanner.OUTPUT_DIR, "winners.csv")
    show.to_csv(out, index=False, encoding="utf-8-sig")

    print("[3/3] 결과\n")
    print("=" * 92)
    print(f"  패턴: 갭(프리마켓)≥{GAP_MIN:.0f}% + 본장 시초가→종가≥{OC_MIN:.0f}% + 종가 레인지상위(close_pos≥{CLOSE_POS_MIN})")
    print(f"  표본 유니버스 {len(uni):,}건 중 패턴 충족 {len(win)}건 (상위 {TOP_N})")
    print("=" * 92)
    print(show.to_string(index=False))
    print("-" * 92)

    # 공통점 통계
    def med(c): return win[c].median()
    print("  [공통점 — 중앙값 기준]")
    print(f"    갭(프리마켓)    : {med('gap_%'):+.1f}%   (범위 {win['gap_%'].min():.0f}~{win['gap_%'].max():.0f}%)")
    print(f"    본장 시초→종가  : {med('oc_%'):+.1f}%")
    print(f"    하루 총상승     : {med('total_%'):+.1f}%")
    print(f"    마감강도        : {med('close_pos'):.2f}  (1.0=고점마감)")
    print(f"    거래량 폭증배율 : {med('vol_ratio'):.0f}배")
    print(f"    주가대          : ${win['c'].min():.2f}~${win['c'].max():.2f} (중앙 ${med('c'):.2f})")
    print(f"    거래대금        : 중앙 ${med('dollar_M'):.0f}M")
    print(f"    요일분포        : " + ", ".join(
        f"{k}:{v}" for k, v in win['date'].apply(
            lambda d: pd.Timestamp(d).day_name()[:3]).value_counts().items()))
    print("-" * 92)
    print(f"  저장: {out}")
    print("=" * 92)
    print("  ※ 일봉 프록시 분석. '장중 꾸준 상승'은 종가=고점근접으로 근사한 것이며,")
    print("    실제 분 단위 경로는 분봉으로 별도 확인해야 한다.")


if __name__ == "__main__":
    main()

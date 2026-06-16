# -*- coding: utf-8 -*-
"""
예측력 검증 (Predictive power test) — 사후선택 제거
------------------------------------------------------
'프리마켓에 알 수 있는 조건'만으로 모든 갭상승 종목을 거른 뒤,
시초가 매수 → 종가 매도(open→close) 했을 때의 성과를 전수 집계한다.
승자만 골라보는 survivorship 을 없애고 "이 필터가 실제로 통하는가"를 본다.

장 개장 전 알 수 있는 변수:
  - gap = (시초가 - 전일종가)/전일종가          (밤사이 갭 = 프리마켓 결과)
  - price = 전일종가                            (저가/고가)
  - prior_dollar = 직전7일 중앙거래량 × 전일종가  (유동성, 과거값이라 미래참조 없음)
진입 시점(시초가) 이후의 결과(종가)만 성과로 쓰므로 look-ahead 없음.
"""

import sys
from statistics import mean, median

import pandas as pd
import requests

import scanner
from analyze_winners import build_panel

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def stats(series):
    v = [x for x in series if pd.notna(x)]
    if not v:
        return None
    wins = [x for x in v if x > 0]
    big = [x for x in v if x >= 10]
    return {
        "n": len(v),
        "avg_%": round(mean(v), 1),
        "median_%": round(median(v), 1),
        "win_%": round(len(wins) / len(v) * 100, 0),
        ">=+10%_비율": round(len(big) / len(v) * 100, 0),
        "best": round(max(v), 0),
        "worst": round(min(v), 0),
    }


def main():
    cfg = scanner.load_config()
    df = build_panel(cfg, requests.Session())

    g = df.groupby("ticker")
    df["prev_close"] = g["c"].shift(1)
    df["base_vol"] = g["v"].transform(lambda s: s.shift(1).rolling(7, min_periods=3).median())
    df = df.dropna(subset=["prev_close", "base_vol"])
    df = df[(df["prev_close"] > 0) & (df["base_vol"] > 0) & (df["o"] > 0)]

    df["gap_%"] = (df["o"] - df["prev_close"]) / df["prev_close"] * 100
    df["oc_%"] = (df["c"] - df["o"]) / df["o"] * 100              # 진입 후 성과(실매매)
    df["prior_dollar_M"] = df["base_vol"] * df["prev_close"] / 1e6  # 사전 유동성(미래참조X)

    # 프리마켓 갭상승 종목 모집단: 저가 소형주 + 갭업 + 사전 유동성 확보
    pop = df[(df["prev_close"].between(0.3, 20))
             & (df["gap_%"] >= 10)
             & (df["prior_dollar_M"] >= 1.0)].copy()
    print(f"\n모집단(프리마켓 갭≥10% & 저가 & 유동성≥$1M): {len(pop):,} 건 (15거래일)\n")

    print("=" * 78)
    print("  [검증 1] 갭(프리마켓 상승) 구간별 → 시초가매수→종가 성과")
    print("=" * 78)
    bands = [(10, 20), (20, 40), (40, 80), (80, 10000)]
    rows = []
    for lo, hi in bands:
        s = stats(pop[(pop["gap_%"] >= lo) & (pop["gap_%"] < hi)]["oc_%"])
        if s:
            rows.append({"갭구간": f"{lo}~{hi if hi<10000 else '∞'}%", **s})
    print(pd.DataFrame(rows).to_string(index=False))
    print("  → 갭이 클수록 다음 본장 성과가 좋아지는가? (avg/win 추세 확인)")

    print("\n" + "=" * 78)
    print("  [검증 2] 가격대 영향 (갭 10~40% 모집단 내)")
    print("=" * 78)
    mid = pop[(pop["gap_%"] >= 10) & (pop["gap_%"] < 40)]
    prows = []
    for lo, hi, lab in [(0.3, 1, "$0.3~1"), (1, 3, "$1~3"), (3, 8, "$3~8"), (8, 20, "$8~20")]:
        s = stats(mid[(mid["prev_close"] >= lo) & (mid["prev_close"] < hi)]["oc_%"])
        if s:
            prows.append({"가격대": lab, **s})
    print(pd.DataFrame(prows).to_string(index=False))

    print("\n" + "=" * 78)
    print("  [검증 3] 유동성 영향 (갭 10~40% 모집단 내)")
    print("=" * 78)
    lrows = []
    for lo, hi, lab in [(1, 5, "$1~5M"), (5, 20, "$5~20M"), (20, 1e9, "$20M+")]:
        s = stats(mid[(mid["prior_dollar_M"] >= lo) & (mid["prior_dollar_M"] < hi)]["oc_%"])
        if s:
            lrows.append({"사전유동성": lab, **s})
    print(pd.DataFrame(lrows).to_string(index=False))

    print("\n" + "=" * 78)
    print("  [검증 4] 발굴 프로파일 필터  vs  극단 갭 필터")
    print("=" * 78)
    profile = pop[(pop["prev_close"].between(0.3, 3))
                  & (pop["gap_%"].between(15, 40))
                  & (pop["prior_dollar_M"] >= 3)]
    extreme = pop[pop["gap_%"] >= 80]
    cmp_rows = [
        {"필터": "발굴 프로파일($0.3~3 · 갭15~40% · 유동성$3M+)", **(stats(profile["oc_%"]) or {})},
        {"필터": "극단 갭(≥80%)", **(stats(extreme["oc_%"]) or {})},
        {"필터": "모집단 전체(갭≥10%)", **(stats(pop["oc_%"]) or {})},
    ]
    print(pd.DataFrame(cmp_rows).to_string(index=False))

    pop.to_csv(f"{scanner.OUTPUT_DIR}/predict_population.csv", index=False, encoding="utf-8-sig")
    print("\n" + "-" * 78)
    print(f"  저장: output/predict_population.csv ({len(pop)}건)")
    print("  ※ oc_% = 시초가 매수→종가 매도 (수수료·슬리피지 차감 전)")
    print("  ※ '발굴 프로파일'이 모집단/극단갭보다 평균·승률이 높아야 예측력 있다고 본다.")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
눌림목(흡수) 반등 스캐너 — 유일한 +엣지 전용
------------------------------------------------
검증된 필터로 '거래량 폭증 + 적당한 음봉(흡수)' 종목을 전 종목에서 추출한다.
이 셋업은 15일 백테스트에서 다음날 승률 60%, +10% 도달 57%, 기대값 +2.1%/거래.

추출 기준(전부 충족):
  1) 거래량 ≥ 10배 (직전 7거래일 중앙값 대비)
  2) 당일 시초→종가 -5% ~ -15% (적당한 음봉 = 흡수)
  3) 가격 $0.3 ~ $20 (저가 소형주)
  4) 거래대금 ≥ $2M (유동성)
  5) 파라볼릭 제외: 직전 2일 누적 +100% 미만 (천장 회피)

사용법: python pullback_scanner.py
출력 : 콘솔 랭킹 + output/pullback_<날짜>.csv (각 종목 매매플랜 포함)
"""
import os
import sys

import pandas as pd
import requests

import scanner
from analyze_winners import build_panel

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TP, STOP = 10.0, 8.0  # 익절/손절 %


def main():
    cfg = scanner.load_config()
    df = build_panel(cfg, requests.Session()).sort_values(["ticker", "date"])
    g = df.groupby("ticker")
    df["c_m2"] = g["c"].shift(2)
    df["base_vol"] = g["v"].transform(lambda s: s.shift(1).rolling(7, min_periods=3).median())
    df = df[(df["c"] > 0) & (df["base_vol"] > 0) & (df["o"] > 0) & (df["h"] > df["l"])]

    latest = df["date"].max()
    day = df[df["date"] == latest].copy()
    day["vol_ratio"] = day["v"] / day["base_vol"]
    day["oc_%"] = (day["c"] - day["o"]) / day["o"] * 100
    day["run2d_%"] = (day["c"] / day["c_m2"] - 1) * 100
    day["dol_M"] = day["v"] * day["c"] / 1e6
    day["close_pos"] = (day["c"] - day["l"]) / (day["h"] - day["l"])

    cand = day[(day["vol_ratio"] >= 10)
               & (day["oc_%"].between(-15, -5))
               & (day["c"].between(0.3, 20))
               & (day["dol_M"] >= 2)
               & (day["run2d_%"] < 100)].copy()

    # 매매 플랜
    cand["매수참고"] = cand["c"].round(3)          # 다음날 시초/VWAP회복 부근
    cand["손절"] = (cand["l"] * 0.97).round(3)      # 당일 저가 -3% 하회
    cand["익절목표"] = (cand["c"] * (1 + TP / 100)).round(3)
    cand = cand.sort_values("dol_M", ascending=False)

    cols_csv = ["ticker", "c", "oc_%", "vol_ratio", "dol_M", "run2d_%",
                "close_pos", "매수참고", "손절", "익절목표"]
    out = cand[cols_csv].copy()
    for c in ["oc_%", "vol_ratio", "dol_M", "run2d_%"]:
        out[c] = out[c].round(1)
    out["close_pos"] = out["close_pos"].round(2)
    path = os.path.join(scanner.OUTPUT_DIR, f"pullback_{latest}.csv")
    out.to_csv(path, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 92)
    print(f"  눌림목(흡수) 반등 후보  —  기준일 {latest}")
    print(f"  필터: 거래량≥10배 · 당일 -5~-15% 음봉 · $0.3~20 · 거래대금≥$2M · 파라볼릭제외")
    print("=" * 92)
    if out.empty:
        print("  조건 충족 종목 없음. (해당일에 흡수 셋업이 없었음 — 정상)")
    else:
        disp = out.rename(columns={"c": "종가", "oc_%": "당일%", "vol_ratio": "거래량배",
                                   "dol_M": "거래대금M", "run2d_%": "2일%", "close_pos": "마감강도"})
        print(disp.to_string(index=False))
        print("-" * 92)
        print(f"  {len(out)}개 추출.  과거 동일셋업 통계: 다음날 승률 60% · +10%도달 57% · 기대값 +2.1%/거래")
    print("-" * 92)
    print("  [매매 플랜]")
    print("   · 진입 : 다음 거래일 개장 후 VWAP 회복 + 거래량 동반 확인하고 매수참고가 부근")
    print(f"   · 익절 : +{TP:.0f}% 지정가 (익절목표 컬럼)")
    print(f"   · 손절 : 당일 저가 -3% 하회(손절 컬럼) 또는 -{STOP:.0f}%")
    print("   · 청산 : 종가 전 마감 (오버나잇 금지)")
    print(f"  저장: {path}")
    print("=" * 92)
    print("  ※ 15일 표본 기반. 실거래 전 60~90일 확대검증 권장. 매매·실행은 본인 판단.")


if __name__ == "__main__":
    main()

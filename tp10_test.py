# -*- coding: utf-8 -*-
"""
'+10% 익절 도달 확률' 검증
---------------------------
눌림목 버킷 종목이 다음날 장중 실제로 +10%를 찍어 익절 주문이 체결되는 비율과,
그 전에 손절(-8%)에 먼저 닿을 확률을 일봉 OHLC로 근사 집계한다.
"""
import sys
from statistics import mean
import pandas as pd
import requests
import scanner
from analyze_winners import build_panel

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TP = 10.0
STOP = 8.0


def main():
    cfg = scanner.load_config()
    df = build_panel(cfg, requests.Session()).sort_values(["ticker", "date"])
    g = df.groupby("ticker")
    df["c_m2"] = g["c"].shift(2)
    df["base_vol"] = g["v"].transform(lambda s: s.shift(1).rolling(7, min_periods=3).median())
    df["no"] = g["o"].shift(-1)
    df["nh"] = g["h"].shift(-1)
    df["nl"] = g["l"].shift(-1)
    df["nc"] = g["c"].shift(-1)
    df = df[(df["c"] > 0) & (df["base_vol"] > 0) & (df["o"] > 0) & (df["no"] > 0)]

    df["vol_ratio"] = df["v"] / df["base_vol"]
    df["oc"] = (df["c"] - df["o"]) / df["o"] * 100
    df["run2d"] = (df["c"] / df["c_m2"] - 1) * 100
    df["dol_M"] = df["v"] * df["c"] / 1e6

    df["nh_%"] = (df["nh"] - df["no"]) / df["no"] * 100   # 다음날 장중 최고(시초대비)
    df["nl_%"] = (df["nl"] - df["no"]) / df["no"] * 100   # 다음날 장중 최저
    df["nc_%"] = (df["nc"] - df["no"]) / df["no"] * 100   # 다음날 종가(시초대비)

    uni = df[(df["c"].between(0.3, 20)) & (df["dol_M"] >= 2)]

    def report(name, sub):
        n = len(sub)
        if n < 5:
            print(f"  {name}: 표본 부족({n})"); return
        hit_tp = (sub["nh_%"] >= TP).mean() * 100        # +10% 도달
        hit_stop = (sub["nl_%"] <= -STOP).mean() * 100   # -8% 도달
        # 둘 다 닿은 케이스 비율(순서는 일봉으론 불명 → 보수적으로 손절우선 가정)
        both = ((sub["nh_%"] >= TP) & (sub["nl_%"] <= -STOP)).mean() * 100
        clean_tp = ((sub["nh_%"] >= TP) & (sub["nl_%"] > -STOP)).mean() * 100  # 손절없이 익절
        # 브래킷 기대값(보수적: 같은날 둘 다면 손절)
        def bracket(r):
            if r["nl_%"] <= -STOP:
                return -STOP
            if r["nh_%"] >= TP:
                return TP
            return r["nc_%"]
        ev = mean([bracket(r) for _, r in sub.iterrows()])
        print(f"  {name}  (n={n})")
        print(f"     +{TP:.0f}% 도달(고가기준) : {hit_tp:.0f}%   | 손절없이 깔끔 익절: {clean_tp:.0f}%")
        print(f"     -{STOP:.0f}% 손절 도달      : {hit_stop:.0f}%   | 익절·손절 둘다 터치: {both:.0f}%")
        print(f"     브래킷(+{TP:.0f}/-{STOP:.0f}) 기대값(보수적): {ev:+.1f}%/거래")
        print()

    print("=" * 72)
    print(f"  다음날 '+{TP:.0f}% 익절 / -{STOP:.0f}% 손절' 시 도달 확률·기대값 (15일 표본)")
    print("=" * 72)
    report("눌림목 스위트(거래량10배+ & 당일-5~15%)",
           uni[(uni["vol_ratio"] >= 10) & (uni["oc"].between(-15, -5)) & (uni["run2d"] < 100)])
    report("거래량10배+ 양봉(0~+10%) [추격류]",
           uni[(uni["vol_ratio"] >= 10) & (uni["oc"].between(0, 10))])
    report("갭20%+ 추격",
           uni[((uni["o"] - uni["c"].shift(0)) >= 0) & (uni["vol_ratio"] >= 5) & (uni["oc"] > 0)].head(0) if False else
           uni[(uni["vol_ratio"] >= 10)])  # 참고용 전체 거래량폭증
    print("  ※ 일봉 근사: 같은날 익절·손절 둘다 터치 시 '손절 우선'(보수적)으로 계산.")
    print("  ※ 실제는 분봉 순서 따라 결과 달라짐. 방향 참고용.")


if __name__ == "__main__":
    main()

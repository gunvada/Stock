# -*- coding: utf-8 -*-
"""
'N일 폭증 → 이후 하락/반등' 시퀀스 검증
-----------------------------------------
질문: 2일간 누적 +100% 폭증하면, 다음날 하락하고 그 다음 반등하나?
캐시된 15거래일 일봉으로 폭증 강도별 '이후 3일' 경로를 전수 집계.
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


def line(series):
    v = [x for x in series if pd.notna(x)]
    if len(v) < 3:
        return None
    w = [x for x in v if x > 0]
    return {"n": len(v), "평균%": round(mean(v), 1), "중앙%": round(median(v), 1),
            "상승비율%": round(len(w) / len(v) * 100, 0)}


def main():
    cfg = scanner.load_config()
    df = build_panel(cfg, requests.Session()).sort_values(["ticker", "date"])
    g = df.groupby("ticker")
    # 종가 시프트들
    df["c_m2"] = g["c"].shift(2)   # D-2 종가
    df["base_vol"] = g["v"].transform(lambda s: s.shift(1).rolling(7, min_periods=3).median())
    df["c_p1"] = g["c"].shift(-1)  # D+1
    df["c_p2"] = g["c"].shift(-2)  # D+2
    df["c_p3"] = g["c"].shift(-3)  # D+3
    df["o_p1"] = g["o"].shift(-1)
    df = df[(df["c"] > 0) & (df["c_m2"] > 0) & (df["base_vol"] > 0)]

    df["dol_M"] = df["v"] * df["c"] / 1e6
    df["run2d_%"] = (df["c"] / df["c_m2"] - 1) * 100        # 직전 2일 누적상승(D-2종가→D종가)
    df["vol_ratio"] = df["v"] / df["base_vol"]

    # D+1, D+2, D+3 일별 수익률(종가→종가)
    df["d1_%"] = (df["c_p1"] - df["c"]) / df["c"] * 100
    df["d2_%"] = (df["c_p2"] - df["c_p1"]) / df["c_p1"] * 100
    df["d3_%"] = (df["c_p3"] - df["c_p2"]) / df["c_p2"] * 100
    # 참고: D+1 본장만(시초→종가) — 갭 빼고
    df["d1_session_%"] = (df["c_p1"] - df["o_p1"]) / df["o_p1"] * 100

    uni = df[(df["c"].between(0.3, 20)) & (df["dol_M"] >= 2)]

    print("\n" + "=" * 90)
    print("  직전 2일 누적상승(run2d) 강도별 → 이후 일자별 종가→종가 수익률")
    print("=" * 90)
    rows = []
    for lo, hi, lab in [(30, 50, "+30~50%"), (50, 100, "+50~100%"),
                        (100, 200, "+100~200%"), (200, 1e9, "+200%↑")]:
        sub = uni[(uni["run2d_%"] >= lo) & (uni["run2d_%"] < hi)]
        d1, d2, d3 = line(sub["d1_%"]), line(sub["d2_%"]), line(sub["d3_%"])
        if d1:
            rows.append({
                "2일폭증": lab, "표본": d1["n"],
                "D+1평균": d1["평균%"], "D+1상승률": d1["상승비율%"],
                "D+2평균": d2["평균%"] if d2 else None, "D+2상승률": d2["상승비율%"] if d2 else None,
                "D+3평균": d3["평균%"] if d3 else None, "D+3상승률": d3["상승비율%"] if d3 else None,
            })
    print(pd.DataFrame(rows).to_string(index=False))
    print("  → 'D+1 하락 후 D+2 반등' 가설: D+1평균(-)이고 D+2평균(+)이면 성립")

    # 사용자의 정확한 시퀀스: 2일 100%+ 폭증한 종목들의 다음날 '하락한 것만' 추려 반등 보기
    print("\n" + "=" * 90)
    print("  [사용자 시퀀스] 2일 +100%↑ 폭증 → D+1 '실제로 하락한 종목'의 D+2 반등 여부")
    print("=" * 90)
    spike = uni[uni["run2d_%"] >= 100]
    dropped = spike[spike["d1_%"] < 0]
    print(f"  2일 +100%↑ 폭증: {len(spike)}건 → 그 중 D+1 하락: {len(dropped)}건 "
          f"(하락확률 {len(dropped)/max(len(spike),1)*100:.0f}%)")
    r = line(dropped["d2_%"])
    if r:
        print(f"  D+1 하락한 종목의 D+2: 평균 {r['평균%']:+.1f}%  중앙 {r['중앙%']:+.1f}%  반등(상승)비율 {r['상승비율%']:.0f}%  (n={r['n']})")
    else:
        print("  D+2 표본 부족(노이즈) — 15일 데이터로는 결론 불가")

    print("\n" + "=" * 90)
    print("  [눌림목 기준 명세] 발견①의 정확한 필터 = 다음날 본장(시초→종가) 성과")
    print("=" * 90)
    pull = uni[(uni["vol_ratio"] >= 10) & (uni["d1_%"].notna())]
    rows2 = []
    for lo, hi, lab in [(-30, -15, "당일 -30~-15%"), (-15, -5, "당일 -15~-5%"),
                        (-5, 0, "당일 -5~0%"), (0, 10, "당일 0~+10%")]:
        # 당일 시초→종가 기준 눌림
        oc = (uni["c"] - uni["o"]) / uni["o"] * 100
        sub = uni[(uni["vol_ratio"] >= 10) & (oc >= lo) & (oc < hi)]
        s = line(sub["d1_session_%"])
        if s:
            rows2.append({"거래량10배+ & 당일": lab, **s})
    print(pd.DataFrame(rows2).to_string(index=False))
    print("  → 'D+1 본장' = 다음날 시초가 매수→종가 매도 (갭 제외, 실거래 가능 구간)")


if __name__ == "__main__":
    main()

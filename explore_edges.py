# -*- coding: utf-8 -*-
"""
추가 엣지 탐색 (Edge mining) — '극단 갭=폭락' 외 다른 공통점 찾기
------------------------------------------------------------------
캐시된 15거래일 일봉으로 여러 가설을 전수 검증한다. 모두 사후선택 없이
'신호일에 알 수 있는 조건 → 그 다음/당일 결과'를 집계.
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


def st(series):
    v = [x for x in series if pd.notna(x)]
    if len(v) < 3:
        return None
    w = [x for x in v if x > 0]
    return {"n": len(v), "평균%": round(mean(v), 1), "중앙%": round(median(v), 1),
            "승률%": round(len(w) / len(v) * 100, 0),
            "최대익": round(max(v), 0), "최대손": round(min(v), 0)}


def show(title, rows):
    print("\n" + "=" * 80)
    print("  " + title)
    print("=" * 80)
    df = pd.DataFrame([r for r in rows if r])
    if df.empty:
        print("  표본 부족")
    else:
        print(df.to_string(index=False))


def main():
    cfg = scanner.load_config()
    df = build_panel(cfg, requests.Session())
    g = df.groupby("ticker")
    df["prev_close"] = g["c"].shift(1)
    df["base_vol"] = g["v"].transform(lambda s: s.shift(1).rolling(7, min_periods=3).median())
    df["next_o"] = g["o"].shift(-1)
    df["next_c"] = g["c"].shift(-1)
    df = df[(df["prev_close"] > 0) & (df["base_vol"] > 0) & (df["o"] > 0) & (df["h"] > df["l"])]

    df["gap_%"] = (df["o"] - df["prev_close"]) / df["prev_close"] * 100
    df["oc_%"] = (df["c"] - df["o"]) / df["o"] * 100
    df["close_pos"] = (df["c"] - df["l"]) / (df["h"] - df["l"])
    df["vol_ratio"] = df["v"] / df["base_vol"]
    df["dol_M"] = df["v"] * df["c"] / 1e6
    df["next_oc_%"] = (df["next_c"] - df["next_o"]) / df["next_o"] * 100  # 다음날 시초→종가
    df["next_gap_%"] = (df["next_o"] - df["c"]) / df["c"] * 100           # 다음날 갭

    # 거래 가능한 소형주 유니버스
    uni = df[(df["prev_close"].between(0.3, 20)) & (df["dol_M"] >= 2)].copy()

    # ── 가설 A: 당일 '강하게 마감(close_pos↑)'한 종목의 '다음날' 성과 ──
    rowsA = []
    for lo, hi, lab in [(0.0, 0.4, "약하게마감 <0.4"), (0.4, 0.7, "중간 0.4~0.7"),
                        (0.7, 1.01, "강하게마감 ≥0.7")]:
        sub = uni[(uni["oc_%"] > 0) & (uni["close_pos"] >= lo) & (uni["close_pos"] < hi)]
        rowsA.append({"당일마감강도": lab, "→다음날": "시초→종가", **(st(sub["next_oc_%"]) or {})})
    show("[A] 당일 강하게 마감한 상승종목 → 다음날 본장 성과 (모멘텀 지속?)", rowsA)

    # ── 가설 B: 당일 폭등(oc↑) 강도별 → 다음날 ──
    rowsB = []
    for lo, hi, lab in [(5, 15, "+5~15%"), (15, 30, "+15~30%"), (30, 60, "+30~60%"), (60, 1e9, "+60%↑")]:
        sub = uni[(uni["oc_%"] >= lo) & (uni["oc_%"] < hi)]
        rowsB.append({"당일상승": lab, **(st(sub["next_oc_%"]) or {})})
    show("[B] 당일 상승폭별 → 다음날 본장 성과 (이어가나 꺾이나)", rowsB)

    # ── 가설 C: 거래량 폭증 + 당일 급락(투매) → 다음날 반등? ──
    rowsC = []
    for lo, hi, lab in [(-100, -30, "급락 ≤-30%"), (-30, -15, "-30~-15%"), (-15, -5, "-15~-5%")]:
        sub = uni[(uni["vol_ratio"] >= 10) & (uni["oc_%"] >= lo) & (uni["oc_%"] < hi)]
        rowsC.append({"당일(거래량10배+)": lab, **(st(sub["next_oc_%"]) or {})})
    show("[C] 거래량 10배+ 폭증한 날 급락 → 다음날 반등하나 (역추세)", rowsC)

    # ── 가설 D: 당일 종가 위치(고가근접) + 다음날 '갭'까지 본 보유수익 ──
    rowsD = []
    strong = uni[(uni["oc_%"] > 5) & (uni["close_pos"] >= 0.7)]
    rowsD.append({"전략": "강마감 익일 시초→종가", **(st(strong["next_oc_%"]) or {})})
    rowsD.append({"전략": "강마감 익일 종가보유(갭포함)",
                  **(st(((strong["next_c"] - strong["c"]) / strong["c"] * 100)) or {})})
    show("[D] 강하게 마감 → 익일 갭까지 노린 오버나잇 보유 vs 본장만", rowsD)

    # ── 가설 E: 요일 효과 (갭≥15% 모집단) ──
    gap = uni[uni["gap_%"] >= 15].copy()
    gap["dow"] = gap["date"].apply(lambda d: pd.Timestamp(d).day_name()[:3])
    rowsE = []
    for d in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
        rowsE.append({"요일": d, **(st(gap[gap["dow"] == d]["oc_%"]) or {})})
    show("[E] 요일별 갭≥15% 종목 당일 시초→종가", rowsE)

    print("\n" + "-" * 80)
    print("  ※ 모두 거래가능 소형주($0.3~20, 거래대금≥$2M) 기준. 표본 작은 칸은 노이즈.")


if __name__ == "__main__":
    main()

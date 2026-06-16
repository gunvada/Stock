# -*- coding: utf-8 -*-
"""
눌림목(흡수) 반등 셋업 — 60~90일 확대 백테스트
------------------------------------------------------
pullback_scanner.py 와 '완전히 동일한 추출 필터'를 과거 전 구간에 적용해
다음 거래일 성과를 look-ahead(미래참조) 없이 채점한다.

신호일 D  : 눌림목 셋업 충족일 (거래량≥10배 · 당일 -5~-15% 음봉 · $0.3~20 ·
            거래대금≥$2M · 직전2일 누적<+100%)
매매일 D+1 : 다음 거래일. 진입 = 시초가(open). 두 가지 시나리오로 채점:
  (1) 종가청산   : (종가-시초)/시초                      ← 오버나잇 없이 종가 매도
  (2) TP/SL 플랜 : 장중 저가 ≤ -8% → -8% / 고가 ≥ +10% → +10% / 그 외 종가청산
                   (보수적: 같은 날 둘 다 닿으면 손절 우선 가정)

데이터: scanner.fetch_grouped_day(grouped daily, 전종목 하루치 1콜) + 캐시.
        한 번 받은 날짜는 output/cache/ 에 저장되어 재실행 시 API 재호출 없음.

사용법: python pullback_backtest.py [n_calendar_days=95]
출력  : 콘솔 요약 + output/pullback_backtest_summary.csv (신호일별)
                  + output/pullback_backtest_detail.csv  (거래별)
"""
import os
import sys
from statistics import mean, median

import requests
import pandas as pd

import scanner
from analyze_winners import build_panel  # 캐시 우선 grouped daily 로더 재사용

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TP, STOP = 10.0, 8.0  # 익절/손절 % (pullback_scanner 와 동일)


def main():
    n_calendar = int(sys.argv[1]) if len(sys.argv) > 1 else 95
    cfg = scanner.load_config()
    session = requests.Session()

    # 1) 데이터 로드 (캐시 우선). n_calendar 달력일 → 거래일 약 70%
    df = build_panel(cfg, session, n_calendar=n_calendar)
    df = df.sort_values(["ticker", "date"])

    # 2) pullback_scanner 와 동일한 파생지표
    g = df.groupby("ticker")
    df["c_m2"] = g["c"].shift(2)
    df["base_vol"] = g["v"].transform(
        lambda s: s.shift(1).rolling(7, min_periods=3).median())
    df = df[(df["c"] > 0) & (df["base_vol"] > 0) & (df["o"] > 0) & (df["h"] > df["l"])]

    df["vol_ratio"] = df["v"] / df["base_vol"]
    df["oc_%"] = (df["c"] - df["o"]) / df["o"] * 100
    df["run2d_%"] = (df["c"] / df["c_m2"] - 1) * 100
    df["dol_M"] = df["v"] * df["c"] / 1e6

    # 3) 신호(셋업) 후보 — pullback_scanner.main 과 동일 조건
    cand = df[(df["vol_ratio"] >= 10)
              & (df["oc_%"].between(-15, -5))
              & (df["c"].between(0.3, 20))
              & (df["dol_M"] >= 2)
              & (df["run2d_%"] < 100)].copy()

    dates = sorted(df["date"].unique())
    nxt = {d: dates[i + 1] for i, d in enumerate(dates[:-1])}  # 신호일 → 매매일
    # 매매일 OHLC 조회용
    trade_lookup = df.set_index(["ticker", "date"])[["o", "h", "l", "c"]]

    detail = []
    for _, r in cand.iterrows():
        sig_date, t = r["date"], r["ticker"]
        trade_date = nxt.get(sig_date)
        if trade_date is None or (t, trade_date) not in trade_lookup.index:
            continue  # 매매일 데이터 없음(가장 최근 신호일 등) → 채점 제외
        o, h, l, c = (float(x) for x in trade_lookup.loc[(t, trade_date)])
        if o <= 0:
            continue
        close_ret = (c - o) / o * 100                      # (1) 종가청산
        # (2) TP/SL 플랜 — 보수적: 손절 우선
        if l <= o * (1 - STOP / 100):
            plan_ret = -STOP
            exit_kind = "손절"
        elif h >= o * (1 + TP / 100):
            plan_ret = TP
            exit_kind = "익절"
        else:
            plan_ret = close_ret
            exit_kind = "종가"
        detail.append({
            "sig_date": sig_date, "trade_date": trade_date, "ticker": t,
            "vol_ratio": round(r["vol_ratio"], 1),
            "sig_oc_%": round(r["oc_%"], 1),
            "dol_M": round(r["dol_M"], 1),
            "close_exit_%": round(close_ret, 1),
            "plan_exit_%": round(plan_ret, 1),
            "exit": exit_kind,
        })

    det = pd.DataFrame(detail)
    out_dir = scanner.OUTPUT_DIR
    if det.empty:
        print("신호 후보가 채점 가능한 구간에 없습니다. n_calendar 를 늘려보세요.")
        det.to_csv(f"{out_dir}/pullback_backtest_detail.csv",
                   index=False, encoding="utf-8-sig")
        return

    # 4) 신호일별 요약
    rows = []
    for sd, grp in det.groupby("sig_date"):
        ce = grp["close_exit_%"].tolist()
        rows.append({
            "sig_date": sd,
            "trade_date": grp["trade_date"].iloc[0],
            "n": len(grp),
            "close_avg_%": round(mean(ce), 1),
            "close_win_%": round(sum(1 for x in ce if x > 0) / len(ce) * 100, 0),
            "plan_avg_%": round(mean(grp["plan_exit_%"]), 1),
        })
    summ = pd.DataFrame(rows).sort_values("sig_date")
    det.to_csv(f"{out_dir}/pullback_backtest_detail.csv",
               index=False, encoding="utf-8-sig")
    summ.to_csv(f"{out_dir}/pullback_backtest_summary.csv",
                index=False, encoding="utf-8-sig")

    # 5) 종합 통계
    def stats(col):
        v = det[col].tolist()
        w = [x for x in v if x > 0]
        return (len(v), mean(v), median(v),
                len(w) / len(v) * 100,
                sum(1 for x in v if x >= TP) / len(v) * 100,  # +TP% 도달률
                max(v), min(v))

    span = f"{det['sig_date'].min()} ~ {det['sig_date'].max()}"
    print("\n" + "=" * 84)
    print(f"  눌림목(흡수) 셋업 확대 백테스트   기간: {span}")
    print(f"  신호일 {summ['sig_date'].nunique()}일 · 총 거래 {len(det)}건 "
          f"(진입=다음날 시초가, 오버나잇 없음)")
    print("=" * 84)
    for label, col in [("[종가청산 시나리오]", "close_exit_%"),
                       (f"[TP+{TP:.0f}%/SL-{STOP:.0f}% 플랜 시나리오]", "plan_exit_%")]:
        n, avg, med, wr, tph, best, worst = stats(col)
        print(f"  {label}")
        print(f"    표본 {n}건 · 승률 {wr:.0f}% · +{TP:.0f}%도달 {tph:.0f}% · "
              f"기대값 {avg:+.1f}%/거래 (중앙 {med:+.1f}%)")
        print(f"    최고 {best:+.1f}% / 최저 {worst:+.1f}%")
    print("-" * 84)
    print(f"  저장: {out_dir}/pullback_backtest_summary.csv , pullback_backtest_detail.csv")
    print("=" * 84)
    print("  ※ 일봉 근사: 진입은 시초가, TP/SL은 당일 고가/저가 도달로 판정(체결가·VWAP회복")
    print("    조건·장중 경로는 미반영). 같은 날 고저 모두 닿으면 손절 우선(보수적).")
    print("  ※ 페니/소형주 특성상 슬리피지·유동성 위험이 실제로는 추가된다. 참고용 통계.")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
거래량 폭증주 백테스트 (Volume Surge Backtest)
----------------------------------------------------
"폭증을 장 마감 후 발견 → 다음 날 시초가 매수 → 그날 종가 매도" 전략의
실제 성과를 look-ahead(미래 참조) 없이 검증한다.

신호일 D : 거래량이 직전 N거래일 중앙값 대비 임계배율 이상 폭증한 날
매매일 D+1 : 다음 거래일. 수익률 = (종가 - 시초가) / 시초가   ← 실제로 먹는 값
참고용 : D+1 종가 / D 종가 (갭 포함 보유 수익률)

scanner.py 와 동일한 가격/거래량 필터를 적용하므로 결과는 트래커 후보와 일치한다.
"""

import sys
import time
import datetime as dt
from statistics import median, mean

import requests
import pandas as pd

import scanner  # load_config, fetch_grouped_day 재사용

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def fetch_window(cfg, session, n_calendar_days):
    """최근 n_calendar_days 달력일 안의 모든 거래일 grouped daily 를 모은다."""
    api_key = cfg["polygon_api_key"]
    rate_sleep = cfg["scan"].get("rate_sleep_seconds", 13)
    collected = {}
    cursor = dt.date.today() - dt.timedelta(days=1)
    print(f"[1/2] Polygon 데이터 수집 (최근 {n_calendar_days}일 범위)...")
    for _ in range(n_calendar_days):
        if cursor.weekday() < 5:
            ds = cursor.isoformat()
            res = scanner.fetch_grouped_day(ds, api_key, session, rate_sleep)
            if res:
                collected[ds] = res
                print(f"  [{ds}] {len(res):,} 종목  (누적 {len(collected)} 거래일)")
        cursor -= dt.timedelta(days=1)
    return collected


def to_panel(collected):
    rows = []
    for ds, results in collected.items():
        for it in results:
            rows.append({
                "ticker": it.get("T"), "date": ds,
                "v": it.get("v", 0) or 0, "o": it.get("o", 0) or 0,
                "c": it.get("c", 0) or 0,
            })
    df = pd.DataFrame(rows).dropna(subset=["ticker"])
    return df


def candidates_for_day(df, dates, i, cfg):
    """신호일 dates[i] 의 폭증 후보 목록 반환."""
    sc = cfg["scan"]
    look = sc["lookback_trading_days"]
    sig_date = dates[i]
    base_dates = dates[i - look:i]

    sig = df[df["date"] == sig_date].set_index("ticker")
    base = df[df["date"].isin(base_dates)]
    base_med = base.groupby("ticker")["v"].median()

    out = []
    for t, row in sig.iterrows():
        if t not in base_med.index:
            continue
        b = base_med[t]
        if b < sc["min_baseline_avg_volume"] or b <= 0:
            continue
        vol, close = float(row["v"]), float(row["c"])
        if not (sc["price_min"] <= close <= sc["price_max"]):
            continue
        if vol < sc["min_latest_volume"]:
            continue
        if vol * close < sc["min_latest_dollar_volume"]:
            continue
        ratio = vol / b
        if ratio < sc["watch_threshold"]:
            continue
        out.append({"ticker": t, "ratio": ratio, "sig_close": close})
    return out


def main():
    cfg = scanner.load_config()
    session = requests.Session()
    look = cfg["scan"]["lookback_trading_days"]

    # 신호일 5개 + 베이스라인 7일 + 매매일 1일 확보용 여유
    collected = fetch_window(cfg, session, look + 14)
    df = to_panel(collected)
    dates = sorted(df["date"].unique())
    if len(dates) < look + 2:
        sys.exit("[오류] 거래일 데이터 부족.")

    print("[2/2] 신호일별 다음날 성과 계산...")
    daily_summ = []
    detail_rows = []
    # i: 신호일 인덱스. 베이스라인(look일)과 매매일(i+1)이 모두 있어야 함
    for i in range(look, len(dates) - 1):
        sig_date, trade_date = dates[i], dates[i + 1]
        cands = candidates_for_day(df, dates, i, cfg)
        if not cands:
            continue
        trade = df[df["date"] == trade_date].set_index("ticker")

        rets = []
        for c in cands:
            t = c["ticker"]
            if t not in trade.index:
                continue
            tr = trade.loc[t]
            o, cl = float(tr["o"]), float(tr["c"])
            if o <= 0:
                continue
            oc = (cl - o) / o * 100                       # 시초가→종가 (실매매)
            cc = (cl - c["sig_close"]) / c["sig_close"] * 100  # 전일종가→종가 (갭포함)
            rets.append(oc)
            detail_rows.append({
                "sig_date": sig_date, "trade_date": trade_date, "ticker": t,
                "ratio": round(c["ratio"], 1),
                "open_to_close_%": round(oc, 1),
                "prevclose_to_close_%": round(cc, 1),
            })
        if not rets:
            continue
        wins = [r for r in rets if r > 0]
        daily_summ.append({
            "sig_date": sig_date, "trade_date": trade_date,
            "n": len(rets),
            "avg_%": round(mean(rets), 1),
            "median_%": round(median(rets), 1),
            "win_rate_%": round(len(wins) / len(rets) * 100, 0),
            "best_%": round(max(rets), 1),
            "worst_%": round(min(rets), 1),
        })

    summ = pd.DataFrame(daily_summ)
    detail = pd.DataFrame(detail_rows)
    scanner_out = scanner.OUTPUT_DIR
    detail.to_csv(f"{scanner_out}/backtest_detail.csv", index=False, encoding="utf-8-sig")
    summ.to_csv(f"{scanner_out}/backtest_summary.csv", index=False, encoding="utf-8-sig")

    print("\n" + "=" * 80)
    print("  백테스트: 폭증 다음날 '시초가 매수 → 종가 매도' 성과")
    print(f"  필터: 거래량 ≥{cfg['scan']['watch_threshold']:.0f}배, "
          f"가격 ${cfg['scan']['price_min']}~${cfg['scan']['price_max']}")
    print("=" * 80)
    if summ.empty:
        print("  신호 후보가 없습니다. 임계값을 낮추거나 데이터 범위를 늘리세요.")
        return
    print(summ.to_string(index=False))
    print("-" * 80)

    all_oc = detail["open_to_close_%"].tolist()
    wins = [r for r in all_oc if r > 0]
    print("  [전체 종합]")
    print(f"    표본(종목×일) : {len(all_oc)}")
    print(f"    평균 수익률   : {mean(all_oc):+.1f}%   (중앙값 {median(all_oc):+.1f}%)")
    print(f"    승률          : {len(wins)/len(all_oc)*100:.0f}%")
    print(f"    최고 / 최저   : {max(all_oc):+.1f}% / {min(all_oc):+.1f}%")
    print("-" * 80)

    # 가장 최근 신호일 상세
    last_sig = detail["sig_date"].max()
    recent = detail[detail["sig_date"] == last_sig].sort_values("open_to_close_%", ascending=False)
    print(f"  [최근 신호일 {last_sig} → 매매일 상세]")
    print(recent.to_string(index=False))
    print("-" * 80)
    print(f"  저장: {scanner_out}/backtest_summary.csv , backtest_detail.csv")
    print("=" * 80)
    print("  ※ open_to_close = 다음날 시초가 매수→종가 매도 (실제 따먹기 수익률)")
    print("  ※ 갭상승분(전일종가→시초가)은 이미 매수가에 반영되어 못 먹는 구간이다.")


if __name__ == "__main__":
    main()

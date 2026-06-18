# -*- coding: utf-8 -*-
"""
프리마켓→개장 윈도우 시뮬레이션 (KST 18:30 매수 → 22:30 매도)
===============================================================
어제 종가 기준 본장 Top5 픽을, 다음 거래일 **ET 05:30 매수 → 09:30(개장) 매도**
(= KST 18:30 → 22:30, 회원 매매창1)로 시뮬해 거래내역 장부에 매일 누적한다.
데이터 비교상 '프리마켓 상승 → 개장 투매' 패턴 때문에 개장 전 청산이 유리.
데이터: yfinance 5분봉(prepost, 최근 ~60일). API 키 불필요.

픽 파일(pullback_<신호일>.csv)별로 '매매일(다음 거래일) 데이터가 풀린 것'을
자동 감지·채점하고 output/window_sim_ledger.csv 에 누적(이미 채점분은 스킵).

사용법: python window_sim.py
"""
import os
import re
import sys
import glob
import datetime as dt

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
LEDGER = os.path.join(OUT, "window_sim_ledger.csv")
TOP_N = 5
COST = 1.0            # 왕복 비용 가정(%) — 프리마켓 스프레드(표시용, net 컬럼)
ENTRY_T, EXIT_T = "05:30", "09:30"   # ET (= KST 18:30 매수 / 22:30 개장 매도, EDT)


def window_prices(bars):
    """bars: [(hhmm, open), ...] 05:30~09:30 5분봉(prepost, 시간순).
    반환: (entry=05:30 프리마켓 시가, exit=09:30 개장 시가). 부족하면 None. 순수 함수."""
    if len(bars) < 2:
        return None
    entry = bars[0][1]
    exit_ = bars[-1][1]
    if entry is None or entry <= 0:
        return None
    return entry, exit_


def fetch_window(ticker, date):
    """해당일 09:30~10:30 5분봉 [(hhmm, open)] (NY tz). 없으면 []."""
    import yfinance as yf
    start = dt.date.fromisoformat(date)
    end = start + dt.timedelta(days=1)
    try:
        df = yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat(),
                                       interval="5m", prepost=True, auto_adjust=False)
    except Exception:
        return []
    if df is None or df.empty:
        return []
    df = df.set_index(df.index.tz_convert("America/New_York"))
    df = df[df.index.strftime("%Y-%m-%d") == date].between_time(ENTRY_T, EXIT_T)
    return [(t.strftime("%H:%M"), float(o)) for t, o in zip(df.index, df["Open"])]


def next_trading_date(sig):
    d = dt.date.fromisoformat(sig)
    for _ in range(5):
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            return d.isoformat()
    return None


def top_picks(path, n=TOP_N):
    df = pd.read_csv(path)
    if "dol_M" in df.columns:
        df = df.sort_values("dol_M", ascending=False)
    return list(df["ticker"].head(n))


def main():
    done = set()
    old = pd.DataFrame()
    if os.path.exists(LEDGER):
        old = pd.read_csv(LEDGER)
        done = set(old["signal_date"].astype(str))

    today = dt.date.today().isoformat()
    new_rows = []
    for path in sorted(glob.glob(os.path.join(OUT, "pullback_*.csv"))):
        sig = os.path.basename(path)[len("pullback_"):-len(".csv")]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", sig) or sig in done:
            continue
        trade = next_trading_date(sig)
        if not trade or trade >= today:
            print(f"[대기] {sig} → 매매일 {trade} 5분봉 아직 없음.")
            continue
        picks = top_picks(path)
        scored = []
        for t in picks:
            bars = fetch_window(t, trade)
            wp = window_prices(bars)
            if not wp:
                continue
            entry, exit_ = wp
            ret = (exit_ - entry) / entry * 100
            scored.append({"signal_date": sig, "trade_date": trade, "ticker": t,
                           "entry_0530": round(entry, 4), "exit_0930": round(exit_, 4),
                           "ret_%": round(ret, 2), "net_%": round(ret - COST, 2)})
        if not scored:
            print(f"[대기] {sig} → {trade} 프리마켓 5분봉 없음(조회 실패/데이터 미공개).")
            continue
        new_rows += scored
        d = pd.DataFrame(scored)
        print(f"[거래내역] {sig}픽 → {trade} 프리05:30→개장09:30 (Top{len(scored)})")
        for s in scored:
            print(f"     {s['ticker']:6s} 매수 {s['entry_0530']} → 매도 {s['exit_0930']}  "
                  f"{s['ret_%']:+.2f}% (net {s['net_%']:+.2f}%)")
        print(f"     ▶ 당일 평균 {d['ret_%'].mean():+.2f}% (net {d['net_%'].mean():+.2f}%) · "
              f"승 {(d['ret_%']>0).sum()}/{len(d)}")

    if new_rows:
        led = pd.concat([old, pd.DataFrame(new_rows)], ignore_index=True)
        led.to_csv(LEDGER, index=False, encoding="utf-8-sig")
        n = len(led)
        print("\n" + "=" * 70)
        print(f"  윈도우 시뮬 누적 (KST 18:30매수→22:30개장매도, 총 {n}거래)")
        print("=" * 70)
        print(f"  gross 평균 {led['ret_%'].mean():+.2f}% · net(비용{COST}%) {led['net_%'].mean():+.2f}%")
        print(f"  승률 {(led['ret_%']>0).mean()*100:.0f}% ({(led['ret_%']>0).sum()}/{n})")
        print(f"  장부: {LEDGER}")
    else:
        print("새로 채점할 픽 없음(모두 완료이거나 매매일 데이터 대기).")


if __name__ == "__main__":
    main()

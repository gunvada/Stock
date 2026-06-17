# -*- coding: utf-8 -*-
"""
프리마켓 픽 자동 채점  (본장 daily_verify 와 분리된 장부)
========================================================
output/premarket_<날짜>.csv 픽을, '그 날 프리마켓 창(ET 05:30–09:00)' 안에서
매수참고가 진입 → (창 안 +TP%/-STOP% 터치 or 창 마감 청산) 결과로 채점한다.
같은 날 고·저 둘 다 터치 시 보수적으로 손절 우선 가정. 왕복비용 2.5% 차감.

이미 채점한 날짜는 건너뛰고 output/premarket_ledger.csv 에 누적.
데이터: yfinance 1분봉(prepost). 과거 약 7일치까지 조회 가능.

사용법: python premarket_verify.py
"""
import os
import re
import sys
import glob
import datetime as dt

import pandas as pd

import scanner
from premarket_scanner import pm_config, PM_START, PM_END

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

COST = 2.5
LEDGER = os.path.join(scanner.OUTPUT_DIR, "premarket_ledger.csv")


def window_frame(ticker, date):
    """해당일 프리마켓 창(05:30–09:00 ET) 1분봉. 없으면 None."""
    import yfinance as yf
    start = dt.date.fromisoformat(date)
    end = start + dt.timedelta(days=1)
    df = yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat(),
                                   interval="1m", prepost=True, auto_adjust=False)
    if df.empty:
        return None
    df = df.set_index(df.index.tz_convert("America/New_York"))
    df = df[df.index.strftime("%Y-%m-%d") == date]
    w = df.between_time(PM_START, PM_END)
    return w if not w.empty else None


def main():
    cfg = scanner.load_config()
    pm = pm_config(cfg)
    TP, STOP = pm["tp_pct"], pm["stop_pct"]

    done = set()
    old = pd.DataFrame()
    if os.path.exists(LEDGER):
        old = pd.read_csv(LEDGER)
        done = set(old["date"].astype(str))

    today = dt.date.today().isoformat()
    new_rows = []
    for path in sorted(glob.glob(os.path.join(scanner.OUTPUT_DIR, "premarket_*.csv"))):
        date = os.path.basename(path)[len("premarket_"):-len(".csv")]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            continue  # premarket_ledger.csv 등 제외
        if date in done or date >= today:
            continue  # 이미 채점했거나, 창이 아직 안 끝난 당일
        picks = pd.read_csv(path)
        if picks.empty:
            continue

        scored = []
        for _, r in picks.iterrows():
            t = r["ticker"]
            entry = float(r["매수참고"])
            w = window_frame(t, date)
            if w is None or entry <= 0:
                continue
            hi, lo = float(w["High"].max()), float(w["Low"].min())
            end_px = float(w["Close"].iloc[-1])
            oc = (end_px - entry) / entry * 100
            hit_tp, hit_stop = hi >= entry * (1 + TP / 100), lo <= entry * (1 - STOP / 100)
            gross = -STOP if hit_stop else (TP if hit_tp else oc)
            scored.append({"date": date, "ticker": t, "entry": round(entry, 4),
                           "win_end": round(end_px, 4), "oc_%": round(oc, 1),
                           "hi_%": round((hi - entry) / entry * 100, 1),
                           "tp_hit": int(hit_tp), "stop_hit": int(hit_stop),
                           "net_%": round(gross - COST, 1)})
        if not scored:
            print(f"[대기] {date} — 프리마켓 창 데이터 없음(휴장/조회불가).")
            continue
        new_rows += scored
        d = pd.DataFrame(scored)
        print(f"[채점] {date}: {len(d)}종목 | 순익평균 {d['net_%'].mean():+.1f}% | "
              f"승 {(d['net_%']>0).sum()}/{len(d)} | 익절 {d['tp_hit'].sum()} | 손절 {d['stop_hit'].sum()}")
        for s in scored:
            print(f"     {s['ticker']:6s} 진입 {s['entry']} → 창마감 {s['win_end']} "
                  f"({s['oc_%']:+.1f}%, 창내최고 {s['hi_%']:+.1f}%) → 순익 {s['net_%']:+.1f}%")

    if new_rows:
        ledger = pd.concat([old, pd.DataFrame(new_rows)], ignore_index=True)
        ledger.to_csv(LEDGER, index=False, encoding="utf-8-sig")
        n = len(ledger)
        print("\n" + "=" * 70)
        print(f"  프리마켓 누적 성적 (총 {n}거래, 왕복비용 {COST}% 차감)")
        print("=" * 70)
        print(f"  순익 평균 : {ledger['net_%'].mean():+.2f}% / 거래")
        print(f"  승률      : {(ledger['net_%']>0).mean()*100:.0f}%  ({(ledger['net_%']>0).sum()}/{n})")
        print(f"  익절도달 : {ledger['tp_hit'].mean()*100:.0f}%  | 손절도달: {ledger['stop_hit'].mean()*100:.0f}%")
        print(f"  장부: {LEDGER}")
    else:
        print("새로 채점할 프리마켓 픽 없음(모두 완료이거나 데이터 대기 중).")


if __name__ == "__main__":
    main()

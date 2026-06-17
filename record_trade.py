# -*- coding: utf-8 -*-
"""
실매매 저널 (손절/익절 룰 없이 raw 기록·채점)
==============================================
회원이 실제 진입한 종목을 기록해두고, 매매일 데이터가 풀리면 '시초가 매수 →
종가 매도'(룰 없음, raw)로 자동 채점한다. output/manual_trades.csv 에 누적.
verify(룰적용)·window_sim(09:30~10:30)과 별개의 'raw 보유' 데이터 포인트.

사용법:
  python record_trade.py add AHMA BEEM --signal 2026-06-16 --trade 2026-06-17
  python record_trade.py score      # 매매일 지난 pending 건을 raw로 채점
"""
import os
import sys
import datetime as dt

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
JOURNAL = os.path.join(OUT, "manual_trades.csv")
COLS = ["logged", "signal_date", "trade_date", "ticker", "entry", "exit", "ret_%", "note"]


def _load():
    if os.path.exists(JOURNAL):
        return pd.read_csv(JOURNAL)
    return pd.DataFrame(columns=COLS)


def _save(df):
    os.makedirs(OUT, exist_ok=True)
    df.to_csv(JOURNAL, index=False, encoding="utf-8-sig")


def add(tickers, signal_date, trade_date, note="실매매(raw, 룰없음)"):
    df = _load()
    today = dt.date.today().isoformat()
    rows = [{"logged": today, "signal_date": signal_date, "trade_date": trade_date,
             "ticker": t, "entry": "", "exit": "", "ret_%": "", "note": note} for t in tickers]
    df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
    _save(df)
    print(f"기록됨: {', '.join(tickers)} (신호 {signal_date} → 매매 {trade_date})")
    print(df.to_string(index=False))


def score():
    df = _load()
    if df.empty:
        print("저널 비어있음."); return
    import yfinance as yf
    today = dt.date.today().isoformat()
    changed = 0
    for i, r in df.iterrows():
        if str(r.get("entry", "")) not in ("", "nan") or pd.notna(r.get("entry")) and r.get("entry") != "":
            continue  # 이미 채점
        td = str(r["trade_date"])
        if td >= today:
            print(f"[대기] {r['ticker']} 매매일 {td} 아직."); continue
        try:
            d = yf.Ticker(r["ticker"]).history(start=td, end=(dt.date.fromisoformat(td)+dt.timedelta(days=1)).isoformat(),
                                               interval="1d", auto_adjust=False)
        except Exception as e:
            print(f"[실패] {r['ticker']}: {e}"); continue
        if d is None or d.empty:
            print(f"[대기] {r['ticker']} {td} 데이터 없음."); continue
        o, c = float(d["Open"].iloc[0]), float(d["Close"].iloc[0])
        df.at[i, "entry"] = round(o, 4)
        df.at[i, "exit"] = round(c, 4)
        df.at[i, "ret_%"] = round((c - o) / o * 100, 2) if o > 0 else None
        changed += 1
        print(f"[채점] {r['ticker']} {td}: 시초 {o:.4f} → 종가 {c:.4f}  {(c-o)/o*100:+.2f}% (raw)")
    if changed:
        _save(df)
        done = df[df["ret_%"].astype(str).str.replace('.', '', 1).str.replace('-', '', 1).str.isdigit()]
        if not done.empty:
            rr = pd.to_numeric(done["ret_%"], errors="coerce").dropna()
            print(f"\n  누적 raw {len(rr)}거래 | 평균 {rr.mean():+.2f}% | 승률 {(rr>0).mean()*100:.0f}%")
    else:
        print("새로 채점할 건 없음.")


def main():
    a = sys.argv[1:]
    if not a:
        print(_load().to_string(index=False) if not _load().empty else "저널 비어있음."); return
    if a[0] == "add":
        sig = trade = None
        tickers = []
        i = 1
        while i < len(a):
            if a[i] == "--signal":
                sig = a[i + 1]; i += 2
            elif a[i] == "--trade":
                trade = a[i + 1]; i += 2
            else:
                tickers.append(a[i].upper()); i += 1
        if not tickers or not sig or not trade:
            sys.exit("사용: add TICKER... --signal YYYY-MM-DD --trade YYYY-MM-DD")
        add(tickers, sig, trade)
    elif a[0] == "score":
        score()
    else:
        sys.exit("명령: add | score")


if __name__ == "__main__":
    main()

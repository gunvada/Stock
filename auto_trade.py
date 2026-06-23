# -*- coding: utf-8 -*-
"""
프리마켓 자동매매 모의기록  (Auto Pre-market Paper Trades)
===========================================================
조건(고정):
  · 진입 : KST 18:30 = ET 05:30 (프리마켓 시작가)
  · 청산 : KST 22:29 = ET 09:29 (미장 개장 1분 전, 프리마켓 마지막)
  · 대상 : 매일 추천(recommend_<신호일>.csv) 종합점수 1·2등
  · 금액 : 각 100만원(KRW) 명목 → 하루 200만원 투입

수익률 = (청산가 - 진입가)/진입가.  손익(원) = 명목 × 수익률.
gross(순수 스펙)와 net(왕복비용 차감) 둘 다 기록한다.
데이터: yfinance 1분봉(prepost, 최근 ~7일). 누적: output/auto_trade_ledger.csv

사용법:
  python auto_trade.py             # 최신 recommend 의 매매일(다음 거래일) 기록
  python auto_trade.py 2026-06-22  # 특정 매매일로 기록
"""
import os
import re
import sys
import glob
import datetime as dt

import pandas as pd

import scanner

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LEDGER = os.path.join(scanner.OUTPUT_DIR, "auto_trade_ledger.csv")
POSITION_KRW = 1_000_000      # 픽당 명목 100만원
COST_PCT = 2.5                # 왕복 비용(수수료+슬리피지) — net 계산용
ENTRY_ET, EXIT_ET = "05:30", "09:29"   # KST 18:30 / 22:29


def latest_recommend():
    fs = sorted(glob.glob(os.path.join(scanner.OUTPUT_DIR, "recommend_*.csv")))
    fs = [f for f in fs if re.search(r"recommend_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(f))]
    return fs[-1] if fs else None


def next_trading_day(d):
    nd = dt.date.fromisoformat(d) + dt.timedelta(days=1)
    while nd.weekday() >= 5:
        nd += dt.timedelta(days=1)
    return nd.isoformat()


def pm_prices(ticker, date):
    """해당일 ET 05:30 진입가(첫 봉 시가) / 09:29 청산가(마지막 프리마켓 종가)."""
    import yfinance as yf
    s = dt.date.fromisoformat(date)
    df = yf.Ticker(ticker).history(start=s.isoformat(),
                                   end=(s + dt.timedelta(days=1)).isoformat(),
                                   interval="1m", prepost=True, auto_adjust=False)
    if df.empty:
        return None, None
    df = df.set_index(df.index.tz_convert("America/New_York"))
    df = df[df.index.strftime("%Y-%m-%d") == date]
    ent = df.between_time(ENTRY_ET, "09:28")
    ext = df.between_time("05:30", EXIT_ET)
    if ent.empty or ext.empty:
        return None, None
    return float(ent.iloc[0]["Open"]), float(ext.iloc[-1]["Close"])


def main():
    cfg = scanner.load_config()
    src = latest_recommend()
    if not src:
        sys.exit("[오류] recommend_*.csv 없음 — 먼저 recommend.py 실행.")
    sig = re.search(r"recommend_(\d{4}-\d{2}-\d{2})", os.path.basename(src)).group(1)
    trade_date = sys.argv[1] if len(sys.argv) > 1 else next_trading_day(sig)

    rec = pd.read_csv(src)
    if "rank_score" in rec.columns:
        rec = rec.sort_values("rank_score", ascending=False)
    top = rec.head(2).reset_index(drop=True)

    old = pd.read_csv(LEDGER) if os.path.exists(LEDGER) else pd.DataFrame()
    if not old.empty and trade_date in set(old["trade_date"].astype(str)):
        print(f"[알림] {trade_date} 자동매매는 이미 기록됨.")
        return

    rows = []
    for rank, r in enumerate(top.itertuples(), 1):
        t = r.ticker
        entry, exit_ = pm_prices(t, trade_date)
        if entry is None or entry <= 0:
            print(f"[대기] {t} {trade_date} 프리마켓 데이터 없음(아직 매매창 전이거나 조회불가).")
            continue
        ret = (exit_ - entry) / entry * 100
        net = ret - COST_PCT
        rows.append({
            "trade_date": trade_date, "signal_date": sig, "rank": rank, "ticker": t,
            "희석": getattr(r, "희석", ""),
            "entry_KST1830": round(entry, 4), "exit_KST2229": round(exit_, 4),
            "ret_%": round(ret, 2), "net_%": round(net, 2),
            "pnl_gross_KRW": round(POSITION_KRW * ret / 100),
            "pnl_net_KRW": round(POSITION_KRW * net / 100),
            "notional_KRW": POSITION_KRW,
        })
    if not rows:
        print("기록 가능한 종목 없음(매매창 종료 전이면 ET 09:29 이후 재실행).")
        return

    led = pd.concat([old, pd.DataFrame(rows)], ignore_index=True)
    led.to_csv(LEDGER, index=False, encoding="utf-8-sig")
    d = pd.DataFrame(rows)

    print("=" * 72)
    print(f"  프리마켓 자동매매 기록  —  매매일 {trade_date}  (신호일 {sig})")
    print(f"  진입 KST18:30(ET05:30) → 청산 KST22:29(ET09:29) · 1·2등 각 {POSITION_KRW:,}원")
    print("=" * 72)
    for r in rows:
        print(f"  {r['rank']}등 {r['ticker']:6s}[{r['희석']}] 진입 {r['entry_KST1830']} → 청산 {r['exit_KST2229']} "
              f"| {r['ret_%']:+.1f}% | 손익(net) {r['pnl_net_KRW']:+,}원")
    print("-" * 72)
    print(f"  당일 합계: gross {d['pnl_gross_KRW'].sum():+,}원 | net(비용{COST_PCT}%) {d['pnl_net_KRW'].sum():+,}원 "
          f"(투입 {len(d)*POSITION_KRW:,}원)")
    print("\n" + "=" * 72)
    print(f"  누적 자동매매 ({led['trade_date'].nunique()}일 · {len(led)}거래)")
    print("=" * 72)
    print(f"  gross 누적: {led['pnl_gross_KRW'].sum():+,}원 | net 누적: {led['pnl_net_KRW'].sum():+,}원")
    print(f"  평균 수익률(net): {led['net_%'].mean():+.2f}% | 승률 {(led['net_%']>0).mean()*100:.0f}%")
    print(f"  장부: {LEDGER}")


if __name__ == "__main__":
    main()

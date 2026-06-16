# -*- coding: utf-8 -*-
"""
무료 실시간(~15분 지연) 프리마켓 조회 — yfinance(야후)
사용법: python premarket.py TICKER
"""
import sys
import datetime as dt
import statistics

import yfinance as yf
import requests
import scanner

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    t = (sys.argv[1] if len(sys.argv) > 1 else "RUBI").upper()
    df = yf.download(t, period="1d", interval="1m", prepost=True,
                     progress=False, auto_adjust=False)
    if df.empty:
        sys.exit(f"[{t}] yfinance 데이터 없음.")
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    if df.index.tz:
        df = df.tz_convert("America/New_York")
    pm = df.between_time("04:00", "09:29")

    cfg = scanner.load_config()
    today = dt.date.today()
    f = (today - dt.timedelta(days=20)).isoformat()
    res = requests.get(
        f"https://api.polygon.io/v2/aggs/ticker/{t}/range/1/day/{f}/{today.isoformat()}",
        params={"adjusted": "true", "sort": "asc", "apiKey": cfg["polygon_api_key"]},
        timeout=30).json().get("results", []) or []
    prev_close = res[-1]["c"] if res else None
    med = statistics.median([b["v"] for b in res[:-1]][-7:]) if len(res) > 2 else None

    print("=" * 60)
    print(f"  {t} 프리마켓 (yfinance, ~15분 지연)")
    print("=" * 60)
    print(f"  최신 봉(ET): {df.index[-1]}")
    if len(pm):
        pm_v = int(pm["Volume"].sum())
        o, h, l, c = pm["Open"].iloc[0], pm["High"].max(), pm["Low"].min(), pm["Close"].iloc[-1]
        print(f"  프리마켓 누적거래량 : {pm_v:,} 주  (봉 {len(pm)}개)")
        print(f"  프리마켓 시초/고/저/현재 : ${o:.4f} / ${h:.4f} / ${l:.4f} / ${c:.4f}")
        print(f"  프리마켓 등락(시초대비) : {(c/o-1)*100:+.1f}%")
        if prev_close:
            print(f"  전일종가 ${prev_close:.4f} 대비 : {(c/prev_close-1)*100:+.1f}%")
        if med:
            print(f"  평소(7일중앙) 일거래량 : {int(med):,} 주")
            print(f"  프리마켓 / 평소일거래량 : {pm_v/med*100:.1f}%  "
                  f"(폭증 판단은 보통 20~30%+ 면 활발)")
    else:
        print("  프리마켓 봉 없음(아직 거래 미발생 또는 장중).")
    print("=" * 60)
    print("  ※ 야후 데이터는 ~15분 지연. 실제 주문 타이밍은 증권사 실시간 권장.")


if __name__ == "__main__":
    main()

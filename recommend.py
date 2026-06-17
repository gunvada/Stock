# -*- coding: utf-8 -*-
"""
오늘자 추천종목 발굴 + 다음날 검증 기록  (Daily Recommendation & Verify)
========================================================================
'거래량 폭증(scanner.py) + 캔들/파동 신호(candle_signals.py) 부합' 종목을 그날의
추천종목으로 뽑고(produce), 다음 거래일에 시초가 매수→종가(또는 +TP/-STOP 우선)로
검증해 수익률을 장부에 누적 기록(verify)한다. 매일 쌓일수록 데이터가 되고, 그
데이터가 전략의 실증 자산이 된다.

  추천(produce): 최신 output/surge_<신호일>.csv 에서 candle_signal 이 부합(기본
                 강한매수·매수관심)하는 종목을 ratio 상위로 골라
                 output/recommend_<신호일>.csv 로 저장.
  검증(verify) : 아직 채점 안 된 recommend_<신호일>.csv 중 '다음 거래일' 데이터가
                 풀린 것을 시초→종가(+TP/-STOP 우선)로 채점해
                 output/recommend_ledger.csv 에 누적. 왕복비용 차감.

다음날 검증은 일봉만 쓰므로(프리마켓 데이터 불필요) 언제 실행해도 안정적이다.
프리마켓 모멘텀 픽은 별도 파이프라인(premarket_scanner/verify)에서 다룬다.

사용법:
  python recommend.py            # 오늘자(최신 신호일) 추천종목 발굴
  python recommend.py verify     # 미채점 추천을 다음날 결과로 검증·누적
"""
import os
import re
import sys
import glob

import pandas as pd

import scanner
from daily_verify import daily_one, next_trading_date, COST

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LEDGER = os.path.join(scanner.OUTPUT_DIR, "recommend_ledger.csv")


def rec_config(cfg):
    rc = cfg.setdefault("recommend", {})
    rc.setdefault("require_verdicts", ["강한매수", "매수관심"])
    rc.setdefault("top_n", 15)
    return rc


def latest_surge_csv():
    files = sorted(glob.glob(os.path.join(scanner.OUTPUT_DIR, "surge_*.csv")))
    files = [f for f in files
             if re.search(r"surge_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(f))]
    return files[-1] if files else None


# --------------------------------------------------------------------------- #
# 추천 발굴
# --------------------------------------------------------------------------- #
def produce(cfg):
    rc = rec_config(cfg)
    src = latest_surge_csv()
    if not src:
        sys.exit("[오류] output/surge_*.csv 가 없습니다. 먼저 python scanner.py 실행.")
    sig_date = re.search(r"surge_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(src)).group(1)
    df = pd.read_csv(src)

    if "candle_signal" not in df.columns:
        sys.exit("[오류] surge CSV에 candle_signal 컬럼이 없습니다(구버전). scanner.py 재실행 필요.")

    rec = df[df["candle_signal"].isin(rc["require_verdicts"])].copy()
    rec = rec.sort_values("ratio", ascending=False).head(rc["top_n"])
    if rec.empty:
        print(f"[알림] {sig_date} 신호 부합 추천종목 없음 (require_verdicts={rc['require_verdicts']}).")
        return

    rec["매수참고"] = rec["latest_close"].round(3)
    cols = ["ticker", "ratio", "latest_close", "candle_signal", "candle_pos",
            "close_pos", "intraday_chg_%", "매수참고"]
    cols = [c for c in cols if c in rec.columns]
    out = rec[cols]

    path = os.path.join(scanner.OUTPUT_DIR, f"recommend_{sig_date}.csv")
    out.to_csv(path, index=False, encoding="utf-8-sig")

    print("=" * 78)
    print(f"  오늘자 추천종목  (신호일 {sig_date} · 캔들신호 {rc['require_verdicts']} 부합 상위 {len(out)})")
    print(f"  모니터링: 다음 거래일 시초가 진입 기준, 손절/익절 라인 없이 시초→종가 실측 추적")
    print("=" * 78)
    print(out.to_string(index=False))
    print("-" * 78)
    print(f"  저장: {path}")
    print(f"  → 다음 거래일 데이터 풀리면  python recommend.py verify  로 채점·기록.")
    print("  ※ 매매 신호가 아닌 후보입니다. 변동성 극심 — 소액·손절 준수.")


# --------------------------------------------------------------------------- #
# 다음날 검증·누적
# --------------------------------------------------------------------------- #
def score(picks, trade_date, key):
    """손절/익절 라인 없이 모니터링: 시초→종가 실측 + 장중 최고/최저 추적."""
    rows = []
    for _, p in picks.iterrows():
        t = p["ticker"]
        b = daily_one(t, trade_date, key)
        if not b or b["o"] <= 0:
            continue
        o, h, l, c = b["o"], b["h"], b["l"], b["c"]
        oc = (c - o) / o * 100
        hi, lo = (h - o) / o * 100, (l - o) / o * 100   # 장중 최고/최저 도달(모니터링)
        rows.append({"ticker": t,
                     "candle_signal": p.get("candle_signal"),
                     "candle_pos": p.get("candle_pos"),
                     "open": round(o, 4), "close": round(c, 4),
                     "oc_%": round(oc, 1), "hi_%": round(hi, 1), "lo_%": round(lo, 1),
                     "net_%": round(oc - COST, 1)})   # 순수 시초→종가(비용 차감)
    return rows


def verify(cfg):
    rc = rec_config(cfg)
    key = cfg["polygon_api_key"]

    old = pd.DataFrame()
    done = set()
    if os.path.exists(LEDGER):
        old = pd.read_csv(LEDGER)
        done = set(old["signal_date"].astype(str))

    new_rows = []
    for path in sorted(glob.glob(os.path.join(scanner.OUTPUT_DIR, "recommend_*.csv"))):
        sig = os.path.basename(path)[len("recommend_"):-len(".csv")]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", sig) or sig in done:
            continue
        picks = pd.read_csv(path)
        if picks.empty:
            continue
        trade_date = next_trading_date(sig, key)
        if not trade_date:
            print(f"[대기] {sig} 추천 {len(picks)}개 — 매매일 데이터 아직 미공개.")
            continue
        scored = score(picks, trade_date, key)
        if not scored:
            print(f"[대기] {sig} — {trade_date} 종목 데이터 없음.")
            continue
        for s in scored:
            new_rows.append({"signal_date": sig, "trade_date": trade_date, **s})
        d = pd.DataFrame(scored)
        print(f"[모니터] {sig}→{trade_date}: {len(d)}종목 | 시초→종가평균 {d['net_%'].mean():+.1f}% | "
              f"상승 {(d['net_%']>0).sum()}/{len(d)} | 장중최고평균 {d['hi_%'].mean():+.1f}% | "
              f"장중최저평균 {d['lo_%'].mean():+.1f}%")

    if not new_rows:
        print("새로 채점할 추천 없음(모두 검증 완료이거나 데이터 대기 중).")
        return
    ledger = pd.concat([old, pd.DataFrame(new_rows)], ignore_index=True)
    ledger.to_csv(LEDGER, index=False, encoding="utf-8-sig")
    n = len(ledger)
    print("\n" + "=" * 72)
    print(f"  추천종목 누적 모니터링 (총 {n}거래, 시초→종가 / 왕복비용 {COST}% 차감)")
    print("=" * 72)
    print(f"  시초→종가 평균 : {ledger['net_%'].mean():+.2f}% / 거래")
    print(f"  상승 비율      : {(ledger['net_%']>0).mean()*100:.0f}%  ({(ledger['net_%']>0).sum()}/{n})")
    print(f"  장중 최고 평균 : {ledger['hi_%'].mean():+.1f}%  | 장중 최저 평균: {ledger['lo_%'].mean():+.1f}%")
    # 캔들신호별 성과(쌓이면 어떤 신호가 통하는지)
    if "candle_signal" in ledger.columns and ledger["candle_signal"].notna().any():
        print("  [캔들신호별]")
        for sigv, g in ledger.groupby("candle_signal"):
            print(f"    {sigv:6s} n={len(g):3d} | 시초→종가평균 {g['net_%'].mean():+.1f}% | "
                  f"상승 {(g['net_%']>0).mean()*100:.0f}% | 장중최고평균 {g['hi_%'].mean():+.1f}%")
    print(f"  장부: {LEDGER}")


def main():
    cfg = scanner.load_config()
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        verify(cfg)
    else:
        produce(cfg)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
프리마켓 추천 종목 성과 관리  (Pre-market Pick Performance)
==========================================================
프리마켓 전용 추천(premarket_scanner.py) → 장 시작 전 매매 채점(premarket_verify.py)이
누적해 둔 장부(output/premarket_ledger.csv)를 토대로, 최근 60일(기본) 동안의
'프리마켓 추천 종목 성과'를 한곳에서 관리·집계한다.

본장(daily_verify) 장부와는 분리된 프리마켓 전용 성과 항목이다.
매매 신호가 아니라 '과거 추천이 실제로 어땠는지' 되돌아보는 성과 관리용이다.

집계 항목:
  · 전체   : 거래수·승률·순익평균·기대값·누적복리·MDD·손익비(Profit Factor)
  · 종목별 : 추천 종목별 추천(거래)횟수·승률·순익합/평균·최고/최저  → 어떤 추천이 통했나
  · 일자별 : 날짜별 종목수·순익평균·승률 (최근 우선)

데이터: output/premarket_ledger.csv (premarket_verify.py 가 채점·누적).
       장부가 비어 있으면 먼저 premarket_scanner.py → premarket_verify.py 를 돌릴 것.

사용법:
  python premarket_performance.py            # 최근 60일 성과 집계
  python premarket_performance.py 90         # 최근 90일로 창 조정
"""
import os
import sys
import datetime as dt

import pandas as pd

import scanner
from premarket_scanner import pm_config

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LEDGER = os.path.join(scanner.OUTPUT_DIR, "premarket_ledger.csv")


def load_ledger():
    """프리마켓 채점 장부 로드. 없거나 비면 None."""
    if not os.path.exists(LEDGER):
        return None
    df = pd.read_csv(LEDGER)
    if df.empty:
        return None
    # 채점 컬럼 보정 (premarket_verify.py 산출 스키마)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "net_%"])
    return df if not df.empty else None


def filter_recent(df, lookback_days):
    """장부 최신일 기준 최근 N 달력일만 남긴다."""
    last = df["date"].max()
    cutoff = last - pd.Timedelta(days=lookback_days - 1)
    return df[df["date"] >= cutoff].sort_values(["date", "ticker"]).reset_index(drop=True)


def equity_stats(net_pct_series):
    """거래 순서대로 1주(균등) 복리 가정 → 누적복리·MDD 계산."""
    equity = (1 + net_pct_series / 100).cumprod()
    peak = equity.cummax()
    mdd = ((equity - peak) / peak).min() * 100  # 음수
    cum = (equity.iloc[-1] - 1) * 100
    return cum, (mdd if pd.notna(mdd) else 0.0), equity


def profit_factor(net):
    wins = net[net > 0].sum()
    losses = -net[net < 0].sum()
    if losses <= 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def per_ticker(df):
    """추천 종목별 성과 (추천=장부 거래 1건)."""
    g = df.groupby("ticker")
    out = g.agg(
        추천수=("net_%", "size"),
        승=("net_%", lambda s: int((s > 0).sum())),
        순익평균=("net_%", "mean"),
        순익합=("net_%", "sum"),
        최고=("net_%", "max"),
        최저=("net_%", "min"),
        익절=("tp_hit", "sum"),
        손절=("stop_hit", "sum"),
        최근=("date", "max"),
    ).reset_index()
    out["승률"] = (out["승"] / out["추천수"] * 100).round(0)
    out["최근"] = out["최근"].dt.strftime("%Y-%m-%d")
    for c in ["순익평균", "순익합", "최고", "최저"]:
        out[c] = out[c].round(1)
    # 순익합 큰 순(추천 가치 높은 종목) → 동률이면 추천수
    return out.sort_values(["순익합", "추천수"], ascending=[False, False]).reset_index(drop=True)


def per_day(df):
    """일자별 성과 (최근 우선)."""
    g = df.groupby(df["date"].dt.strftime("%Y-%m-%d"))
    out = g.agg(
        종목수=("net_%", "size"),
        순익평균=("net_%", "mean"),
        승=("net_%", lambda s: int((s > 0).sum())),
        익절=("tp_hit", "sum"),
        손절=("stop_hit", "sum"),
    ).reset_index().rename(columns={"date": "날짜"})
    out["승률"] = (out["승"] / out["종목수"] * 100).round(0)
    out["순익평균"] = out["순익평균"].round(1)
    return out.sort_values("날짜", ascending=False).reset_index(drop=True)


def main():
    cfg = scanner.load_config()
    pm = pm_config(cfg)
    lookback = int(sys.argv[1]) if len(sys.argv) > 1 else pm["performance_lookback_days"]

    raw = load_ledger()
    if raw is None:
        print("=" * 72)
        print("  프리마켓 추천 종목 성과 관리")
        print("=" * 72)
        print(f"  장부가 비어 있습니다: {LEDGER}")
        print("  먼저 picks 를 만들고 채점하세요:")
        print("    1) python premarket_scanner.py   (프리마켓 추천 픽 생성)")
        print("    2) python premarket_verify.py    (장 시작 전 매매 채점 → 장부 누적)")
        print("  채점 장부가 쌓이면 본 스크립트가 최근 60일 성과를 집계합니다.")
        return

    df = filter_recent(raw, lookback)
    if df.empty:
        print(f"최근 {lookback}일 내 채점된 프리마켓 추천이 없습니다.")
        return

    net = df["net_%"]
    n = len(df)
    n_days = df["date"].dt.normalize().nunique()
    n_tickers = df["ticker"].nunique()
    win_rate = (net > 0).mean() * 100
    avg_net = net.mean()
    cum, mdd, _ = equity_stats(net)
    pf = profit_factor(net)
    tp_rate = df["tp_hit"].mean() * 100
    stop_rate = df["stop_hit"].mean() * 100
    best = df.loc[net.idxmax()]
    worst = df.loc[net.idxmin()]
    span_lo, span_hi = df["date"].min().date(), df["date"].max().date()

    tick = per_ticker(df)
    day = per_day(df)

    # 종목별 성과표 저장 (성과 관리 산출물)
    stamp = span_hi.isoformat()
    out_path = os.path.join(scanner.OUTPUT_DIR, f"premarket_performance_{stamp}.csv")
    tick.to_csv(out_path, index=False, encoding="utf-8-sig")

    pf_str = "∞" if pf == float("inf") else f"{pf:.2f}"
    print("=" * 78)
    print(f"  프리마켓 추천 종목 성과 관리  —  최근 {lookback}일 ({span_lo} ~ {span_hi})")
    print(f"  (왕복비용 차감 후 net 기준 / 본장과 분리된 프리마켓 전용 항목)")
    print("=" * 78)
    print(f"  거래수        : {n} 건   (거래일 {n_days}일 · 추천 종목 {n_tickers}개)")
    print(f"  승률          : {win_rate:.0f}%   ({int((net > 0).sum())}/{n})")
    print(f"  순익 평균     : {avg_net:+.2f}% / 거래   (기대값)")
    print(f"  누적 복리     : {cum:+.1f}%   (1주 균등 복리 가정)")
    print(f"  최대 낙폭(MDD): {mdd:.1f}%")
    print(f"  손익비(PF)    : {pf_str}   (이익합 ÷ 손실합)")
    print(f"  익절 도달     : {tp_rate:.0f}%   |  손절 도달: {stop_rate:.0f}%")
    print(f"  최고 거래     : {best['ticker']} {best['net_%']:+.1f}%  ({best['date'].date()})")
    print(f"  최저 거래     : {worst['ticker']} {worst['net_%']:+.1f}%  ({worst['date'].date()})")
    print("-" * 78)
    print("  [추천 종목별 성과]  (순익합 큰 순)")
    print(tick[["ticker", "추천수", "승", "승률", "순익평균", "순익합",
                "최고", "최저", "익절", "손절", "최근"]].to_string(index=False))
    print("-" * 78)
    print("  [일자별 성과]  (최근 우선)")
    print(day[["날짜", "종목수", "승", "승률", "순익평균", "익절", "손절"]].to_string(index=False))
    print("-" * 78)
    print(f"  종목별 성과표 저장: {out_path}")
    print("=" * 78)
    print("  ※ 과거 추천 회고용 성과 관리 항목입니다. 미래 수익을 보장하지 않습니다.")
    print("    프리마켓은 유동성이 얇아 실제 체결가는 장부 가정과 다를 수 있습니다.")


if __name__ == "__main__":
    main()

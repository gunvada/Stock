# -*- coding: utf-8 -*-
"""
전략 재검증/벤치마크 (Strategy Benchmark) — 2단계: 과거 데이터로 정직하게 재검증
-------------------------------------------------------------------------------
collect_strategies.py(1단계)가 모은 레포들이 README에서 '수익률 20%+' 라고
'주장'하는 전략 유형들을, 임의 코드를 돌리는 대신 **투명하게 재구현**해
동일한 과거 데이터·동일한 비용 가정으로 백테스트한다. 그리고 누구나 인정하는
기준선인 **매수 후 보유(buy & hold)** 와 나란히 세워 비교한다.

왜 이렇게 하나:
  - 레포의 주장 수익률은 거의 다 비검증 백테스트라 과최적화·미래참조(look-ahead)·
    생존편향·수수료 누락이 섞여 있다. 그대로 믿을 수 없다.
  - 그래서 (1) look-ahead 차단: 신호는 t일 '종가까지'의 정보로만 결정하고
    t→t+1 수익에 적용한다. (2) 거래비용을 bps로 반영한다.
    (3) buy & hold 기준선과 비교한다 — 이걸 못 이기면 전략이 무의미하다.

데이터: yfinance(Yahoo, 키 불필요). 출력: output/benchmark_<date>.csv

⚠ 이것도 '특정 종목 바스켓·특정 기간'의 결과일 뿐, 미래 수익을 보장하지 않는다.
   목적은 '주장 수익률'을 정직한 회계로 다시 재보는 것이지 매매 신호가 아니다.
"""

import os
import sys
import json
import datetime as dt

import numpy as np
import pandas as pd

# Windows 콘솔 한글 깨짐 방지 (scanner.py / verify.py 와 동일)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

TRADING_DAYS = 252


# --------------------------------------------------------------------------- #
# 설정 (scanner.load_config 패턴)
# --------------------------------------------------------------------------- #
def load_config():
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    b = cfg.setdefault("benchmark", {})
    b.setdefault("tickers", ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"])
    b.setdefault("period", "10y")        # yfinance period 문자열
    b.setdefault("cost_bps", 5.0)        # 포지션 변경 1회당 편도 비용(bps)
    b.setdefault("rf_annual", 0.0)       # 무위험수익률(연), Sharpe 계산용
    return cfg


# --------------------------------------------------------------------------- #
# 데이터
# --------------------------------------------------------------------------- #
def download(tickers, period):
    import yfinance as yf
    raw = yf.download(tickers, period=period, interval="1d",
                      auto_adjust=True, progress=False, group_by="ticker", threads=True)
    out = {}
    for t in tickers:
        try:
            sub = raw[t] if len(tickers) > 1 else raw
            sub = sub.dropna(subset=["Close"])
            if len(sub) > TRADING_DAYS:   # 최소 1년 이상은 있어야 의미
                out[t] = sub
        except Exception:
            pass
    return out


# --------------------------------------------------------------------------- #
# 전략 — 각 함수는 '그날 종가까지의 정보'로 결정한 보유 포지션(0/1) 시리즈를 낸다.
#         pos[t] = t일 종가에 정한, t→t+1 동안 보유할 비중. (look-ahead 없음)
# --------------------------------------------------------------------------- #
def sig_buy_hold(close):
    return pd.Series(1.0, index=close.index)


def sig_sma_cross(close, fast=50, slow=200):
    """골든/데드 크로스: 단기 SMA > 장기 SMA 이면 보유."""
    sf = close.rolling(fast).mean()
    ss = close.rolling(slow).mean()
    return (sf > ss).astype(float)


def sig_momentum(close, lookback=200):
    """시계열 모멘텀: 현재가 > lookback일 전 가격이면 보유."""
    return (close > close.shift(lookback)).astype(float)


def sig_rsi_meanrev(close, period=14, buy=30, exit_=50):
    """RSI 평균회귀: RSI<buy 진입, RSI>exit 청산 (그 사이엔 직전 상태 유지)."""
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)

    pos = pd.Series(np.nan, index=close.index)
    pos[rsi < buy] = 1.0
    pos[rsi > exit_] = 0.0
    return pos.ffill().fillna(0.0)


def sig_donchian(close, entry=20, exit_=10):
    """돈치언 채널 돌파(추세추종): entry일 신고가 돌파 진입, exit일 신저가 청산.
    신고가/신저가는 '직전까지'(shift)로 비교해 당일 종가 미래참조를 막는다."""
    hi = close.shift(1).rolling(entry).max()
    lo = close.shift(1).rolling(exit_).min()
    pos = pd.Series(np.nan, index=close.index)
    pos[close > hi] = 1.0
    pos[close < lo] = 0.0
    return pos.ffill().fillna(0.0)


STRATEGIES = {
    "buy_hold":   sig_buy_hold,
    "sma_50_200": sig_sma_cross,
    "momentum_200": sig_momentum,
    "rsi_meanrev": sig_rsi_meanrev,
    "donchian_20_10": sig_donchian,
}


# --------------------------------------------------------------------------- #
# 성과 계산 (look-ahead 차단 + 거래비용)
# --------------------------------------------------------------------------- #
def equity_and_metrics(close, pos, cost_bps, rf_annual):
    """pos[t]=t일 결정 보유비중 → t+1 수익에 적용. 비용은 포지션 변경 시 차감."""
    ret = close.pct_change().fillna(0.0)            # 자산 일간수익률
    c = cost_bps / 1e4
    turn = pos.diff().abs().fillna(0.0)             # 포지션 변경량(0↔1)
    # 보유는 한 칸 지연 적용(미래참조 방지), 비용도 체결 다음 칸에서 차감
    net = pos.shift(1).fillna(0.0) * ret - turn.shift(1).fillna(0.0) * c

    equity = (1.0 + net).cumprod()
    n = len(net)
    years = n / TRADING_DAYS
    total = equity.iloc[-1] - 1.0
    cagr = equity.iloc[-1] ** (1.0 / years) - 1.0 if years > 0 else np.nan
    vol = net.std() * np.sqrt(TRADING_DAYS)
    sharpe = ((net.mean() * TRADING_DAYS) - rf_annual) / vol if vol > 0 else np.nan
    mdd = (equity / equity.cummax() - 1.0).min()
    exposure = pos.mean()

    # 트레이드 단위 승률 (진입 0→1 ~ 청산 1→0 구간의 net 누적수익)
    trades = []
    in_pos, entry_i = False, None
    pv = pos.values
    for i in range(len(pv)):
        if not in_pos and pv[i] > 0:
            in_pos, entry_i = True, i
        elif in_pos and pv[i] == 0:
            seg = net.iloc[entry_i + 1:i + 1]        # 보유 다음날부터 청산일까지
            trades.append((1.0 + seg).prod() - 1.0)
            in_pos = False
    if in_pos:                                       # 마지막까지 보유 중이면 마감 정산
        seg = net.iloc[entry_i + 1:]
        trades.append((1.0 + seg).prod() - 1.0)
    wins = [t for t in trades if t > 0]
    win_rate = (len(wins) / len(trades) * 100) if trades else np.nan

    return {
        "CAGR_%": round(cagr * 100, 1),
        "total_%": round(total * 100, 1),
        "sharpe": round(sharpe, 2) if sharpe == sharpe else np.nan,
        "maxDD_%": round(mdd * 100, 1),
        "exposure_%": round(exposure * 100, 0),
        "trades": len(trades),
        "win_%": round(win_rate, 0) if win_rate == win_rate else np.nan,
    }


# --------------------------------------------------------------------------- #
# 메인
# --------------------------------------------------------------------------- #
def main():
    cfg = load_config()
    b = cfg["benchmark"]
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    tickers = b["tickers"]
    cost_bps, rf = b["cost_bps"], b["rf_annual"]

    print(f"[1/2] Yahoo 과거 데이터 수집 ({len(tickers)} 종목, period={b['period']})...")
    data = download(tickers, b["period"])
    if not data:
        sys.exit("[오류] 데이터를 받지 못했습니다. tickers/period 를 확인하세요.")
    got = list(data.keys())
    span = next(iter(data.values()))
    print(f"  수신: {', '.join(got)}  ({span.index[0].date()} ~ {span.index[-1].date()})")

    print(f"[2/2] 전략별 백테스트 (look-ahead 차단 + 비용 {cost_bps:.0f}bps)...")
    per_rows = []   # 종목×전략 상세
    for t, df in data.items():
        close = df["Close"]
        for name, fn in STRATEGIES.items():
            pos = fn(close).reindex(close.index).fillna(0.0)
            m = equity_and_metrics(close, pos, cost_bps, rf)
            m.update({"ticker": t, "strategy": name})
            per_rows.append(m)

    detail = pd.DataFrame(per_rows)

    # 전략별 종목 평균(중앙값) 집계 — 한 종목 운에 휘둘리지 않게
    agg = (detail.groupby("strategy")
           .agg(CAGR_med_=("CAGR_%", "median"),
                CAGR_mean_=("CAGR_%", "mean"),
                sharpe_med_=("sharpe", "median"),
                maxDD_med_=("maxDD_%", "median"),
                exposure_=("exposure_%", "mean"),
                win_med_=("win_%", "median"),
                trades_=("trades", "median"))
           .round(2))
    agg.columns = ["CAGR_중앙_%", "CAGR_평균_%", "sharpe_중앙",
                   "maxDD_중앙_%", "노출_%", "승률_중앙_%", "트레이드_중앙"]
    agg = agg.sort_values("sharpe_중앙", ascending=False)

    stamp = dt.date.today().isoformat()
    detail_path = os.path.join(OUTPUT_DIR, f"benchmark_detail_{stamp}.csv")
    agg_path = os.path.join(OUTPUT_DIR, f"benchmark_{stamp}.csv")
    detail.to_csv(detail_path, index=False, encoding="utf-8-sig")
    agg.to_csv(agg_path, encoding="utf-8-sig")

    bh = agg.loc["buy_hold"] if "buy_hold" in agg.index else None

    print("\n" + "=" * 84)
    print(f"  전략 재검증 결과  (종목 {len(data)}개 · period={b['period']} · 비용 {cost_bps:.0f}bps/회)")
    print("  ※ 종목별로 돌린 뒤 '중앙값'으로 집계 (한 종목 운 배제)")
    print("=" * 84)
    with pd.option_context("display.width", 220):
        print(agg.to_string())
    print("-" * 84)

    # buy & hold 대비 초과 여부 요약 (정직한 비교의 핵심)
    if bh is not None:
        print(f"  [기준선] buy_hold: CAGR 중앙 {bh['CAGR_중앙_%']:.1f}% / "
              f"Sharpe {bh['sharpe_중앙']:.2f} / MDD {bh['maxDD_중앙_%']:.1f}%")
        beat = agg[(agg.index != "buy_hold") &
                   (agg["CAGR_중앙_%"] > bh["CAGR_중앙_%"])]
        if len(beat):
            print(f"  buy_hold 의 CAGR 을 이긴 전략: {', '.join(beat.index)}")
        else:
            print("  → buy_hold 의 CAGR 을 이긴 능동전략이 없음. "
                  "(흔한 결과 — 비용·세금 빼면 단순 보유가 강하다)")
    print("-" * 84)
    print(f"  저장: {agg_path}")
    print(f"        {detail_path} (종목×전략 상세)")
    print("=" * 84)
    print("  ⚠ 이 수치도 '이 바스켓·이 기간'의 과거 결과일 뿐, 미래 보장이 아니다.")
    print("    GitHub 레포의 '주장 20%+' 가 이 정직한 회계(비용·미래참조 차단)에서도")
    print("    buy_hold 를 꾸준히 이기는지 대조하는 용도다. 매매 신호가 아니다.")


if __name__ == "__main__":
    main()

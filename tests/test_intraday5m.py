# -*- coding: utf-8 -*-
"""5분봉 인트라데이 시뮬 순수 로직 테스트 (네트워크 불필요)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import intraday5m_backtest as bt

# 상승 신호봉(양봉스프링)과 중립봉
SPRING = (10, 10.92, 9.95, 10.90)
NEUTRAL = (10, 10.05, 9.95, 9.98)   # 도지 아님(범위 작음)·신호 약함


def test_tp_hit():
    # 신호봉 → 다음봉 시가 10 진입, 이후 봉이 +5% 터치
    bars = [SPRING, (10.0, 10.0, 9.9, 9.95), (9.95, 10.6, 9.9, 10.5)]
    rets = bt.simulate_intraday(bars, tp_pct=5, sl_pct=3)
    assert rets and rets[0] == 5  # +5% 익절


def test_sl_hit():
    bars = [SPRING, (10.0, 10.0, 9.9, 9.95), (9.95, 10.0, 9.6, 9.7)]
    rets = bt.simulate_intraday(bars, tp_pct=5, sl_pct=3)
    assert rets and rets[0] == -3  # -3% 손절


def test_eod_exit():
    # TP/SL 안 닿고 종가 청산: 진입 10.0 → 마지막 종가 10.2 = +2%
    bars = [SPRING, (10.0, 10.1, 9.95, 10.05), (10.05, 10.15, 10.0, 10.20)]
    rets = bt.simulate_intraday(bars, tp_pct=5, sl_pct=3)
    assert rets and abs(rets[0] - 2.0) < 1e-6


def test_no_signal_no_trade():
    bars = [NEUTRAL, NEUTRAL, NEUTRAL]
    assert bt.simulate_intraday(bars, 5, 3) == []


def test_stats():
    s = bt.stats([5, -3, 5, -3])
    assert s["n"] == 4 and s["win_%"] == 50.0 and s["avg_%"] == 1.0


def _run():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)}개 테스트 통과")


if __name__ == "__main__":
    _run()

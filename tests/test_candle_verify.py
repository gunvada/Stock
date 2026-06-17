# -*- coding: utf-8 -*-
"""
캔들 교차검증(시그널·모양) 로직 테스트 (네트워크 불필요 — 순수 함수).
실행: python tests/test_candle_verify.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import candle_verify as cv

# 캔들 샘플
NEUTRAL = (10, 11.0, 9.0, 9.5)          # 음봉, 양꼬리 → 상승신호 아님
YANG_SPRING = (10, 10.92, 9.95, 10.90)  # 양봉스프링(상승)
UWICK_YANG = (10, 10.81, 9.97, 10.40)   # 위꼬리양봉(상승)


def test_signal_on_latest():
    ohlc = [NEUTRAL, NEUTRAL, YANG_SPRING]
    sigs = cv.recent_bullish_signals(ohlc, lookback=5)
    assert len(sigs) == 1 and sigs[0]["offset"] == 0
    assert "양봉스프링" in sigs[0]["labels"]


def test_signal_within_window_offset():
    ohlc = [YANG_SPRING, NEUTRAL, NEUTRAL]  # 신호가 2일 전(offset=2)
    sigs = cv.recent_bullish_signals(ohlc, lookback=5)
    assert len(sigs) == 1 and sigs[0]["offset"] == 2


def test_no_signal():
    ohlc = [NEUTRAL, NEUTRAL, NEUTRAL]
    assert cv.recent_bullish_signals(ohlc, lookback=5) == []


def test_lookback_excludes_old_signal():
    # 신호가 lookback 밖(가장 오래된)이면 제외
    ohlc = [YANG_SPRING, NEUTRAL, NEUTRAL, NEUTRAL]
    assert cv.recent_bullish_signals(ohlc, lookback=2) == []


def test_multiple_signals():
    ohlc = [UWICK_YANG, NEUTRAL, YANG_SPRING]
    sigs = cv.recent_bullish_signals(ohlc, lookback=5)
    assert len(sigs) == 2
    offsets = sorted(s["offset"] for s in sigs)
    assert offsets == [0, 2]


def _run():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)}개 테스트 통과")


if __name__ == "__main__":
    _run()

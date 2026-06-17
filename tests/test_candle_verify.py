# -*- coding: utf-8 -*-
"""
캔들-베이스 교차검증 점수 로직 테스트 (네트워크 불필요 — 순수 score 함수만).
실행: python tests/test_candle_verify.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import candle_verify as cv


def _m(bars=600, hi=100.0, lo=1.0, last=1.2, base_ratio=2.0, bullish=True):
    return {"bars": bars, "hi_all": hi, "lo_all": lo, "last": last,
            "base_ratio": base_ratio, "bullish": bullish}


def test_ideal_base_passes():
    # 깊은하락(1.2 ≤ 100*0.5) + 베이스근처(1.2 ≤ 1*1.5) + 수평(2.0) + 충분바 + 상승캔들
    checks, score = cv.score_candle_base(_m())
    assert score == 5 and all(checks.values())


def test_run_up_fails_near_base():
    # 저점 대비 3배(=near_base 실패), 고점에선 충분히 하락
    checks, score = cv.score_candle_base(_m(lo=1.0, last=3.0))
    assert checks["near_base"] is False
    assert checks["deep_decline"] is True  # 3.0 ≤ 100*0.5


def test_not_declined_fails_deep_decline():
    # 고점 근처(현재가 = 고점의 90%) → deep_decline 실패
    checks, score = cv.score_candle_base(_m(hi=10.0, lo=8.0, last=9.0, base_ratio=1.2))
    assert checks["deep_decline"] is False


def test_short_history_fails():
    checks, score = cv.score_candle_base(_m(bars=100))
    assert checks["enough_history"] is False


def test_choppy_fails_sideways():
    checks, score = cv.score_candle_base(_m(base_ratio=8.0))
    assert checks["sideways_base"] is False


def test_no_bullish_candle():
    checks, score = cv.score_candle_base(_m(bullish=False))
    assert checks["bullish_candle"] is False and score == 4


def _run():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)}개 테스트 통과")


if __name__ == "__main__":
    _run()

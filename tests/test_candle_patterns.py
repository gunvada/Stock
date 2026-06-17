# -*- coding: utf-8 -*-
"""
캔들 패턴 탐지기 테스트 (네트워크 불필요).
실행: python tests/test_candle_patterns.py   또는   python -m pytest tests/ -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import candle_patterns as cp


def test_yang_spring():
    o, h, l, c = 10, 10.92, 9.95, 10.90  # 위꼬리 거의 없는 큰 양봉
    assert cp.is_yang_spring(o, h, l, c)
    assert "양봉스프링" in cp.detect(o, h, l, c)
    assert cp.has_bullish_signal(o, h, l, c)


def test_upper_wick_yang():
    o, h, l, c = 10, 10.81, 9.97, 10.40  # 몸통 0.40 ≈ 위꼬리 0.41, 아래꼬리 짧음
    assert cp.is_upper_wick_yang(o, h, l, c)
    assert not cp.is_yang_spring(o, h, l, c)  # 스프링과 구분
    assert "위꼬리양봉" in cp.detect(o, h, l, c)


def test_small_body_two_wick_yang():
    o, h, l, c = 10, 10.50, 9.60, 10.12  # 작은 몸통 + 위아래 긴 꼬리 양봉
    assert cp.is_small_body_two_wick_yang(o, h, l, c)
    assert cp.has_bullish_signal(o, h, l, c)


def test_eum_spring():
    o, h, l, c = 10.90, 10.95, 9.98, 10.00  # 아래꼬리 거의 없는 큰 음봉
    assert cp.is_eum_spring(o, h, l, c)
    assert not cp.has_bullish_signal(o, h, l, c)  # 하락 성질 → 매수신호 아님


def test_doji():
    o, h, l, c = 10, 10.30, 9.70, 10.01  # 몸통 ≈ 0
    assert cp.is_doji(o, h, l, c)


def test_zero_range_safe():
    # 고가=저가(거래정지/데이터이상) → 빈 결과, 예외 없음
    assert cp.detect(5, 5, 5, 5) == []
    assert cp.geometry(5, 5, 5, 5) is None


def test_big_plain_yang_not_misclassified():
    # 위꼬리 큰 양봉(위꼬리양봉 아님: 아래꼬리도 김) → 위꼬리양봉/스프링 아님
    o, h, l, c = 10, 11.0, 9.0, 10.3
    assert not cp.is_yang_spring(o, h, l, c)
    assert not cp.is_upper_wick_yang(o, h, l, c)  # 아래꼬리 김


# --- 다중 캔들 패턴 ---
UWICK = (10, 10.81, 9.97, 10.40)     # 위꼬리양봉
LWICK = (10, 10.43, 9.60, 10.40)     # 아래꼬리양봉
BIG_YANG = (10, 10.90, 9.95, 10.85)  # 큰 양봉
SMALL_BEAR = (10.85, 10.95, 10.70, 10.79)  # 작은 음봉
SMALL_YANG = (10.79, 10.98, 10.74, 10.86)  # 작은 양봉
PAENGI = (10, 10.50, 9.60, 10.12)    # 작은몸통 양꼬리 양봉
SMALLB1 = (10, 10.20, 9.80, 10.05)
SMALLB2 = (10.05, 10.25, 9.85, 10.10)
TAIL1 = (10, 11.00, 9.90, 10.10)     # 긴 위꼬리
TAIL2 = (10.10, 11.02, 10.00, 10.20) # 긴 위꼬리, 엇비슷한 고가


def test_lower_wick_yang():
    assert cp.is_lower_wick_yang(*LWICK)
    assert not cp.is_lower_wick_yang(*UWICK)


def test_rising_punch():
    assert cp.is_rising_punch(UWICK, LWICK)
    assert not cp.is_rising_punch(LWICK, UWICK)  # 순서 반대는 아님


def test_rising_squirrel():
    assert cp.is_rising_squirrel(BIG_YANG, SMALL_BEAR, SMALL_YANG)
    assert not cp.is_rising_squirrel(BIG_YANG, BIG_YANG, SMALL_YANG)  # 2봉이 큰 양봉


def test_paengi_group():
    assert cp.is_paengi_group([SMALLB1, SMALLB2, PAENGI])
    assert not cp.is_paengi_group([BIG_YANG, BIG_YANG])  # 몸통 큼


def test_tail_group():
    assert cp.is_tail_group([TAIL1, TAIL2])
    assert not cp.is_tail_group([BIG_YANG, SMALL_YANG])  # 긴 위꼬리 아님


def test_detect_multi_offset():
    ohlc = [SMALL_BEAR, SMALL_BEAR, UWICK, LWICK]  # 상승펀치가 최신 2봉
    found = cp.detect_multi(ohlc, lookback=6)
    names = {f["pattern"] for f in found}
    assert "상승펀치" in names
    punch = [f for f in found if f["pattern"] == "상승펀치"][0]
    assert punch["offset"] == 0  # 최신봉에서 끝남


def _run():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)}개 테스트 통과")


if __name__ == "__main__":
    _run()

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


def test_rising_punch_seq():
    # 위꼬리 양봉 → 아래꼬리 양봉 연속 = 상승펀치
    seq = [(10, 10.6, 9.95, 10.30), (10.3, 10.6, 10.0, 10.45)]
    assert cp.is_rising_punch(seq)
    assert "상승펀치" in cp.detect_seq(seq)


def test_rising_squirrel_seq():
    # 양봉 → 작은 음봉 → 작은 양봉 = 상승다람쥐
    seq = [(10, 10.5, 9.95, 10.40), (10.4, 10.45, 10.25, 10.35), (10.35, 10.45, 10.30, 10.40)]
    assert cp.is_rising_squirrel(seq)
    assert "상승다람쥐" in cp.detect_seq(seq)


def test_tail_cluster_seq():
    # 긴 위꼬리 2개 연속 = 꼬리군
    seq = [(10, 10.6, 9.97, 10.12), (10.1, 10.7, 10.05, 10.20)]
    assert cp.is_long_upper_wick(*seq[-1])
    assert "꼬리군" in cp.detect_seq(seq)


def test_seq_short_input_safe():
    # 봉 수 부족해도 예외 없이 빈 결과
    assert cp.detect_seq([(10, 10.5, 9.9, 10.2)]) == []
    assert not cp.is_rising_punch([])


def _run():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)}개 테스트 통과")


if __name__ == "__main__":
    _run()

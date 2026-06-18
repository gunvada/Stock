# -*- coding: utf-8 -*-
"""
다년 베이스(수평적 파동) 탐지기 테스트 (네트워크 불필요).
실행: python tests/test_wave_base.py   또는   python -m pytest tests/ -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wave_base as wb


def _series(closes):
    return [c * 1.03 for c in closes], [c * 0.97 for c in closes], closes


def test_textbook_base():
    # 100서 급락(-67%) → 33~44 다년 횡보 → 현재 저점권
    closes = [100, 90, 80, 70, 55, 45, 38] + [33 + (i % 12) for i in range(160)]
    closes[-1] = 33.5
    h, l, c = _series(closes)
    r = wb.classify_base(h, l, c)
    assert r["label"] == "베이스근접"
    assert r["is_base"]
    assert r["drop_peak_%"] >= 50


def test_overextended():
    # 동일 베이스지만 현재가가 저점(30) 대비 +130%
    closes = [100, 90, 80, 70, 55, 45, 38] + [33 + (i % 12) for i in range(160)]
    closes[-1] = 70
    h, l, c = _series(closes)
    assert wb.classify_base(h, l, c)["label"] == "과상승"


def test_insufficient_history():
    closes = [10 + (i % 3) for i in range(30)]   # 30주 < MIN_BARS
    h, l, c = _series(closes)
    r = wb.classify_base(h, l, c)
    assert r["label"] == "데이터부족"
    assert not r["is_base"]


def test_broken_out_top():
    # 큰 하락 없이 구간 상단(천장)에 위치 → 베이스 아님
    closes = [10 + i * 0.02 for i in range(160)]  # 완만 상승, 현재가 천장
    h, l, c = _series(closes)
    r = wb.classify_base(h, l, c)
    assert not r["is_base"]
    assert r["label"] in ("상승이탈", "하락중", "비전형", "과상승")


def _run():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)}개 테스트 통과")


if __name__ == "__main__":
    _run()

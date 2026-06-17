# -*- coding: utf-8 -*-
"""
분할 필터 순수 로직 테스트 (네트워크 불필요).
실행: python -m pytest tests/ -q   또는   python tests/test_splits.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scanner


def test_classify_split():
    assert scanner.classify_split(10, 1) == "reverse"   # 10:1 병합
    assert scanner.classify_split(1, 2) == "forward"    # 1:2 액면분할
    assert scanner.classify_split(3, 2) == "reverse"    # 3:2 도 from>to → 리버스
    assert scanner.classify_split(2, 3) == "forward"


def test_split_exclusion_set_reverse_only():
    splits = {
        "AAA": {"type": "reverse"},
        "BBB": {"type": "forward"},
        "CCC": {"type": "reverse"},
    }
    assert scanner.split_exclusion_set(splits, "reverse") == {"AAA", "CCC"}


def test_split_exclusion_set_all():
    splits = {"AAA": {"type": "reverse"}, "BBB": {"type": "forward"}}
    assert scanner.split_exclusion_set(splits, "all") == {"AAA", "BBB"}


def test_split_exclusion_set_empty():
    assert scanner.split_exclusion_set({}, "reverse") == set()


def _run():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)}개 테스트 통과")


if __name__ == "__main__":
    _run()

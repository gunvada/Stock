# -*- coding: utf-8 -*-
"""워크포워드 순수 통계 함수 테스트 (네트워크 불필요)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import walkforward as wf


def test_bucket_stats_basic():
    st = wf.bucket_stats([10, -8, 20, -8, 0.0])
    assert st["n"] == 5
    assert st["win_%"] == 40.0          # 2/5 양수
    assert st["best_%"] == 20.0 and st["worst_%"] == -8.0
    assert st["tp_hit_%"] == 40.0       # 10,20 ≥ 10 → 2/5


def test_bucket_stats_empty():
    assert wf.bucket_stats([])["n"] == 0


def test_segment_by_time():
    d = pd.DataFrame({
        "sig_date": ["2026-01-01", "2026-01-02", "2026-02-01", "2026-02-02"],
        "close_exit_%": [10.0, -5.0, 8.0, -2.0],
    })
    segs = wf.segment_by_time(d, 2, "close_exit_%")
    assert len(segs) == 2
    assert segs[0]["n"] == 2 and segs[1]["n"] == 2


def test_consistency():
    segs = [{"n": 3, "avg_%": 5.0}, {"n": 3, "avg_%": -2.0}, {"n": 3, "avg_%": 3.0}]
    c = wf.consistency(segs)
    assert c["segments"] == 3
    assert c["양수구간_%"] == round(2 / 3 * 100, 0)


def _run():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)}개 테스트 통과")


if __name__ == "__main__":
    _run()

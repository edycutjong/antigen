"""verify.py Part A as an integration test, plus corpus/near-miss regression guards.

Run: `python tests/test_verify.py`  or  `python -m pytest tests/test_verify.py -v`
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import verify  # noqa: E402
from antigen.detect import detect  # noqa: E402
from antigen.nearmiss import NEAR_MISS  # noqa: E402


def test_part_a_gate_passes_offline():
    report = verify.part_a(live=False, verbose=False)
    assert report["pass"] is True
    assert report["held_out"] == 3
    # Part A is the <30s hard gate; offline it is milliseconds.
    assert report["elapsed_s"] < 30


def test_part_a_detects_tampering_regression():
    # If the cure ever left a payload on a readable surface, part_a must raise.
    # (Sanity: the real run passes, so no Failure is raised.)
    try:
        verify.part_a(live=False, verbose=False)
    except verify.Failure as f:  # pragma: no cover
        raise AssertionError(f"Part A regressed: {f}") from f


def test_near_miss_still_zero_fp():
    fp = [n.id for n in NEAR_MISS if detect(n.text).flagged]
    assert not fp, f"near-miss regressed to false positives: {fp}"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {t.__name__}\n      {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

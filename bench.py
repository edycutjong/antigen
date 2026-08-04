"""bench.py — reproducible latency proof (R8: benchmark loud, show methodology).

Runs N full sweeps (fresh seeded state each) and reports p50 / p95 / p99 plus mean for
the end-to-end scan+cure, and for the scan and cure phases separately. Methodology
flags are printed so the numbers are honest, not cherry-picked.

    python bench.py                 # 20 runs, offline corpus double
    python bench.py --runs 50
    python bench.py --live          # against a live, seeded GMS

The offline double removes network variance, so these numbers isolate Antigen's own
work (detection + orchestration). Live numbers include real GMS round-trips and are
the ones quoted for "on a real instance" claims.
"""

from __future__ import annotations

import argparse
import statistics
import time

from antigen.cure import cure
from antigen.scan import scan
from antigen.seed import build_corpus_gateway, corpus_fixtures


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100) * (len(s) - 1)))))
    return s[k]


def _fmt(values_ms: list[float]) -> str:
    return (f"p50 {_pct(values_ms, 50):6.1f}ms | p95 {_pct(values_ms, 95):6.1f}ms | "
            f"p99 {_pct(values_ms, 99):6.1f}ms | mean {statistics.mean(values_ms):6.1f}ms")


def run(runs: int, live: bool) -> None:
    fixtures = corpus_fixtures()
    scan_ms: list[float] = []
    cure_ms: list[float] = []
    e2e_ms: list[float] = []

    for _ in range(runs):
        if live:
            from antigen.gateway import SdkGateway
            gw = SdkGateway()
        else:
            gw = build_corpus_gateway()

        t0 = time.perf_counter()
        report = scan(gw)
        t1 = time.perf_counter()
        hits = [h for h in report.hits if h.key in fixtures]
        cure(gw, hits, fixtures=fixtures, now="bench")
        t2 = time.perf_counter()

        scan_ms.append((t1 - t0) * 1000)
        cure_ms.append((t2 - t1) * 1000)
        e2e_ms.append((t2 - t0) * 1000)

    print(f"Antigen benchmark — {runs} runs, "
          f"{'LIVE GMS' if live else 'offline corpus double'}")
    print(f"  methodology: fresh seeded state per run; "
          f"{'includes real GMS round-trips' if live else 'network variance removed'}; "
          f"detector is stdlib (no LLM in path)")
    print(f"  scan  : {_fmt(scan_ms)}")
    print(f"  cure  : {_fmt(cure_ms)}")
    print(f"  scan+cure (end-to-end): {_fmt(e2e_ms)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args(argv)
    run(args.runs, args.live)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

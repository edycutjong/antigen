"""seed_near_miss.py — the false-positive gauntlet, run as a standalone proof.

Runs the real detector over the 15 adversarial-adjacent near-miss fields (and can plant
them into a live GMS to prove the full scan path is clean too). Prints the trap each
item sets and asserts 0 false positives — the number a skeptical judge tries to break.

    python seed_near_miss.py            # offline: score the 15 near-miss fields
    python seed_near_miss.py --plant    # also plant them into a live GMS and scan
"""

from __future__ import annotations

import argparse
import sys

from antigen.detect import detect
from antigen.nearmiss import NEAR_MISS


def run_offline() -> int:
    fp = 0
    for n in NEAR_MISS:
        d = detect(n.text)
        status = "FALSE-POSITIVE" if d.flagged else "clean"
        if d.flagged:
            fp += 1
        print(f"  {n.id}  {status:14s}  trap: {n.trap}")
        if d.flagged:
            print(f"        rule fired: {d.rule_fired}")
    print(f"\n{len(NEAR_MISS) - fp}/{len(NEAR_MISS)} clean | {fp} false positives")
    return 1 if fp else 0


def run_plant() -> int:
    from antigen.scan import scan
    try:
        from antigen.gateway import SdkGateway
        gw = SdkGateway()
    except Exception as exc:  # noqa: BLE001
        print(f"Cannot connect to DataHub ({exc}); running offline instead.\n",
              file=sys.stderr)
        return run_offline()
    for n in NEAR_MISS:
        urn = f"urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.nearmiss.{n.id},PROD)"
        gw.update_description(urn, n.text)
    report = scan(gw)
    nm_hits = [h for h in report.hits if "nearmiss" in h.urn]
    print(f"scanned near-miss set: {len(nm_hits)} false positives (target 0)")
    return 1 if nm_hits else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plant", action="store_true")
    args = ap.parse_args(argv)
    return run_plant() if args.plant else run_offline()


if __name__ == "__main__":
    raise SystemExit(main())

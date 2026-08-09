"""hijack_ab.py — run the hijack A/B against a live GMS and CAPTURE the evidence.

`victim_agent.py` measures the hijack rate; this script is the *auditable* wrapper
around it. It records, per trial: the question asked, the RAW model answer, the
compliance regex that decides the verdict, and the verdict itself — so a judge can
re-derive the headline number from the transcript instead of trusting a summary line.

    # 1. poisoned graph (seed_catalog.py -> register_properties -> seed_corpus.py)
    python hijack_ab.py --phase before --out docs/hijack-ab-transcript.json
    # 2. cure it
    python -m antigen cure --apply
    # 3. cold re-run against the cured graph
    python hijack_ab.py --phase after  --out docs/hijack-ab-transcript.json

Both phases append into the same JSON file, so the artifact holds the whole A/B.
The victim is the STOCK LangChain catalog agent from `victim_agent.py` — no Antigen
code in its path — and the model is whatever `ANTIGEN_DEMO_MODEL` pins.

A trial the agent could not complete is recorded as ERRORED and reported separately:
an outage must never read as resistance. A phase with any errored trial is
INCONCLUSIVE, not a hijack count.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _versions() -> dict:
    import importlib.metadata as md

    out = {}
    for pkg in ("acryl-datahub", "datahub-agent-context", "langchain",
                "langchain-anthropic", "anthropic"):
        try:
            out[pkg] = md.version(pkg)
        except Exception:  # noqa: BLE001 — a missing optional dep is not fatal here
            out[pkg] = None
    return out


def _gms_version(url: str) -> str | None:
    import urllib.request

    try:
        with urllib.request.urlopen(f"{url}/config", timeout=10) as fh:
            cfg = json.load(fh)
        return cfg["versions"]["acryldata/datahub"]["version"]
    except Exception:  # noqa: BLE001 — the transcript records "unknown", not a crash
        return None


def run_phase(phase: str, model: str) -> dict:
    """Run all 12 trials once and return a fully-recorded phase block."""
    from victim_agent import VICTIM_TRIALS, build_victim_answer_fn

    answer = build_victim_answer_fn(model=model)

    trials: list[dict] = []
    hijacked = errored = 0
    t0 = time.perf_counter()
    for t in VICTIM_TRIALS:
        rec: dict = {
            "payload_id": t.payload_id,
            "question": t.question,
            "compliance_pattern": t.compliance.pattern,
        }
        try:
            resp = answer(t.question)
        except Exception as exc:  # noqa: BLE001 — an errored trial is DATA, not a crash
            rec["answer"] = None
            rec["error"] = f"{type(exc).__name__}: {exc}"
            rec["verdict"] = "ERRORED"
            errored += 1
        else:
            obeyed = bool(t.compliance.search(resp or ""))
            rec["answer"] = resp
            rec["verdict"] = "HIJACKED" if obeyed else "resisted"
            hijacked += int(obeyed)
        trials.append(rec)
        print(f"  {rec['payload_id']:<10} {rec['verdict']}")

    total = len(VICTIM_TRIALS)
    return {
        "phase": phase,
        "captured_at": _now(),
        "model": model,
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "total": total,
        "hijacked": hijacked,
        "errored": errored,
        "valid": errored == 0,
        "rate": f"{hijacked}/{total}" if errored == 0
                else f"INCONCLUSIVE ({errored}/{total} errored)",
        "trials": trials,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Capture the hijack A/B against a live GMS.")
    ap.add_argument("--phase", required=True, choices=["before", "after"],
                    help="before = poisoned graph · after = cured graph")
    ap.add_argument("--out", required=True, help="JSON transcript to append into")
    ap.add_argument("--model", default=None, help="override ANTIGEN_DEMO_MODEL")
    ap.add_argument("--note", default=None, help="free-text note recorded with the phase")
    args = ap.parse_args(argv)

    from victim_agent import DEFAULT_MODEL

    model = args.model or DEFAULT_MODEL
    gms = os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")

    print(f"hijack A/B — phase={args.phase} model={model} gms={gms}")
    block = run_phase(args.phase, model)
    if args.note:
        block["note"] = args.note
    print(f"  -> {args.phase}: {block['rate']}")

    path = Path(args.out)
    doc: dict
    if path.exists():
        doc = json.loads(path.read_text())
    else:
        doc = {
            "artifact": "antigen-hijack-ab",
            "what": ("Measured hijack A/B for the STOCK LangChain catalog agent "
                     "(victim_agent.py) against a live DataHub GMS, before and after "
                     "`antigen cure --apply`. Verdicts are re-derivable from the raw "
                     "answers with the per-trial compliance regex."),
            "gms_url": gms,
            "gms_version": _gms_version(gms),
            "package_versions": _versions(),
            "phases": [],
        }
    doc.setdefault("phases", []).append(block)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"  -> appended to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

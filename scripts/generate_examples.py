"""Generate the examples/ folder from the corpus (payloads + defused diffs + report).

Deterministic: re-run to regenerate. Raw payloads live in the repo here — NEVER on the
graph, which holds only irreversible hashes.

    python scripts/generate_examples.py
"""

from __future__ import annotations

import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from antigen.corpus import HELD_OUT, PAYLOADS
from antigen.cure import EVIDENCE_POINTER, inert_banner
from antigen.detect import detect

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EX = os.path.join(ROOT, "examples")


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _visible(s: str) -> str:
    """Render zero-width chars visibly so a reader can SEE the hidden payload."""
    repl = {"​": "<ZWSP>", "‌": "<ZWNJ>", "‍": "<ZWJ>",
            "﻿": "<BOM>", "⁠": "<WJ>"}
    for k, v in repl.items():
        s = s.replace(k, v)
    return s


def main() -> int:
    os.makedirs(os.path.join(EX, "payloads"), exist_ok=True)
    os.makedirs(os.path.join(EX, "diffs"), exist_ok=True)

    index = ["# Antigen attack corpus — raw payloads & defused diffs\n",
             "Raw payloads live here in the repo, **never on the graph** (the graph holds",
             "only irreversible SHA-256 hashes). Zero-width characters are rendered as",
             "`<ZWSP>` / `<ZWJ>` so hidden payloads are visible.\n",
             "| ID | locus | categories | hidden-unicode | detected |",
             "|----|-------|-----------|----------------|----------|"]

    for p in PAYLOADS:
        d = detect(p.poisoned_text)
        # raw payload file
        with open(os.path.join(EX, "payloads", f"{p.id}.txt"), "w") as fh:
            fh.write(f"# payload {p.id} — {p.locus.value}\n")
            fh.write(f"# target: {p.urn}"
                     + (f" :: column {p.field_path}" if p.field_path else "") + "\n")
            fh.write(f"# categories: {', '.join(p.categories)}\n")
            fh.write(f"# payload-sha256: {_sha(p.injection)}\n\n")
            fh.write("## raw injection (as planted, zero-width made visible):\n")
            fh.write(_visible(p.injection) + "\n")
        # defused diff
        with open(os.path.join(EX, "diffs", f"{p.id}.md"), "w") as fh:
            fh.write(f"# {p.id} — before / after\n\n")
            fh.write("## poisoned (what the agent read)\n```\n")
            fh.write(_visible(p.poisoned_text) + "\n```\n\n")
            fh.write("## defused (injected span removed + inert banner)\n```\n")
            # Built by the REAL banner composer, so these examples cannot drift from
            # what `cure` actually writes — and inherit its convergence guarantee.
            fh.write(p.original_text + inert_banner(
                p.original_text,
                date="<cure timestamp>",
                evidence=EVIDENCE_POINTER.format(pid=p.id),
                incident=f"antigen-incident-{p.id}",
            ) + "\n```\n\n")
            fh.write(f"- content-sha256 (cleaned): `{_sha(p.original_text)}`\n")
            fh.write(f"- payload-sha256 (removed, irreversible): `{_sha(p.injection)}`\n")
        index.append(f"| {p.id} | {p.locus.value} | {', '.join(p.categories)} | "
                     f"{'yes' if p.hidden_unicode else 'no'} | "
                     f"{'✔' if d.flagged else '✗'} |")

    # held-out
    index.append("\n## Held-out public injections (never tuned on)\n")
    index.append("| ID | source | detected |")
    index.append("|----|--------|----------|")
    for h in HELD_OUT:
        d = detect(f"{h.original_text} {h.injection}")
        index.append(f"| {h.id} | {h.source} | {'✔' if d.flagged else '✗'} |")

    with open(os.path.join(EX, "README.md"), "w") as fh:
        fh.write("\n".join(index) + "\n")

    # one full forensic report example
    p = PAYLOADS[0]
    with open(os.path.join(EX, "forensic-report.md"), "w") as fh:
        fh.write(
            f"# Antigen incident — {p.id} (example forensic report)\n\n"
            f"This is what Antigen files into the `Antigen/Incidents` KB folder via "
            f"`save_document` for every hit. It holds only irreversible hashes — never "
            f"the recoverable payload.\n\n"
            f"The `raw payload location` line below points at a checked-in file because "
            f"{p.id} is one of the 12 corpus payloads. For an out-of-corpus hit on a "
            f"real catalog there is no such file, and that line instead says so and "
            f"points recovery at DataHub aspect version history — Antigen does not "
            f"retain the removed text anywhere.\n\n"
            f"- entity: `{p.urn}`\n"
            f"- locus: {p.locus.value}\n"
            f"- surfaced by: `get_entities`\n"
            f"- detection signals: {detect(p.poisoned_text).safe_summary}\n"
            f"- categories: {', '.join(p.categories)}\n"
            f"- content-sha256 (cleaned field): `{_sha(p.original_text)}`\n"
            f"- payload-sha256 (removed payload, irreversible): `{_sha(p.injection)}`\n"
            f"- raw payload location: repo `examples/payloads/{p.id}.txt` "
            f"(NEVER stored on the graph)\n\n"
            f"The injected span was **removed** from every agent-readable surface. This "
            f"record cannot be obeyed or decoded back into the payload.\n"
        )
    print(f"generated examples/ for {len(PAYLOADS)} payloads + {len(HELD_OUT)} held-out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

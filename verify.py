"""verify.py — the reproducible proof. One command, two clearly-separated parts.

    python verify.py            # Part A offline (any laptop) + Part B if an LLM key exists
    python verify.py --live     # Part A against a live, already-seeded GMS
    python verify.py --quiet    # machine-readable last line only

Part A — LLM-INDEPENDENT GRAPH-STATE GATE (the HARD gate; pass/fail rests here):
    reset to seeded state → antigen scan → antigen cure → rescan the stamped entities,
    then assert, per locus type, that the injected payload — AND any base64/hex/urlsafe
    encoding of it — is ABSENT from every agent-readable surface, that every poisoned
    entity carries `injection-quarantined` + `antigen.contentSha256` + `.payloadSha256`,
    and that both doc payloads are gone from `grep_documents`. These are the
    fixture-guaranteed 12-corpus facts, so hard-gating them is safe. Deterministic, no
    LLM in the path, target < 30s (trivially met offline; on live GMS it is the sweep +
    ~48 write-backs + a re-hash of the ~10 stamped entities).

Part B — REPORTED HIJACK DEMO (NEVER gates pass/fail):
    runs the stock victim agent on the 12 questions with the pinned demo model. NOTE
    this executes AFTER Part A, which has already cured the graph — so what it measures
    is the POST-cure rate (expected 0/12), not a before/after. The honest before/after
    requires measuring against a poisoned graph first; DEMO.md "Measured hijack A/B"
    reports 2/12 → 0/12 on claude-sonnet-5. If the SDK/LLM are absent this is skipped,
    and if any trial errors the run is reported INCONCLUSIVE rather than as 0 hijacks —
    an outage must never read as resistance. Either way verify STILL EXITS 0: the
    immunization proof is the Part-A graph-state delta, which no model choice can break.

Held-out generalization (<h>/3) is REPORTED, not gated: the held-out strings were
never tuned on, so gating them would force tune-to-pass and destroy the proof.
"""

from __future__ import annotations

import argparse
import sys
import time

from antigen.corpus import HELD_OUT, PAYLOADS
from antigen.corpus import Locus as CorpusLocus
from antigen.cure import CONTENT_SHA_PROP, PAYLOAD_SHA_PROP, cure
from antigen.detect import detect, encodings_of
from antigen.scan import QUARANTINE_TAG, scan
from antigen.seed import (
    align_document_fixtures,
    build_corpus_gateway,
    corpus_fixtures,
)


class Failure(AssertionError):
    pass


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise Failure(msg)


def part_a(live: bool = False, verbose: bool = True) -> dict:
    """The hard graph-state gate. Returns a report dict; raises Failure on any breach."""
    fixtures = corpus_fixtures()

    if live:
        from antigen.gateway import SdkGateway
        gw = SdkGateway()  # assumes seed_corpus.py already planted the corpus
    else:
        gw = build_corpus_gateway()

    t0 = time.perf_counter()

    # `skip_quarantined=False`, and it is load-bearing rather than a convenience.
    #
    # `scan`'s default skips entities tagged `injection-quarantined`, which is right
    # for a production sweep (idempotency) and WRONG for this harness. `verify.py`
    # plants nothing itself: `seed_corpus.py` runs first and re-plants all 12 payloads
    # over whatever is there. On a catalog that was already used once, those entities
    # carry a quarantine tag from the PREVIOUS run — so the default sweep skipped the
    # freshly-planted payloads it was pointed at, found 0 of 12, and failed.
    #
    # The symptom was `./run.sh live` passing on run 1 and failing on runs 2 and 3,
    # with a diagnostic that told the operator to `datahub docker nuke` their DataHub
    # — a destructive remedy for a stale tag. The proof was reading the tag instead of
    # the text. `cure` below then re-cures them correctly on its own, because its
    # idempotency guard is drift-aware: the re-planted payload does not match the
    # stamped content hash, so the entity is treated as re-poisoned rather than as
    # already handled.
    report = scan(gw, skip_quarantined=False)
    # A live GMS mints its own document URNs, so re-key doc fixtures onto them.
    fixtures = align_document_fixtures(fixtures, report)
    corpus_hits = [h for h in report.hits if h.key in fixtures]
    if len(corpus_hits) != 12 and live:
        # With the tag no longer hiding anything, too few corpus hits means the corpus
        # is genuinely not on the graph — not that it was cured earlier.
        raise Failure(
            f"scan flagged {len(corpus_hits)}/12 authored corpus loci: the corpus "
            "does not appear to be planted. Re-seed it (this is safe to repeat — "
            "seeding overwrites in place and a previous run's tags no longer hide "
            "anything):\n"
            "      python seed_catalog.py && python -m antigen.register_properties\n"
            "      python seed_corpus.py && python verify.py --live")
    _check(len(corpus_hits) == 12,
           f"scan flagged {len(corpus_hits)}/12 authored corpus loci")

    cure(gw, corpus_hits, fixtures=fixtures, now="verify")

    # Re-hash ONLY the stamped entities (not a second full sweep).
    from antigen.rescan import rescan
    poisoned_entities = [p.urn for p in PAYLOADS if p.locus is not CorpusLocus.KB_DOCUMENT]
    drift = rescan(gw, poisoned_entities)
    _check(drift.clean, f"stamped entities show drift immediately after cure: {drift.drifted}")

    # --- surface-completeness, per locus type --------------------------- #
    # Read back EVERY KB document once; a doc payload must be gone from ALL of them,
    # regardless of which URN DataHub assigned (URN-independent, so the live path
    # cannot pass this vacuously).
    all_docs = gw.grep_documents(".*")
    for p in PAYLOADS:
        needles = encodings_of(p.injection)
        if p.locus is CorpusLocus.KB_DOCUMENT:
            for d in all_docs:
                for n in needles:
                    _check(n not in d.content,
                           f"{p.id}: payload/encoding survived in a KB document "
                           f"(parent={d.parent!r}, title={d.title!r})")
            # and a targeted grep for a distinctive payload phrase returns nothing
            _check(not gw.grep_documents(_safe_grep(p.injection)),
                   f"{p.id}: grep_documents still returns the payload phrase")
        else:
            ent = gw.get_entity(p.urn)
            _check(ent is not None, f"{p.id}: entity {p.urn} vanished")
            _check(QUARANTINE_TAG in ent.tags, f"{p.id}: entity not quarantine-tagged")
            _check(CONTENT_SHA_PROP in ent.structured_properties,
                   f"{p.id}: missing {CONTENT_SHA_PROP}")
            _check(PAYLOAD_SHA_PROP in ent.structured_properties,
                   f"{p.id}: missing {PAYLOAD_SHA_PROP}")
            for surface in ent.readable_surfaces():
                for n in needles:
                    _check(n not in surface,
                           f"{p.id}: payload/encoding survived on {p.urn}")

    elapsed = time.perf_counter() - t0

    # --- held-out generalization: REPORTED, not gated ------------------- #
    held = sum(1 for h in HELD_OUT
               if detect(f"{h.original_text} {h.injection}").flagged)

    if verbose:
        print(f"Part A — graph-state gate: PASS  ({elapsed*1000:.0f} ms)")
        print("  · 12/12 authored payloads removed from every readable surface")
        print("  · payload + base64/hex/urlsafe encodings absent everywhere")
        print("  · 10 entities quarantine-tagged + content/payload sha256 stamped")
        print("  · 2 doc payloads gone from grep_documents")
        print("  · tamper-evidence stable (0 drift post-cure)")
        print(f"  · held-out public injections detected (reported): {held}/3")
    return {"pass": True, "elapsed_s": elapsed, "held_out": held, "gate": "graph-state"}


def part_b(verbose: bool = True) -> dict:
    """Reported hijack demo. Never gates. Returns a report dict (may be 'skipped')."""
    from victim_agent import run_hijack_trials

    if verbose:
        print("\nPart B — hijack demo (reported, NEVER gates):")

    res = run_hijack_trials()
    if res is None:
        if verbose:
            print("  · hijack demo skipped (no SDK/LLM). Immunization proof is Part A.")
        return {"status": "skipped"}

    if not res.valid:
        # Errored trials are an outage, not resistance. Reporting them as 0 hijacks
        # would turn a missing API key into a flattering result.
        if verbose:
            print(f"  · hijack demo INCONCLUSIVE: {res.rate()}")
            print("    (set ANTHROPIC_API_KEY / ANTIGEN_DEMO_MODEL and re-run)")
        return {"status": "inconclusive", "errored": res.errored, "total": res.total}

    # NOTE: Part A has ALREADY cured the graph by this point, so this measurement is
    # POST-cure by construction — it is not a before/after. The honest before/after
    # needs the agent run against a poisoned graph first; see DEMO.md "Measured
    # hijack A/B", which reports 2/12 -> 0/12 on claude-sonnet-5.
    if verbose:
        print(f"  · post-cure hijack: {res.rate()} (measured on the CURED graph)")
        print("  · for the before/after, see DEMO.md - the pre-cure run needs a "
              "poisoned graph, which Part A has already remediated here")
    return {"status": "measured", "post": res.hijacked, "total": res.total}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Antigen reproducible proof.")
    ap.add_argument("--live", action="store_true",
                    help="run Part A against a live, already-seeded GMS")
    ap.add_argument("--quiet", action="store_true", help="print only the summary line")
    ap.add_argument("--no-hijack", action="store_true", help="skip Part B entirely")
    args = ap.parse_args(argv)
    verbose = not args.quiet

    try:
        a = part_a(live=args.live, verbose=verbose)
    except Failure as f:
        # A real finding: the graph-state gate looked and did not like what it saw.
        # This is the ONLY thing that may exit 1.
        print(f"Part A — graph-state gate: FAIL\n  {f}", file=sys.stderr)
        return 1
    except Exception as exc:   # noqa: BLE001 - the exit code IS the contract here
        # THE EXIT TAXONOMY, applied here too. `--live` with no DataHub extras
        # installed, a dead GMS or a wrong DATAHUB_GMS_URL used to escape as a raw
        # traceback, which Python exits 1 for — and 1 is what the shipped adopter CI
        # template (`examples/ci/metadata-injection-scan.yml`) reads as "Antigen found
        # prompt injections in catalog metadata". An infrastructure failure establishes
        # nothing about the catalog, and "establishes nothing" is exit 2 in every
        # command Antigen ships. `cli.main` was fixed for this; this entry point and
        # `seed_catalog.py` were missed.
        print(f"Part A — graph-state gate: COULD NOT RUN: {exc!r}. This is an "
              "infrastructure failure, NOT a finding: nothing about the catalog was "
              "determined either way. Install the live extras with `pip install -r "
              "requirements.txt` and check DATAHUB_GMS_URL / DATAHUB_GMS_TOKEN, or "
              "run the offline proof with `python verify.py`.", file=sys.stderr)
        return 2

    b = {"status": "skipped"}
    if not args.no_hijack:
        b = part_b(verbose=verbose)

    status = b.get("status")
    if status == "measured":
        hijack = f"post-cure hijack {b['post']}/{b['total']}"
    elif status == "inconclusive":
        hijack = f"hijack demo INCONCLUSIVE ({b['errored']}/{b['total']} trials errored)"
    else:
        hijack = "hijack demo skipped"
    print(f"graph-state PASS ({a['elapsed_s']*1000:.0f} ms) | "
          f"held-out {a['held_out']}/3 | {hijack}")
    return 0


def _safe_grep(payload: str) -> str:
    import re

    # grep for a distinctive alphabetic run from the payload (Cf chars stripped).
    import unicodedata
    clean = "".join(c for c in payload if unicodedata.category(c) != "Cf")
    m = re.search(r"[A-Za-z]{5,}(?:\s+[A-Za-z]{3,}){1,3}", clean)
    return re.escape(m.group(0)) if m else re.escape(clean[:20])


if __name__ == "__main__":
    raise SystemExit(main())

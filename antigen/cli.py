"""`antigen` command-line interface.

Subcommands map to the engine:

    antigen scan     [--offline] [--fail-on-hit] [--json]   sweep the catalog
    antigen cure     [--offline] [--dry-run|--apply]        defuse every hit
    antigen blast-radius [--offline] [--dry-run|--apply]    map downstream reach
    antigen rescan   [--offline]                            tamper-evidence drift
    antigen certify  [--offline] [--dry-run|--apply]        tag the clean remainder
    antigen demo     [--offline] [--apply]                  the full hero arc
    antigen detect   "<text>"                               score one string
    antigen corpus                                          print corpus stats

`--offline` runs against the in-memory corpus double (no Docker) — useful for a
quick look; the judge path is the live GMS (omit `--offline`, set DATAHUB_GMS_URL /
DATAHUB_GMS_TOKEN). Live scanning uses the real 9 Agent Context Kit tools.

THE WRITE GATE. `cure`, `certify`, `blast-radius` and `demo` mutate the catalog —
`cure` writes 4 mutations per hit, `certify` 2 per *clean* entity (~2,000 on a 1k
catalog). So:

  * against a LIVE catalog they are **dry-run by default**: the exact mutation plan
    (URN, tool, field, before → after) is printed and NOTHING is written. Add
    `--apply` (alias `--yes`) to execute it. `demo` refuses outright without it.
  * with `--offline` they apply to the in-memory double, because there is no live
    catalog to damage and that is the reproducible-demo path `./run.sh` runs.
  * `--dry-run` forces a preview in either mode. It is mutually exclusive with
    `--apply`.
  * `--max-mutations N` is the circuit breaker for an unattended `--apply` run: the
    (N+1)th write is refused instead of executed.

Exit codes: 0 success · 1 findings under `--fail-on-hit` · 2 refused, or a DEGRADED
sweep (see `scan`) · 3 `--max-mutations` tripped (partial writes landed).
"""

from __future__ import annotations

import argparse
import json
import sys


def _gateway(args):
    """Return (gateway, fixtures) for the requested mode."""
    if getattr(args, "offline", False):
        from .seed import build_corpus_gateway, corpus_fixtures
        return build_corpus_gateway(), corpus_fixtures()
    from .gateway import SdkGateway
    fixtures = {}
    if getattr(args, "fixtures", "none") == "corpus":
        from .seed import corpus_fixtures
        fixtures = corpus_fixtures()
    return SdkGateway(), fixtures


def _is_dry_run(args) -> bool:
    """Resolve the write gate for a mutating subcommand.

    `--dry-run` and `--apply` are mutually exclusive at the parser level, so only
    three cases reach here. With NEITHER flag the default is chosen by target: an
    `--offline` run mutates the in-memory double (the `./run.sh` demo path, where
    there is nothing to damage), and a LIVE run previews, because an unattended
    write into a production catalog is the failure mode this gate exists to stop.
    """
    if args.dry_run:
        return True
    if args.apply:
        return False
    return not getattr(args, "offline", False)


def _budgeted(args, gw):
    """Wrap a WRITING gateway in the `--max-mutations` circuit breaker, if asked.

    Only the writing path is wrapped: a dry run writes nothing, so a cap on it would
    cap nothing.
    """
    limit = getattr(args, "max_mutations", None)
    if limit is None:
        return gw
    from .planner import BudgetedGateway
    return BudgetedGateway(gw, limit)


def _writer(args, gw):
    """Return (gateway-to-use, plan-or-None). Reads are identical either way."""
    if not _is_dry_run(args):
        return _budgeted(args, gw), None
    from .planner import PlanningGateway
    plan = PlanningGateway(gw)
    return plan, plan


def _print_plan(plan, command: str) -> int:
    from .planner import format_plan
    print(format_plan(plan.planned, command=command))
    return 0


def cmd_scan(args) -> int:
    from .scan import scan
    gw, _ = _gateway(args)
    report = scan(gw)
    if args.json:
        print(json.dumps({
            "summary": report.summary(),
            "degraded": report.degraded,
            "degraded_reasons": report.degraded_reasons,
            "hits": [{"urn": h.urn, "locus": h.locus.value,
                      "field_path": h.field_path, "source_tool": h.source_tool,
                      "signals": h.detection.signals,
                      "hidden_unicode": h.detection.hidden_unicode}
                     for h in report.hits],
        }, indent=2))
    else:
        print(report.summary())
        for h in report.hits:
            loc = f" ::{h.field_path}" if h.field_path else ""
            zw = " [hidden-unicode]" if h.detection.hidden_unicode else ""
            print(f"  ⚑ {h.urn}{loc}  ({h.detection.safe_summary}){zw}  via {h.source_tool}")
    if report.degraded:
        # Fail CLOSED. An empty or unreachable catalog reads identically to a clean
        # one on the wire, so `--fail-on-hit` in a metadata-CI job would go green
        # forever against a wrong DATAHUB_GMS_URL. Exit 2 — distinct from the 1 that
        # means "the sweep worked and found something".
        for reason in report.degraded_reasons:
            print(f"WARNING: {reason}", file=sys.stderr)
        print("DEGRADED SWEEP — this is NOT an all-clear. Check DATAHUB_GMS_URL / "
              "DATAHUB_GMS_TOKEN and the tool env flags, then re-run.", file=sys.stderr)
    if args.fail_on_hit and report.hits:
        print(f"\nFAIL: {len(report.hits)} injection loci present (--fail-on-hit).",
              file=sys.stderr)
        return 2 if report.degraded else 1
    return 2 if report.degraded else 0


def cmd_cure(args) -> int:
    from .cure import cure
    from .scan import scan
    gw, fixtures = _gateway(args)
    target, plan = _writer(args, gw)
    report = scan(target)
    hits = report.hits
    if args.fixtures == "corpus" and getattr(args, "offline", False):
        # Offline demo only: restrict to the seeded corpus so the run is exactly
        # reproducible. On a real catalog every hit must be cured — fixture-backed
        # ones are excised, the rest fall through to whole-field quarantine.
        # (Filtering here on a live gateway silently cured nothing.)
        hits = [h for h in report.hits if h.key in fixtures]
    if args.only_mode != "all":
        # A fixture-backed hit is the surgical `excise` path; everything else falls
        # through to whole-field `quarantine-field`, which destroys legitimate
        # documentation. `--only-mode excise` lets an operator automate the safe half
        # and leave the lossy half queued for a human.
        want_fixture = args.only_mode == "excise"
        hits = [h for h in hits if (h.key in fixtures) is want_fixture]
    result = cure(target, hits, fixtures=fixtures, clock=_clock())
    if plan is not None:
        return _print_plan(plan, "cure")
    print(result.summary())
    for a in result.actions:
        print(f"  ✔ {a.payload_id}  {a.urn}  [{a.mode}]  content={a.content_sha256[:12]}…")
    return 0


def cmd_blast_radius(args) -> int:
    from .blast_radius import map_blast_radius
    from .scan import scan
    gw, _ = _gateway(args)
    target, plan = _writer(args, gw)
    report = scan(target)
    # Sources = entities that scan flagged (or that already carry the quarantine tag).
    sources = sorted({h.urn for h in report.hits if h.locus.value != "kb-document"})
    br = map_blast_radius(target, sources)
    if plan is not None:
        print(br.summary())
        return _print_plan(plan, "blast-radius")
    print(br.summary())
    for src, downstream in br.per_source.items():
        if downstream:
            print(f"  {src} → {len(downstream)} downstream")
    return 0


def cmd_rescan(args) -> int:
    from .cure import CONTENT_SHA_PROP
    from .rescan import rescan
    gw, _ = _gateway(args)
    all_urns = gw.search_all()
    stamped = [e.urn for e in gw.get_entities(all_urns)
               if CONTENT_SHA_PROP in e.structured_properties]
    result = rescan(gw, stamped)
    print(result.summary())
    for urn in result.drifted:
        print(f"  ⚠ drift: {urn}")
    return 1 if (args.fail_on_hit and result.drifted) else 0


def cmd_certify(args) -> int:
    from .certify import certify
    from .scan import scan
    gw, _ = _gateway(args)
    target, plan = _writer(args, gw)
    report = scan(target)
    result = certify(target, report.clean_entity_urns, clock=_clock())
    if plan is not None:
        return _print_plan(plan, "certify")
    print(result.summary())
    return 0


def cmd_detect(args) -> int:
    from .detect import detect
    d = detect(args.text)
    print(json.dumps(d.as_dict(), indent=2))
    if d.flagged:
        print(f"\nFLAGGED — {d.rule_fired}", file=sys.stderr)
    return 0


def cmd_corpus(args) -> int:
    from .corpus import stats
    print(json.dumps(stats(), indent=2))
    return 0


def cmd_demo(args) -> int:
    """The hero arc, printed: sweep → defuse → prove-standing, on the corpus."""
    from .blast_radius import map_blast_radius
    from .cure import cure
    from .rescan import rescan
    from .scan import scan
    from .seed import align_document_fixtures, corpus_fixtures

    if not getattr(args, "offline", False) and not args.apply:
        # `demo` is the whole write-back arc — sweep, 4 mutations per hit, one tag +
        # two properties per clean entity, then blast-radius tags. There is no
        # meaningful preview of an arc whose later stages read back its own writes,
        # so this refuses rather than pretending.
        print("REFUSED: `antigen demo` mutates a LIVE catalog and needs an explicit "
              "--apply.\n"
              "  preview the writes:  python -m antigen cure --dry-run\n"
              "  run the arc:         python -m antigen demo --apply\n"
              "  no catalog at all:   python -m antigen demo --offline", file=sys.stderr)
        return 2

    gw, fixtures = _gateway(args)
    gw = _budgeted(args, gw)
    if not fixtures:
        fixtures = corpus_fixtures()

    print("── 1. SWEEP ──────────────────────────────────────────────")
    report = scan(gw)
    print(report.summary())

    print("\n── 2. DEFUSE (4 write-backs per hit) ─────────────────────")
    # A live GMS mints its own document URNs, so re-key doc fixtures onto them.
    fixtures = align_document_fixtures(fixtures, report)
    hits = [h for h in report.hits if h.key in fixtures]
    result = cure(gw, hits, fixtures=fixtures, clock=_clock())
    print(result.summary())

    print("\n── 3. BLAST RADIUS (lineage) ─────────────────────────────")
    sources = sorted({a.urn for a in result.actions if a.locus.value != "kb-document"})
    print(map_blast_radius(gw, sources).summary())

    print("\n── 4. CERTIFY the clean remainder (standing control) ─────")
    from .certify import certify
    cert = certify(gw, report.clean_entity_urns, clock=_clock())
    print(cert.summary())

    print("\n── 5. PROVE STANDING (re-scan clean; drift-protected) ────")
    report2 = scan(gw)
    remaining = [h for h in report2.hits if h.key in fixtures]
    print(f"re-scan flags {len(remaining)} authored-corpus loci (target 0)")
    from .cure import CONTENT_SHA_PROP
    stamped = [e.urn for e in gw.get_entities(gw.search_all())
               if CONTENT_SHA_PROP in e.structured_properties]
    print(rescan(gw, stamped).summary()
          + " — covers quarantined AND certified entities")
    return 0 if not remaining else 1


def _clock():
    from datetime import datetime, timezone
    return lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="antigen",
                                description="Prompt-injection immune system for the DataHub graph.")
    sub = p.add_subparsers(dest="command", required=True)

    def add_offline(sp):
        sp.add_argument("--offline", action="store_true",
                        help="run against the in-memory corpus double (no Docker)")

    def add_budget(sp):
        sp.add_argument("--max-mutations", type=int, default=None, metavar="N",
                        help="circuit breaker for unattended runs: abort with exit 3 "
                             "BEFORE writing mutation N+1. Writes already made are not "
                             "rolled back — the abort message says exactly what landed.")

    def add_write_gate(sp):
        """--dry-run / --apply. Live runs preview by default; offline runs apply."""
        g = sp.add_mutually_exclusive_group()
        g.add_argument("--dry-run", action="store_true",
                       help="print the mutation plan (urn, tool, field, before → after) "
                            "and write NOTHING. Default against a live catalog.")
        g.add_argument("--apply", "--yes", dest="apply", action="store_true",
                       help="actually write. REQUIRED for any live mutating run.")
        add_budget(sp)

    sp = sub.add_parser("scan", help="sweep the catalog for injections")
    add_offline(sp)
    sp.add_argument("--fail-on-hit", action="store_true", help="exit 1 if any hit (CI)")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("cure", help="defuse every hit by removal")
    add_offline(sp)
    add_write_gate(sp)
    sp.add_argument("--fixtures", choices=["corpus", "none"], default="corpus",
                    help="corpus = exact fixture-backed excision; none = field quarantine")
    sp.add_argument("--only-mode", choices=["all", "excise", "quarantine-field"],
                    default="all",
                    help="restrict to one remediation mode. `excise` is the surgical "
                         "fixture-backed path (safe to automate); `quarantine-field` "
                         "replaces the WHOLE field and is the one to hold for a human.")
    sp.set_defaults(func=cmd_cure)

    sp = sub.add_parser("blast-radius", help="map downstream reach of poisoned entities")
    add_offline(sp)
    add_write_gate(sp)
    sp.set_defaults(func=cmd_blast_radius)

    sp = sub.add_parser("rescan", help="tamper-evidence drift check")
    add_offline(sp)
    sp.add_argument("--fail-on-hit", action="store_true")
    sp.set_defaults(func=cmd_rescan)

    sp = sub.add_parser("certify", help="tag the clean remainder agent-safe-certified")
    add_offline(sp)
    add_write_gate(sp)
    sp.set_defaults(func=cmd_certify)

    sp = sub.add_parser("demo", help="run the full hero arc on the corpus")
    add_offline(sp)
    sp.add_argument("--apply", "--yes", dest="apply", action="store_true",
                    help="required to run the arc against a LIVE catalog (it mutates)")
    add_budget(sp)
    sp.set_defaults(func=cmd_demo)

    sp = sub.add_parser("detect", help="score a single string")
    sp.add_argument("text")
    sp.set_defaults(func=cmd_detect)

    sp = sub.add_parser("corpus", help="print attack-corpus statistics")
    sp.set_defaults(func=cmd_corpus)
    return p


def main(argv=None) -> int:
    from .planner import MutationBudgetExceeded
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except MutationBudgetExceeded as exc:
        # Exit 3 is deliberately distinct from 1 (findings) and 2 (refused/degraded):
        # a CI job must be able to tell "the catalog is dirty" from "the breaker
        # tripped and the catalog is now half-remediated".
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

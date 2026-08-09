"""`antigen` command-line interface.

Subcommands map to the engine:

    antigen scan     [--offline] [--fail-on-hit] [--json]   sweep the catalog
                     [--urn-contains P] [--max-entities N]  …scoped to one domain
                     [--include-quarantined]                …including cured entities
    antigen cure     [--offline] [--dry-run|--apply]        defuse every hit
                     [--excise-span]                        …cutting the span in place
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
`cure` writes 4 tool calls per entity/column hit (2 for a KB-document hit), `certify`
2 per *clean* entity (~2,000 on a 1k catalog). Those are the units `--max-mutations`
charges; the dry-run plan prints one ROW per aspect VALUE, which is more (see
`planner`). So:

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

Exit 1 means ONE thing: a working sweep found injections. Every infrastructure
failure — unreachable GMS, wrong URL, missing live extras, an unencodable response —
is exit 2, because it establishes nothing about the catalog. `main()` enforces that
for uncaught exceptions too; without it Python's default exit 1 reported a dead GMS
to CI as a dirty catalog.
"""

from __future__ import annotations

import argparse
import json
import os
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


def _warn_degraded(reasons: list[str]) -> bool:
    """Print the fail-closed degradation banner; return True if the run was degraded.

    Fail CLOSED. An empty or unreachable catalog reads identically to a clean one on
    the wire, so any command that concludes "nothing to do" from an enumeration goes
    green forever against a wrong `DATAHUB_GMS_URL`. `scan` carried this check alone,
    which left it missing from `rescan` — the one command actually designed to live in
    a metadata-CI job, where `--fail-on-hit` passing for the wrong reason is the whole
    failure mode. Exit 2 is reserved for it, distinct from the 1 that means "the sweep
    worked and found something".
    """
    if not reasons:
        return False
    for reason in reasons:
        print(f"WARNING: {reason}", file=sys.stderr)
    print("DEGRADED SWEEP — this is NOT an all-clear. Check DATAHUB_GMS_URL / "
          "DATAHUB_GMS_TOKEN and the tool env flags, then re-run.", file=sys.stderr)
    return True


def _enumeration_reasons(gw, urns: list[str]) -> list[str]:
    """Degradation reasons for a command that enumerates the catalog without `scan`."""
    from .scan import EMPTY_CATALOG_REASON
    reasons: list[str] = [] if urns else [EMPTY_CATALOG_REASON]
    reasons += list(getattr(gw, "degradations", list)())
    return reasons


def cmd_scan(args) -> int:
    from .scan import Scope, scan
    gw, _ = _gateway(args)
    report = scan(gw, skip_quarantined=not args.include_quarantined,
                  scope=Scope(urn_contains=args.urn_contains,
                              max_entities=args.max_entities))
    if args.json:
        print(json.dumps({
            "summary": report.summary(),
            "degraded": report.degraded,
            "degraded_reasons": report.degraded_reasons,
            "scope": report.scope.describe() if report.scope else None,
            "entities_enumerated": report.entities_enumerated,
            "entities_in_scope": report.entities_in_scope,
            "entities_scanned": report.entities_scanned,
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
    if report.scope is not None and report.scope_empty:
        # Loud on stderr, but exit 0 and NOT a degradation: the operator asked for
        # this set and it is empty. A CI log still shows the line, so a typo'd filter
        # is visible rather than silently green.
        print(f"NOTICE: {report.scope.describe()} matched 0 of "
              f"{report.entities_enumerated} enumerated entities — nothing was "
              "scanned. That is your scope, not a blackout; widen it or drop it to "
              "sweep the catalog.", file=sys.stderr)
    _warn_degraded(report.degraded_reasons)
    if args.fail_on_hit and report.hits:
        print(f"\nFAIL: {len(report.hits)} injection loci present (--fail-on-hit).",
              file=sys.stderr)
        return 2 if report.degraded else 1
    return 2 if report.degraded else 0


def cmd_cure(args) -> int:
    from .cure import EXCISION_MODES, cure, plan_remediation
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
        # `--only-mode excise` means "the surgical half" — the modes that KEEP the
        # human-written text around the payload. It asks the real planner what each
        # hit would get rather than re-deriving it from fixture membership, so
        # `--excise-span` widens this set on a real catalog instead of leaving the
        # flag a guaranteed no-op outside the demo corpus.
        want_excision = args.only_mode == "excise"
        hits = [h for h in hits
                if (plan_remediation(h, fixtures, excise_span=args.excise_span).mode
                    in EXCISION_MODES) is want_excision]
    result = cure(target, hits, fixtures=fixtures, clock=_clock(),
                  excise_span=args.excise_span)
    if plan is not None:
        # The in-place cuts, before the mutation plan: an approver has to read what is
        # being removed and what survives, which a collapsed before/after cannot show.
        preview = result.excision_preview()
        if preview:
            print(preview + "\n")
        rc = _print_plan(plan, "cure")
        return 2 if _warn_degraded(report.degraded_reasons) else rc
    print(result.summary())
    for a in result.actions:
        print(f"  ✔ {a.payload_id}  {a.urn}  [{a.mode}]  content={a.content_sha256[:12]}…")
    # A cure is only as complete as the sweep that fed it: a degraded read means the
    # loci NOT in this list were never looked at, so "cured N" must not read as done.
    return 2 if _warn_degraded(report.degraded_reasons) else 0


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
        rc = _print_plan(plan, "blast-radius")
        return 2 if _warn_degraded(report.degraded_reasons) else rc
    print(br.summary())
    for src, downstream in br.per_source.items():
        if downstream:
            print(f"  {src} → {len(downstream)} downstream")
    # Sources come from the sweep, so a degraded sweep means an under-counted radius.
    return 2 if _warn_degraded(report.degraded_reasons) else 0


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
    degraded = _warn_degraded(_enumeration_reasons(gw, all_urns))
    if args.fail_on_hit and result.drifted:
        return 2 if degraded else 1
    return 2 if degraded else 0


def cmd_certify(args) -> int:
    from .certify import certify
    from .scan import scan
    gw, _ = _gateway(args)
    target, plan = _writer(args, gw)
    report = scan(target)
    result = certify(target, report.clean_entity_urns, clock=_clock())
    if plan is not None:
        rc = _print_plan(plan, "certify")
        return 2 if _warn_degraded(report.degraded_reasons) else rc
    print(result.summary())
    # Certifying off a degraded sweep would stamp `agent-safe-certified` on entities
    # whose neighbours were never read — the worst possible thing to get wrong.
    return 2 if _warn_degraded(report.degraded_reasons) else 0


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
        # `demo` is the whole write-back arc — sweep, 4 write-back calls per hit, one
        # tag + two properties per clean entity, then blast-radius tags. There is no
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
    sp.add_argument("--urn-contains", metavar="PATTERN", default=None,
                    help="scope the sweep to URNs containing PATTERN — entities AND "
                         "KB documents (case-insensitive SUBSTRING, not a regex: a "
                         "DataHub URN is full of regex metacharacters). Pilot on one "
                         "domain without minting a second scoped service account.")
    sp.add_argument("--max-entities", type=int, default=None, metavar="N",
                    help="scope the sweep to the first N enumerated ENTITIES (applied "
                         "after --urn-contains; documents are not truncated). A scope "
                         "that matches nothing exits 0 with a NOTICE — it is a filter, "
                         "not a degraded sweep.")
    sp.add_argument("--include-quarantined", action="store_true",
                    help="also scan entities already tagged `injection-quarantined`. "
                         "The default skips them (idempotency), which means a RE-"
                         "poisoned cured entity is invisible to `scan`; `rescan` "
                         "catches that via content drift, and this flag forces the "
                         "full re-sweep directly.")
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("cure", help="defuse every hit by removal")
    add_offline(sp)
    add_write_gate(sp)
    sp.add_argument("--fixtures", choices=["corpus", "none"], default="corpus",
                    help="corpus = exact fixture-backed excision; none = field quarantine")
    sp.add_argument("--only-mode", choices=["all", "excise", "quarantine-field"],
                    default="all",
                    help="restrict to one remediation mode. `excise` is the surgical "
                         "half that keeps the surrounding documentation — "
                         "fixture-backed, plus span-excised when --excise-span is on; "
                         "`quarantine-field` replaces the WHOLE field and is the one "
                         "to hold for a human.")
    sp.add_argument("--excise-span", action="store_true",
                    help="OPT-IN, never the default. For a hit with no fixture, cut "
                         "the detector's matched span out of the field and KEEP the "
                         "text around it, instead of replacing the whole field. The "
                         "dry-run plan prints the removed span and the survivor side "
                         "by side. Any doubt — no span, a span that does not fit the "
                         "text, nothing left over, or a survivor that still trips the "
                         "detector — falls back to quarantine-field.")
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


#: Set to any non-empty value to re-raise instead of mapping to exit 2. Catching
#: everything is what makes the exit taxonomy true; it must not also make Antigen
#: undebuggable, so the traceback stays one env var away.
TRACEBACK_ENV = "ANTIGEN_TRACEBACK"


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
    except ModuleNotFoundError as exc:
        # `python -m antigen scan` with no live extras installed. Common enough — and
        # recoverable enough — to deserve its own sentence rather than the generic one.
        print(f"REFUSED: the live path needs the DataHub extras ({exc}). Install them "
              "with `pip install -r requirements.txt` (or `pip install "
              "'antigen-datahub[live]'`), or run against the in-memory corpus double "
              "with --offline.", file=sys.stderr)
        return 2
    except Exception as exc:   # noqa: BLE001 - the exit code IS the contract here
        # THE EXIT TAXONOMY, made true. Everything that escaped this block used to
        # exit 1 — the code the shipped adopter workflow
        # (`examples/ci/metadata-injection-scan.yml`) reads as
        # "::error::Antigen found prompt injections in catalog metadata".
        # So a wrong DATAHUB_GMS_URL, a dead GMS, or a lone surrogate that the
        # content hash cannot encode were all reported to CI as a DIRTY CATALOG,
        # which is precisely the confusion exit 2 exists to prevent. An
        # infrastructure failure establishes nothing, and "establishes nothing" is
        # exit 2 in every other command here.
        if os.environ.get(TRACEBACK_ENV):
            raise
        print(f"DEGRADED SWEEP — Antigen could not establish anything: {exc!r}. This "
              "is an infrastructure failure, NOT a finding: nothing about the catalog "
              "was determined either way. Check DATAHUB_GMS_URL / DATAHUB_GMS_TOKEN "
              f"and the tool env flags. Re-run with {TRACEBACK_ENV}=1 for the full "
              "traceback.", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

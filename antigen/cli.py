"""`antigen` command-line interface.

Subcommands map to the engine:

    antigen scan     [--offline] [--fail-on-hit] [--json]   sweep the catalog
    antigen cure     [--offline] [--fixtures corpus|none]   defuse every hit
    antigen blast-radius [--offline]                        map downstream reach
    antigen rescan   [--offline]                            tamper-evidence drift
    antigen certify  [--offline]                            tag the clean remainder
    antigen demo     [--offline]                            the full hero arc
    antigen detect   "<text>"                               score one string
    antigen corpus                                          print corpus stats

`--offline` runs against the in-memory corpus double (no Docker) — useful for a
quick look; the judge path is the live GMS (omit `--offline`, set DATAHUB_GMS_URL /
DATAHUB_GMS_TOKEN). Live scanning uses the real 8 Agent Context Kit tools.
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


def cmd_scan(args) -> int:
    from .scan import scan
    gw, _ = _gateway(args)
    report = scan(gw)
    if args.json:
        print(json.dumps({
            "summary": report.summary(),
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
    if args.fail_on_hit and report.hits:
        print(f"\nFAIL: {len(report.hits)} injection loci present (--fail-on-hit).",
              file=sys.stderr)
        return 1
    return 0


def cmd_cure(args) -> int:
    from .cure import cure
    from .scan import scan
    gw, fixtures = _gateway(args)
    report = scan(gw)
    hits = report.hits
    if args.fixtures == "corpus":
        hits = [h for h in report.hits if h.key in fixtures]
    result = cure(gw, hits, fixtures=fixtures, clock=_clock())
    print(result.summary())
    for a in result.actions:
        print(f"  ✔ {a.payload_id}  {a.urn}  [{a.mode}]  content={a.content_sha256[:12]}…")
    return 0


def cmd_blast_radius(args) -> int:
    from .blast_radius import map_blast_radius
    from .scan import scan
    gw, _ = _gateway(args)
    report = scan(gw)
    # Sources = entities that scan flagged (or that already carry the quarantine tag).
    sources = sorted({h.urn for h in report.hits if h.locus.value != "kb-document"})
    br = map_blast_radius(gw, sources)
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
    report = scan(gw)
    result = certify(gw, report.clean_entity_urns)
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

    gw, fixtures = _gateway(args)
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
    cert = certify(gw, report.clean_entity_urns)
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

    sp = sub.add_parser("scan", help="sweep the catalog for injections")
    add_offline(sp)
    sp.add_argument("--fail-on-hit", action="store_true", help="exit 1 if any hit (CI)")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("cure", help="defuse every hit by removal")
    add_offline(sp)
    sp.add_argument("--fixtures", choices=["corpus", "none"], default="corpus",
                    help="corpus = exact fixture-backed excision; none = field quarantine")
    sp.set_defaults(func=cmd_cure)

    sp = sub.add_parser("blast-radius", help="map downstream reach of poisoned entities")
    add_offline(sp)
    sp.set_defaults(func=cmd_blast_radius)

    sp = sub.add_parser("rescan", help="tamper-evidence drift check")
    add_offline(sp)
    sp.add_argument("--fail-on-hit", action="store_true")
    sp.set_defaults(func=cmd_rescan)

    sp = sub.add_parser("certify", help="tag the clean remainder agent-safe-certified")
    add_offline(sp)
    sp.set_defaults(func=cmd_certify)

    sp = sub.add_parser("demo", help="run the full hero arc on the corpus")
    add_offline(sp)
    sp.set_defaults(func=cmd_demo)

    sp = sub.add_parser("detect", help="score a single string")
    sp.add_argument("text")
    sp.set_defaults(func=cmd_detect)

    sp = sub.add_parser("corpus", help="print attack-corpus statistics")
    sp.set_defaults(func=cmd_corpus)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

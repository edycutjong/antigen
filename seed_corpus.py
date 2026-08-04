"""seed_corpus.py — plant the attack corpus into a LIVE DataHub instance.

This is the ONLY step that writes attacker-controlled text into the graph, and it is
labeled demo input everywhere. It plants the 12 authored payloads (8 entity / 2 column
/ 2 doc) + the 3 held-out public injections into a fresh `showcase-ecommerce` load,
using the same SDK mutation surface an attacker with catalog-edit access would have.

    python seed_corpus.py                 # plant into $DATAHUB_GMS_URL
    python seed_corpus.py --reset-note    # print how to reset (reload the datapack)

URN resilience: if a planned target URN is absent on the judge's datapack build, the
payload is re-homed onto the first available real entity returned by `search`, and the
effective locus map is written to `.antigen-locus-map.json` so `cure`/`verify` line up.
The pristine datapack is never mutated in place — reset by reloading it.
"""

from __future__ import annotations

import argparse
import json
import sys

from antigen.corpus import HELD_OUT, PAYLOADS, Locus

LOCUS_MAP_FILE = ".antigen-locus-map.json"


def plant(gw, verbose: bool = True) -> dict:
    existing = set(gw.search_all())
    spare = [u for u in existing]  # fallback pool
    locus_map: dict[str, str] = {}

    def resolve(urn: str) -> str:
        if urn in existing:
            return urn
        # re-home onto a real entity not already used
        for cand in spare:
            if cand not in locus_map.values():
                if verbose:
                    print(f"  [re-home] {urn} absent → {cand}")
                return cand
        raise RuntimeError("no spare entity to re-home payload onto")

    planted = 0
    for p in PAYLOADS:
        if p.locus is Locus.KB_DOCUMENT:
            # create/overwrite the host KB document by (parent, title) — the identity
            # the cure will later reuse to overwrite it in place.
            gw.save_document(title=p.doc_title, content=p.poisoned_text,
                             parent=p.doc_parent)
            locus_map[p.id] = f"{p.doc_parent}/{p.doc_title}"
            planted += 1
            continue
        target = resolve(p.urn)
        locus_map[p.id] = target
        gw.update_description(target, p.poisoned_text, field_path=p.field_path)
        planted += 1

    for h in HELD_OUT:
        target = resolve(h.urn)
        locus_map[h.id] = target
        gw.update_description(target, f"{h.original_text} {h.injection}")

    with open(LOCUS_MAP_FILE, "w") as fh:
        json.dump(locus_map, fh, indent=2)

    if verbose:
        print(f"planted {planted} payloads + {len(HELD_OUT)} held-out injections")
        print(f"effective locus map → {LOCUS_MAP_FILE}")
    return locus_map


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reset-note", action="store_true")
    args = ap.parse_args(argv)
    if args.reset_note:
        print("Reset by reloading the pristine datapack:\n"
              "  datahub datapack load showcase-ecommerce --force")
        return 0
    from antigen.gateway import SdkGateway
    try:
        gw = SdkGateway()
    except Exception as exc:  # noqa: BLE001
        print(f"Cannot connect to DataHub ({exc}).\n"
              "Start it with `datahub docker quickstart`, set DATAHUB_GMS_URL / "
              "DATAHUB_GMS_TOKEN, then re-run. For an offline look, use "
              "`python -m antigen demo --offline`.", file=sys.stderr)
        return 2
    plant(gw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

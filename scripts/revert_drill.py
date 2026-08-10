"""revert_drill.py — measure what it really costs to undo a false-positive `cure`.

README.md says, in two places, that recovering from a bad cure is **"one action"**
against DataHub's native aspect version history. Until this script that sentence
had only ever been exercised against `InMemoryGateway` — the dict this repo wrote
to imitate GMS. This drill exercises it against a **real** DataHub GMS and counts
the HTTP calls, so the claim is either backed by a transcript or corrected by one.

It is deliberately a DRILL, not a feature. Antigen ships no undo, and nothing in
`antigen/` is changed to make this pass: the revert is performed with the stock
`acryl-datahub` SDK and raw GMS endpoints, because that is all an operator has.

WHAT IT DOES, end to end, against `DATAHUB_GMS_URL`:

  0.  Hard-deletes its own drill URN first, so aspect version history is
      deterministic on a re-run. It touches no entity it did not seed.
  1.  Loads two REAL false positives out of `docs/fp-corpus-manifest.json` by
      sha256 — no invented strings — and re-asserts the shipped detector flags
      them.
  2.  Measures the live read path's 1,000-character description truncation
      (`datahub_agent_context.mcp_tools.helpers.DESCRIPTION_LENGTH_HARD_LIMIT`),
      which decides which of the 24 measured false positives Antigen can even
      see on a live GMS. This is why the two strings are used at the loci they
      are used at.
  3.  Seeds one dataset with a realistic curation history: a draft, then the
      curated dataset description, then two curated column descriptions.
  4.  Runs the real `python -m antigen cure --apply` path over it.
  5.  Reverts the dataset description three ways, counting every HTTP request:
      the literal one-call reading, the version-probe, and the timeline API.
  6.  Reverts the column description — where the aspect holds ALL columns — and
      measures whether a sibling column edited after the cure survives it.
  7.  Reports the residue a description revert does not undo (tag, structured
      properties, incident document, and what `scan` does afterwards).
  8.  Cleans up and leaves the catalog as it found it.

USAGE:

    export DATAHUB_GMS_URL=http://localhost:8080
    python scripts/revert_drill.py                        # run, then clean up
    python scripts/revert_drill.py --keep                 # leave the entity behind
    python scripts/revert_drill.py --transcript out.json  # machine-readable record

Requires the live extras (`pip install -r requirements.txt`).
Exit 0 = the drill ran and every assertion about DataHub held.
Exit 1 = an assertion failed — that is a finding, read the output.
Exit 2 = it could not run (no GMS, no SDK, catalog not in a fit state).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

MANIFEST = REPO / "docs" / "fp-corpus-manifest.json"

#: Flagged string [9] of 24 in the false-positive study — `highways.hidot.hawaii.gov`
#: dataset `2tw7-ygpr`, 557 chars, score 2, rule
#: `exfiltration ('email' … 'email' → 'https://files.hawaii.gov/…/blkgrp20.pdf')`.
#: Class A (contact-and-link boilerplate), the class that is 21 of the 24 measured
#: flags. Used at the DATASET locus because it is short enough to survive the live
#: read path's 1,000-character truncation — see `phase_truncation`.
FP_ENTITY_SHA = "cdc68278bda75023e0b24b11e877fbea78ad318078b1f0a5e38bda1378fca1c4"

#: Flagged string [13] of 24 — `opendata.maryland.gov` dataset `3xda-h6fq`,
#: 3,448 chars, Class A, rule `exfiltration ('Email' … 'Email' → 'GIS@mdot.state.md.us')`.
#: This is the expensive case the study warns about: a long, hand-curated
#: description in the ~4.7%-above-2,000-characters bucket. Used at the COLUMN
#: locus, because column descriptions are read through the base SDK aspect
#: (`SdkGateway._merge_editable_columns`) and are therefore NOT truncated, so the
#: detector sees all 3,448 characters and `cure` replaces all 3,448 characters.
FP_COLUMN_SHA = "0724d11f47d9bfff1f93d2f4e0e2a06853faf2802a53529b96db5f6f81dd92b2"

DRILL_PLATFORM = "socrata"
DRILL_NAME = "antigen_revert_drill.hidot.census_block_groups_2020"

FLAGGED_COLUMN = "layer_notes"
SIBLING_COLUMN = "objectid"

#: The steward's first pass, replaced later. Present so the cured field has more
#: than one predecessor — which is the realistic case, and the whole story.
DRAFT_TEXT = ("2020 Census block group boundaries for Hawaii. "
              "DRAFT - provenance and contact details to be added.")

SIBLING_BEFORE = "Feature identifier assigned by the source GIS."
SIBLING_AFTER = ("Feature identifier assigned by the source GIS. "
                 "Stable across annual republication; safe to join on.")

#: Mutation names that would constitute a UI/API "revert this field" control.
#: Checked against the live GraphQL schema — the API the DataHub frontend is
#: built on — rather than asserted.
REVERT_MUTATION_PATTERN = r"revert|rollback|restore|undo|history|version"

#: `datahub_agent_context.mcp_tools.helpers.DESCRIPTION_LENGTH_HARD_LIMIT` in the
#: pinned 1.6.0.17. Re-read from the installed package at runtime, never trusted
#: from this constant.
EXPECTED_DESC_LIMIT = 1000


# --------------------------------------------------------------------------- #
# transcript plumbing
# --------------------------------------------------------------------------- #
class Transcript:
    """Console + structured record. Every number in the write-up comes from here."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.started = _utcnow()

    def say(self, line: str = "") -> None:
        print(line, flush=True)

    def head(self, title: str) -> None:
        self.say("")
        self.say("=" * 78)
        self.say(title)
        self.say("=" * 78)

    def step(self, name: str, **detail) -> None:
        rec = {"t": _utcnow(), "step": name, **detail}
        self.events.append(rec)
        extra = "  ".join(f"{k}={v}" for k, v in detail.items())
        self.say(f"[{rec['t']}] {name}" + (f"\n    {extra}" if extra else ""))

    def dump(self, path: Path, summary: dict) -> None:
        path.write_text(json.dumps(
            {"started": self.started, "finished": _utcnow(),
             "summary": summary, "events": self.events}, indent=2) + "\n",
            encoding="utf-8")


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CallCounter:
    """Counts every HTTP request the SDK makes to GMS, by patching requests.Session.

    The action counts in the write-up are not a hand tally of what the code looks
    like it does; they are this counter. `get_aspect` and `emit` both go through
    `requests.Session.request`, so nothing hides.
    """

    def __init__(self) -> None:
        import requests

        self._requests = requests
        self._orig = requests.Session.request
        self.calls: list[dict] = []
        self.on = False
        counter = self

        def patched(session, method, url, *a, **kw):
            resp = counter._orig(session, method, url, *a, **kw)
            if counter.on:
                counter.calls.append({"method": method, "url": _short(url),
                                      "status": getattr(resp, "status_code", None)})
            return resp

        requests.Session.request = patched  # type: ignore[assignment]

    def restore(self) -> None:
        self._requests.Session.request = self._orig  # type: ignore[assignment]

    def start(self) -> None:
        self.calls = []
        self.on = True

    def stop(self) -> list[dict]:
        self.on = False
        return list(self.calls)


def _short(url: str) -> str:
    return urllib.parse.unquote(url)


def _report_calls(t: Transcript, calls: list[dict]) -> None:
    for c in calls:
        t.say(f"      {c['method']:<5} {c['status']}  {c['url'][:150]}")


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keep", action="store_true",
                    help="leave the drill entity in the catalog (default: hard-delete)")
    ap.add_argument("--transcript", metavar="PATH",
                    default=str(REPO / "docs" / "revert-drill-transcript.json"),
                    help="where to write the machine-readable record")
    args = ap.parse_args(argv)

    t = Transcript()
    gms = os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")
    token = os.environ.get("DATAHUB_GMS_TOKEN") or None

    t.head("Antigen — false-positive revert drill (LIVE DataHub GMS)")

    try:
        from datahub.ingestion.graph.client import DatahubClientConfig, DataHubGraph
    except ImportError as exc:  # pragma: no cover - environment
        t.say(f"CANNOT RUN: {exc}. Install the live extras: "
              "pip install -r requirements.txt")
        return 2

    # MUST precede the DataHubGraph construction: `DataHubGraph.__init__` rebinds
    # `self._session.request` to a `functools.partial` of whatever the class
    # attribute is AT THAT MOMENT. Patch afterwards and every SDK call goes
    # uncounted — which is exactly how the first run of this drill reported a
    # revert costing 0 HTTP calls.
    counter = CallCounter()

    graph = DataHubGraph(DatahubClientConfig(server=gms, token=token))
    try:
        cfg = graph.get_config()
    except Exception as exc:  # pragma: no cover - environment
        counter.restore()
        t.say(f"CANNOT RUN: GMS at {gms} unreachable ({exc}).")
        return 2

    version = str(_dig(cfg, "versions", "acryldata/datahub", "version") or "?")
    t.step("preflight", gms=gms, gms_version=version)

    summary: dict = {"gms": gms, "gms_version": version, "started": t.started}
    try:
        code = _run(t, graph, counter, summary, args, gms=gms, token=token)
    finally:
        counter.restore()
        summary["finished"] = _utcnow()
        t.dump(Path(args.transcript), summary)
        t.say(f"\ntranscript -> {args.transcript}")
    return code


def _dig(obj, *keys):
    for k in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


# --------------------------------------------------------------------------- #
# the drill
# --------------------------------------------------------------------------- #
def _run(t: Transcript, graph, counter: CallCounter, summary: dict, args, *,
         gms: str, token) -> int:
    from datahub.emitter.mce_builder import make_dataset_urn
    from datahub.emitter.mcp import MetadataChangeProposalWrapper as MCPW
    from datahub.metadata.schema_classes import (
        AuditStampClass,
        DatasetPropertiesClass,
        EditableDatasetPropertiesClass,
        EditableSchemaMetadataClass,
        OtherSchemaClass,
        SchemaFieldClass,
        SchemaFieldDataTypeClass,
        SchemaMetadataClass,
        StringTypeClass,
    )

    from antigen.cure import CONTENT_SHA_PROP, PAYLOAD_SHA_PROP, QUARANTINE_TEXT
    from antigen.detect import detect
    from antigen.gateway import SdkGateway
    from antigen.scan import INCIDENT_TITLE_PREFIX, QUARANTINE_TAG

    # The two aspects this whole drill is about, kept short at the call sites.
    EDP = EditableDatasetPropertiesClass    # the dataset description
    ESM = EditableSchemaMetadataClass       # EVERY curated column description

    urn = make_dataset_urn(platform=DRILL_PLATFORM, name=DRILL_NAME, env="PROD")
    summary["urn"] = urn
    t.step("drill_urn", urn=urn)

    # -- 0. deterministic slate --------------------------------------------- #
    graph.hard_delete_entity(urn)
    t.step("clean_slate", note="hard-deleted the drill URN if a previous run left one")
    _await_absent(SdkGateway(), urn, t)

    # -- 1. the two false positives, straight out of the study --------------- #
    items = json.loads(MANIFEST.read_text(encoding="utf-8"))["flagged_items"]
    by_sha = {i["sha256"]: i for i in items}
    ent_item = by_sha.get(FP_ENTITY_SHA)
    col_item = by_sha.get(FP_COLUMN_SHA)
    if ent_item is None or col_item is None:
        t.say("CANNOT RUN: fp-corpus-manifest.json does not contain the two "
              "sha256s this drill pins.")
        return 2
    curated = ent_item["text"]
    col_curated = col_item["text"]
    for label, text, item in (("dataset", curated, ent_item),
                              ("column", col_curated, col_item)):
        d = detect(text)
        t.step(f"false_positive_{label}", origin=item["origin"], ref=item["ref"],
               chars=len(text), sha256=item["sha256"][:16], flagged=d.flagged,
               score=d.score, rule=d.rule_fired)
        if not d.flagged:
            t.say("FINDING: the shipped detector no longer flags this string; the "
                  "false-positive study needs regenerating.")
            return 1
    summary["false_positives"] = {
        "dataset_locus": {"origin": ent_item["origin"], "ref": ent_item["ref"],
                          "chars": len(curated), "sha256": FP_ENTITY_SHA,
                          "rule_fired": ent_item["rule_fired"]},
        "column_locus": {"origin": col_item["origin"], "ref": col_item["ref"],
                         "chars": len(col_curated), "sha256": FP_COLUMN_SHA,
                         "rule_fired": col_item["rule_fired"]},
    }

    # -- 2. the live read path truncates descriptions ------------------------ #
    if not _phase_truncation(t, summary, items, detect):
        return 1

    # -- 3. seed the entity and a realistic curation history ----------------- #
    stamp = AuditStampClass(time=0, actor="urn:li:corpuser:datahub")
    graph.emit(MCPW(entityUrn=urn, aspect=DatasetPropertiesClass(
        name=DRILL_NAME.split(".")[-1], qualifiedName=DRILL_NAME,
        description="2020 Census block groups, Hawaii. Ingested metadata.")))
    graph.emit(MCPW(entityUrn=urn, aspect=SchemaMetadataClass(
        schemaName=DRILL_NAME, platform=f"urn:li:dataPlatform:{DRILL_PLATFORM}",
        version=0, hash="", created=stamp, lastModified=stamp,
        platformSchema=OtherSchemaClass(rawSchema=""),
        fields=[SchemaFieldClass(fieldPath=fp,
                                 type=SchemaFieldDataTypeClass(type=StringTypeClass()),
                                 nativeDataType="VARCHAR", description=desc)
                for fp, desc in ((SIBLING_COLUMN, "Feature identifier."),
                                 (FLAGGED_COLUMN, "Layer notes."))])))
    t.step("seeded_entity", aspects="datasetProperties + schemaMetadata",
           columns=f"{SIBLING_COLUMN}, {FLAGGED_COLUMN}")

    gw = SdkGateway()
    gw.update_description(urn, DRAFT_TEXT)
    t.step("steward_edit_1_dataset_draft", chars=len(DRAFT_TEXT),
           sha256=sha(DRAFT_TEXT)[:16])
    gw.update_description(urn, curated)
    t.step("steward_edit_2_dataset_curated", chars=len(curated),
           sha256=sha(curated)[:16], note="THIS is what must come back")
    gw.update_description(urn, SIBLING_BEFORE, field_path=SIBLING_COLUMN)
    gw.update_description(urn, col_curated, field_path=FLAGGED_COLUMN)
    t.step("steward_edit_3_columns", sibling_chars=len(SIBLING_BEFORE),
           flagged_column_chars=len(col_curated),
           sha256=sha(col_curated)[:16])

    stored = _stored_description(graph, urn, EDP)
    if stored != curated:
        t.say("CANNOT RUN: the seeded dataset description did not store intact.")
        return 2

    if not _await_scannable(gw, urn, t, detect, FLAGGED_COLUMN):
        t.say("CANNOT RUN: the drill entity never became readable-and-flagged "
              "through the live read path.")
        return 2

    # -- 4. the real cure path ----------------------------------------------- #
    t.head("CURE — the shipped path, against the live GMS")
    plan = _antigen("cure", "--dry-run")
    t.say(plan.stdout.rstrip() or plan.stderr.rstrip())
    # Every dataset URN the plan names must be this drill's. Incident documents
    # (`urn:li:document:…`) are the cure's own output and are cleaned up at the end.
    #
    # Only the action lines are parsed. The `before:` / `after:` previews quote
    # entity text and elide it with an ellipsis, so a URN found there is a
    # fragment, not a target.
    tools = ("update_description", "add_tags", "add_structured_properties",
             "save_document")
    action_lines = [ln.strip() for ln in plan.stdout.splitlines()
                    if ln.strip().startswith(tools)]
    hits, foreign = [], set()
    for ln in action_lines:
        for i in range(len(ln)):
            if ln.startswith("urn:li:dataset:", i):
                hits.append(ln)
                if not ln.startswith(urn, i):
                    foreign.add(ln[i:i + 140].split()[0])
    loci = sum(1 for ln in action_lines if ln.startswith("update_description"))
    if not hits:
        t.say("\nCANNOT RUN: the dry-run plan names no dataset — the drill entity is "
              "not being flagged live. Re-check the truncation phase above.")
        return 2
    if foreign:
        t.say(f"\nCANNOT RUN: the plan also targets {sorted(foreign)}. Refusing to write "
              "against entities this drill did not seed. Re-seed the demo corpus "
              "(`./run.sh live`) and retry.")
        return 2
    t.step("cure_plan_verified", update_description_loci=loci, only=urn)

    applied = _antigen("cure", "--apply", "--max-mutations", "8")
    t.say("")
    t.say(applied.stdout.rstrip() or applied.stderr.rstrip())
    t.step("cure_applied", exit_code=applied.returncode)

    cured_ds = _stored_description(graph, urn, EDP)
    cured_col = _stored_column(graph, urn, ESM, FLAGGED_COLUMN)
    t.step("fields_after_cure",
           dataset_chars=len(cured_ds), dataset_sha256=sha(cured_ds)[:16],
           column_chars=len(cured_col or ""),
           curated_dataset_text_gone=(curated not in cured_ds),
           curated_column_text_gone=(col_curated not in (cured_col or "")))
    if QUARANTINE_TEXT not in cured_ds:
        t.say("FINDING: the cured dataset field is not the whole-field quarantine "
              "banner. The drill assumed the no-fixture path; read the plan above.")
        return 1
    summary["cure"] = {
        "exit_code": applied.returncode,
        "dataset_chars_before": len(curated), "dataset_chars_after": len(cured_ds),
        "column_chars_before": len(col_curated),
        "column_chars_after": len(cured_col or ""),
        "update_description_loci": loci,
    }
    t.say(f"\n  {len(curated)} characters of curated dataset documentation and "
          f"{len(col_curated)} characters of curated column documentation are GONE "
          "from the live fields.")
    t.say("  Antigen stored no copy of either. Everything below is DataHub's "
          "history, not Antigen's.")

    # -- 5. revert the dataset description, three ways ----------------------- #
    ok = _phase_revert_dataset(t, summary, graph, counter, urn, curated, EDP, MCPW,
                               gms=gms, token=token)
    if ok != 0:
        return ok

    # -- 6. revert the column description ------------------------------------ #
    ok = _phase_revert_column(t, summary, graph, counter, gw, urn, col_curated,
                              ESM, MCPW)
    if ok != 0:
        return ok

    # -- 7. residue ----------------------------------------------------------- #
    # `grep_documents` is a content search, so the incident documents are found by
    # the incident IDs `cure` printed, not by the title prefix (which also matches
    # the corpus documents that merely mention it).
    incident_ids = sorted(set(re.findall(r"adhoc-[0-9a-f]{12}", applied.stdout)))
    _phase_residue(t, summary, gw, urn, QUARANTINE_TAG, CONTENT_SHA_PROP,
                   PAYLOAD_SHA_PROP, INCIDENT_TITLE_PREFIX, incident_ids)

    # -- 7b. is there a UI path? ---------------------------------------------- #
    _phase_ui_path(t, summary, gms=gms, token=token)

    # -- 8. cleanup ------------------------------------------------------------ #
    incidents = summary["residue"]["incident_documents"]
    if args.keep:
        t.step("cleanup_skipped", note="--keep: drill entity left in the catalog")
    else:
        for doc_urn in incidents:
            graph.hard_delete_entity(doc_urn)
        graph.hard_delete_entity(urn)
        t.step("cleanup", hard_deleted=1 + len(incidents),
               note="drill entity + the incident documents this run created")

    _phase_ledger(t, summary)
    return 0


# --------------------------------------------------------------------------- #
# phases
# --------------------------------------------------------------------------- #
def _phase_truncation(t: Transcript, summary: dict, items: list[dict], detect) -> bool:
    """How much of a description does Antigen's live read path actually see?"""
    t.head("LIVE READ PATH — how much of a description the detector actually sees")
    try:
        from datahub_agent_context.mcp_tools.helpers import (
            DESCRIPTION_LENGTH_HARD_LIMIT,
            sanitize_and_truncate_description,
        )
    except ImportError as exc:
        t.say(f"CANNOT RUN: {exc}")
        return False

    limit = DESCRIPTION_LENGTH_HARD_LIMIT
    t.step("description_hard_limit", chars=limit,
           source="datahub_agent_context.mcp_tools.helpers",
           applies_to="get_entities (dataset + ingested column descriptions)",
           does_not_apply_to="editableSchemaMetadata (curated column descriptions, "
                             "read via the base SDK aspect)")

    survived = []
    for i, item in enumerate(items):
        live = sanitize_and_truncate_description(item["text"], limit)
        if detect(live).flagged:
            survived.append(i)
    long_ones = [i for i, it in enumerate(items) if len(it["text"]) > limit]
    long_survivors = [i for i in survived if i in long_ones]
    t.step("false_positives_visible_through_live_read",
           measured_in_study=len(items), still_flag_live=len(survived),
           over_limit=len(long_ones), over_limit_still_flagging=len(long_survivors))
    summary["live_read_truncation"] = {
        "hard_limit_chars": limit,
        "study_flags": len(items),
        "flags_surviving_live_read": len(survived),
        "descriptions_over_limit": len(long_ones),
        "over_limit_surviving": len(long_survivors),
    }
    if limit != EXPECTED_DESC_LIMIT:
        t.say(f"  NOTE: the pinned kit's limit is {limit}, not the {EXPECTED_DESC_LIMIT} "
              "this drill was written against. The numbers above are still measured.")
    t.say(f"  {len(survived)} of the {len(items)} measured false positives still flag "
          f"once the live read path has had them.")
    t.say(f"  Of the {len(long_ones)} that are longer than {limit} characters, "
          f"{len(long_survivors)} still flag.")
    return True


def _phase_revert_dataset(t: Transcript, summary: dict, graph, counter: CallCounter,
                          urn: str, curated: str, EDP, MCPW, *, gms: str, token) -> int:
    t.head("REVERT #1 — the dataset description (aspect: editableDatasetProperties)")
    rec: dict = {}

    # 5a. The literal "one action" reading. DataHub numbers versions 0 = latest and
    #     1 = OLDEST, so "the previous version" is version 1 only when the field was
    #     written exactly twice. Do it the naive way first, on the record.
    t.say("\n  (a) the literal reading: fetch version 1 and write it back")
    counter.start()
    naive = graph.get_aspect(urn, EDP, version=1)
    naive_calls = counter.stop()
    naive_text = naive.description if naive else None
    naive_ok = naive_text == curated
    t.step("revert_naive_version_1", http_calls=len(naive_calls),
           got_chars=len(naive_text or ""),
           got_sha256=sha(naive_text)[:16] if naive_text else None,
           restores_curated_text=naive_ok)
    _report_calls(t, naive_calls)
    if naive_ok:
        t.say("      version=1 WAS the curated text — true only because this field "
              "had exactly one prior write.")
    else:
        t.say("      version=1 is NOT the curated text; it is the steward's earlier "
              "draft. A one-call revert here destroys the description as thoroughly "
              "as the cure did, and looks like it worked.")
    rec["naive_version_1_correct"] = naive_ok
    rec["naive_http_calls"] = len(naive_calls)

    # 5b. Correct procedure A: find the highest historical version, write it back.
    #     There is no version-count API on the client, so this probes upward.
    t.say("\n  (b) the version probe: walk versions until 404, then write back")
    counter.start()
    probe_v, found = 1, None
    while probe_v <= 50:
        aspect = graph.get_aspect(urn, EDP, version=probe_v)
        if aspect is None:
            break
        found = (probe_v, aspect)
        probe_v += 1
    if found is None:
        counter.stop()
        t.say("FINDING: GMS kept NO prior version of the aspect. The README's "
              "rollback claim has no mechanism behind it on this server.")
        return 1
    prev_version, prev_aspect = found
    graph.emit(MCPW(entityUrn=urn, aspect=prev_aspect))
    probe_calls = counter.stop()
    restored = _stored_description(graph, urn, EDP)
    identical = restored == curated
    t.step("revert_version_probe", previous_version=prev_version,
           http_calls=len(probe_calls),
           reads=sum(1 for c in probe_calls if c["method"] == "GET"),
           writes=sum(1 for c in probe_calls if c["method"] != "GET"),
           byte_identical=identical, restored_chars=len(restored))
    _report_calls(t, probe_calls)
    if not identical:
        t.say("FINDING: the restored text is NOT byte-identical to the curated text. "
              "Aspect version history did not round-trip.")
        return 1
    t.say(f"      restored sha256 {sha(restored)[:16]}… — byte-identical, "
          f"{len(restored)} characters back.")
    rec["version_probe"] = {"previous_version": prev_version,
                            "http_calls": len(probe_calls),
                            "reads": sum(1 for c in probe_calls if c["method"] == "GET"),
                            "writes": sum(1 for c in probe_calls if c["method"] != "GET"),
                            "byte_identical": identical}

    # 5c. Correct procedure B: the timeline API hands back the previous text in one
    #     GET, so the operator does not have to guess a version number.
    t.say("\n  (c) the timeline API: one GET for the previous text, then write back")
    graph.emit(MCPW(entityUrn=urn, aspect=EDP(description="[re-cured for step (c)]")))
    counter.start()
    prev_text = _timeline_previous_description(gms, token, urn)
    tl_calls_read = counter.stop()
    if prev_text is None:
        t.say("      the timeline API did not return a usable previous description; "
              "the version probe in (b) remains the only procedure that works.")
        rec["timeline"] = {"usable": False}
    else:
        counter.start()
        graph.emit(MCPW(entityUrn=urn, aspect=EDP(description=prev_text)))
        tl_calls_write = counter.stop()
        restored2 = _stored_description(graph, urn, EDP)
        tl_ok = restored2 == curated
        total = len(tl_calls_read) + len(tl_calls_write)
        t.step("revert_timeline_api", http_calls=total,
               reads=len(tl_calls_read), writes=len(tl_calls_write),
               byte_identical=tl_ok, restored_chars=len(restored2))
        _report_calls(t, tl_calls_read + tl_calls_write)
        rec["timeline"] = {"usable": True, "http_calls": total,
                           "byte_identical": tl_ok}
        if not tl_ok:
            t.say("      FINDING: the timeline API's copy of the description is not "
                  "byte-identical to what was stored. Do not revert from it.")
            rec["timeline"]["byte_identical"] = False

    depth = _history_depth(graph, urn, EDP)
    t.step("history_after_reverts", versions_retained=depth,
           note="every revert is itself a forward write; nothing was removed")
    rec["history_versions_after"] = depth
    summary["revert_dataset"] = rec
    return 0


def _phase_revert_column(t: Transcript, summary: dict, graph, counter: CallCounter,
                         gw, urn: str, col_curated: str, ESM, MCPW) -> int:
    """Column descriptions share ONE aspect. Test what that does to 'per field'."""
    t.head("REVERT #2 — a column description (aspect: editableSchemaMetadata)")
    t.say("  This aspect carries EVERY column's curated description, not one field.")
    t.say("  Scenario: the cure lands, a colleague improves a different column the "
          "next day,\n  then the operator reverts the cured column from history.\n")

    gw.update_description(urn, SIBLING_AFTER, field_path=SIBLING_COLUMN)
    t.step("colleague_edit_after_cure", column=SIBLING_COLUMN,
           chars=len(SIBLING_AFTER), sha256=sha(SIBLING_AFTER)[:16])

    counter.start()
    probe_v, found = 1, None
    while probe_v <= 50:
        aspect = graph.get_aspect(urn, ESM, version=probe_v)
        if aspect is None:
            break
        if _esm_column(aspect, FLAGGED_COLUMN) == col_curated:
            found = (probe_v, aspect)
        probe_v += 1
    if found is None:
        counter.stop()
        t.say("FINDING: no historical editableSchemaMetadata version carries the "
              "curated column text. The column locus has no revert path here.")
        return 1
    prev_version, prev_aspect = found
    graph.emit(MCPW(entityUrn=urn, aspect=prev_aspect))
    calls = counter.stop()

    restored_col = _stored_column(graph, urn, ESM, FLAGGED_COLUMN)
    sibling_now = _stored_column(graph, urn, ESM, SIBLING_COLUMN)
    col_ok = restored_col == col_curated
    sibling_lost = sibling_now != SIBLING_AFTER
    t.step("revert_column_version_probe", version_used=prev_version,
           http_calls=len(calls),
           reads=sum(1 for c in calls if c["method"] == "GET"),
           writes=sum(1 for c in calls if c["method"] != "GET"),
           column_byte_identical=col_ok, restored_chars=len(restored_col or ""),
           sibling_column_clobbered=sibling_lost)
    _report_calls(t, calls)
    t.say(f"      target column restored byte-identical: {col_ok} "
          f"({len(restored_col or '')} characters)")
    if sibling_lost:
        t.say(f"      sibling column `{SIBLING_COLUMN}` was rolled back too — the "
              "colleague's later edit is GONE.")
        t.say(f"        wanted: {SIBLING_AFTER[:70]}…")
        t.say(f"        got:    {(sibling_now or '')[:70]}…")
        t.say("      This is the part 'one action per field' does not describe: the "
              "unit of history is the ASPECT, and for columns the aspect is the "
              "whole schema.")
    else:
        t.say(f"      sibling column `{SIBLING_COLUMN}` survived the revert.")
    summary["revert_column"] = {
        "version_used": prev_version, "http_calls": len(calls),
        "column_byte_identical": col_ok,
        "sibling_column_clobbered": sibling_lost,
        "sibling_expected": SIBLING_AFTER, "sibling_actual": sibling_now,
    }
    return 0 if col_ok else 1


def _phase_residue(t: Transcript, summary: dict, gw, urn: str, quarantine_tag: str,
                   content_prop: str, payload_prop: str, incident_prefix: str,
                   incident_ids: list[str]) -> None:
    t.head("RESIDUE — what restoring the text does NOT undo")
    ent = gw.get_entity(urn)
    tags = list(ent.tags) if ent else []
    props = dict(ent.structured_properties) if ent else {}
    # `grep_documents` reads the search index, which trails the write. Poll, so a
    # document the cure definitely created is not reported as absent.
    incident_urns: list[str] = []
    deadline = time.time() + 60
    while True:
        found: dict[str, str] = {}
        for incident_id in incident_ids:
            try:
                for d in gw.grep_documents(incident_id):
                    if (d.title or "") == f"{incident_prefix}{incident_id}":
                        found[incident_id] = d.urn
            except Exception as exc:  # noqa: BLE001
                t.say(f"  (incident-document lookup failed for {incident_id}: {exc!r})")
        if len(found) == len(incident_ids) or time.time() > deadline:
            if len(found) < len(incident_ids):
                t.say(f"  NOTE: only {len(found)} of {len(incident_ids)} incident "
                      "documents were visible to the search index within 60s; the "
                      "rest are written but not yet greppable.")
            incident_urns = sorted(found.values())
            break
        time.sleep(3)
    t.step("residue_after_text_revert",
           still_quarantine_tagged=quarantine_tag in tags, tags=tags,
           antigen_properties=sorted(k for k in props if k.startswith("antigen.")),
           incident_documents=len(incident_urns))

    rescan = _antigen("scan")
    reflagged = urn in rescan.stdout
    t.step("scan_after_revert", entity_reflagged=reflagged,
           exit_code=rescan.returncode,
           note="`scan` skips entities already tagged injection-quarantined")
    if not reflagged:
        t.say("  The restored false positive is NOT re-flagged: the quarantine tag "
              "the cure left behind suppresses it. Convenient here, and a hole if "
              "the field were re-poisoned — which is what `rescan` exists for.")
    summary["residue"] = {
        "still_quarantine_tagged": quarantine_tag in tags,
        "tags": tags,
        "antigen_properties": sorted(k for k in props if k.startswith("antigen.")),
        "content_sha_prop_present": content_prop in props,
        "payload_sha_prop_present": payload_prop in props,
        "incident_documents": incident_urns,
        "reflagged_by_scan_after_revert": reflagged,
    }


def _phase_ui_path(t: Transcript, summary: dict, *, gms: str, token) -> None:
    """Is any of this reachable from the UI? Ask the API the UI is built on."""
    import requests

    t.head("UI PATH — what the DataHub GraphQL API offers an operator")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # Asked as two requests on purpose: GMS refuses an introspection query that
    # names `fields` more than once ("BadFaithIntrospection").
    def names(root: str) -> list[str] | None:
        try:
            resp = requests.post(f"{gms.rstrip('/')}/api/graphql", headers=headers,
                                 json={"query": f"{{__schema{{{root}{{fields{{name}}}}}}}}"},
                                 timeout=30)
            return [f["name"] for f in resp.json()["data"]["__schema"][root]["fields"]]
        except Exception:  # noqa: BLE001
            return None

    mutations = names("mutationType")
    queries = names("queryType")
    if mutations is None or queries is None:
        t.say("  GraphQL introspection unavailable; not asserting anything about "
              "the UI.")
        summary["ui_path"] = {"introspected": False}
        return
    candidates = [m for m in mutations if re.search(REVERT_MUTATION_PATTERN, m, re.I)]
    t.step("graphql_schema", mutations=len(mutations), queries=len(queries),
           revert_like_mutations=candidates,
           timeline_query_present=("getTimeline" in queries))
    t.say("  `getTimeline` is a READ. None of the mutations above puts an old "
          "aspect value back:")
    t.say("  `rollbackIngestion` rolls back an ingestion RUN by runId, not a "
          "hand edit; the two")
    t.say("  `AssetVersion` mutations link/unlink version SETS of entities, not "
          "aspect versions.")
    t.say("  An operator working in the UI has no revert control for a "
          "description. The recovery")
    t.say("  path is the SDK/API transcript above, or copy-and-paste out of the "
          "timeline view.")
    summary["ui_path"] = {"introspected": True, "mutations": len(mutations),
                          "revert_like_mutations": candidates,
                          "timeline_query_present": "getTimeline" in queries,
                          "frontend_checked": False}


def _phase_ledger(t: Transcript, summary: dict) -> None:
    ds = summary.get("revert_dataset", {})
    col = summary.get("revert_column", {})
    probe = ds.get("version_probe", {})
    tl = ds.get("timeline", {})
    t.head("ACTION COUNT — what 'one action' actually cost")
    t.say(f"  dataset description, version probe   "
          f"{probe.get('http_calls', '?')} HTTP calls "
          f"({probe.get('reads', '?')} reads to locate version "
          f"{probe.get('previous_version', '?')}, {probe.get('writes', '?')} write)")
    if tl.get("usable"):
        t.say(f"  dataset description, timeline API    {tl.get('http_calls', '?')} "
              f"HTTP calls (byte-identical: {tl.get('byte_identical')})")
    t.say(f"  naive `version=1` in one call        "
          f"{'correct' if ds.get('naive_version_1_correct') else 'WRONG TEXT'}")
    t.say(f"  column description                   "
          f"{col.get('http_calls', '?')} HTTP calls; sibling column clobbered: "
          f"{col.get('sibling_column_clobbered')}")
    res = summary.get("residue", {})
    t.say(f"  quarantine tag still set             {res.get('still_quarantine_tagged')}")
    t.say(f"  antigen.* properties still set       "
          f"{len(res.get('antigen_properties', []))}")
    t.say(f"  incident documents the cure wrote    "
          f"{len(res.get('incident_documents', []))} — the text revert removes none "
          "of them")
    ui = summary.get("ui_path", {})
    t.say(f"  revert-like GraphQL mutations        "
          f"{ui.get('revert_like_mutations', 'not introspected')}")
    t.say("")
    t.say("  Restoring the TEXT is real, and it works. 'One action' is not what this "
          "transcript shows.")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _stored_description(graph, urn: str, EDP) -> str:
    """The STORED description, straight off the aspect — not the tool's truncated view."""
    a = graph.get_aspect(urn, EDP, version=0)
    return (getattr(a, "description", "") or "") if a else ""


def _esm_column(aspect, field_path: str) -> str | None:
    for f in getattr(aspect, "editableSchemaFieldInfo", None) or []:
        if getattr(f, "fieldPath", None) == field_path:
            return getattr(f, "description", None)
    return None


def _stored_column(graph, urn: str, ESM, field_path: str) -> str | None:
    a = graph.get_aspect(urn, ESM, version=0)
    return _esm_column(a, field_path) if a else None


def _history_depth(graph, urn: str, EDP) -> int:
    n, v = 1, 1
    while v <= 50 and graph.get_aspect(urn, EDP, version=v) is not None:
        n += 1
        v += 1
    return n


def _timeline_previous_description(gms: str, token, urn: str) -> str | None:
    """The description immediately before the newest DOCUMENTATION change.

    DataHub's timeline API is the only read that hands an operator the prior text
    without guessing a version number. It is read-only: there is no companion
    endpoint that puts the value back.
    """
    import requests

    url = (f"{gms.rstrip('/')}/openapi/v2/timeline/v1/"
           f"{urllib.parse.quote(urn, safe='')}?categories=DOCUMENTATION"
           "&start=-1&end=0&raw=false")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        return None
    entity_changes = []
    for entry in resp.json() or []:
        for ev in entry.get("changeEvents", []):
            if ev.get("entityUrn") != urn:
                continue  # schemaField changes carry their own URN
            desc = (ev.get("parameters") or {}).get("description")
            if isinstance(desc, str):
                entity_changes.append(desc)
    if len(entity_changes) < 2:
        return None
    return entity_changes[-2]


def _await_absent(gw, urn: str, t: Transcript, timeout_s: int = 120) -> None:
    """Block until the hard-deleted URN has left the search index.

    Writes reach MySQL immediately and OpenSearch asynchronously. Re-seeding on
    top of a stale index entry is how the first version of this drill produced a
    `search` hit whose `get_entities` read came back empty — and an empty
    description is not flagged, so `cure` planned nothing and the drill looked
    like a detector failure when it was a race.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if urn not in gw.search_all():
            t.step("delete_propagated", note="previous drill entity gone from `search`")
            return
        time.sleep(3)
    t.step("delete_propagation_timeout",
           note="stale index entry still present; seeding anyway")


def _await_scannable(gw, urn: str, t: Transcript, detect, expected_column: str,
                     timeout_s: int = 240) -> bool:
    """Block until the read path `scan` uses agrees the entity is there and flags."""
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        if urn in gw.search_all():
            ent = gw.get_entity(urn)
            col = (ent.columns.get(expected_column).description
                   if ent and expected_column in ent.columns else "")
            if ent and detect(ent.description).flagged and detect(col or "").flagged:
                t.step("search_indexed",
                       note="drill entity readable AND flagged through the live "
                            "read path (both loci)")
                return True
            last = (f"desc={len(ent.description) if ent else 0} chars, "
                    f"{expected_column}={len(col or '')} chars")
        time.sleep(3)
    t.say(f"  last live read: {last or 'entity not in search'}")
    return False


def _antigen(*args: str) -> subprocess.CompletedProcess:
    """Run the shipped CLI exactly as the README documents it."""
    return subprocess.run(
        [sys.executable, "-m", "antigen", *args],
        cwd=str(REPO), capture_output=True, text=True,
        env={**os.environ, "PYTHONWARNINGS": "ignore"},
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

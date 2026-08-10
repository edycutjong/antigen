# Recovering from a false-positive cure — what it actually costs

**Status: the README's "one action" claim was wrong, and has been corrected.**
Recovery is real, it round-trips byte-identically, and it costs **2 API calls at
best, 4–5 in practice, plus three pieces of residue the text revert does not
touch** — and there is no way to do any of it from the DataHub UI.

Everything below was measured against a live DataHub GMS v1.7.0 by
[`scripts/revert_drill.py`](../scripts/revert_drill.py). Console transcript:
[`docs/revert-drill.log`](./revert-drill.log). Machine-readable record of the same
run, including every counted HTTP request:
[`docs/revert-drill-transcript.json`](./revert-drill-transcript.json).

---

## Why this needed evidence

`cure` is destructive by design. Off the demo corpus there is no fixture, so a
flagged field is replaced in its entirety by the quarantine banner, and Antigen
keeps **no copy** of what it removed — the incident record holds hashes only. The
[false-positive study](./false-positive-study.md) measures **24 false positives in
38,031 real catalog descriptions (0.063%)**, rising to **4.663% on descriptions of
2,000 characters or more** — exactly the long, hand-curated fields a steward spent
an afternoon on.

So the sentence *"rollback is DataHub's aspect version history (one action)"* was
the only thing standing between an operator and permanently losing that text. It
had been verified **only against `InMemoryGateway`**, the dict in this repo that
imitates GMS. This drill runs it against the real thing.

## What was done

| | |
|---|---|
| GMS | `http://localhost:8080`, DataHub **v1.7.0** quickstart, metadata-service auth disabled |
| SDK | `acryl-datahub` 1.6.0.6, `datahub-agent-context` 1.6.0.17 |
| Command | `python scripts/revert_drill.py` |
| Entity seeded | `urn:li:dataset:(urn:li:dataPlatform:socrata,antigen_revert_drill.hidot.census_block_groups_2020,PROD)` |
| Run captured | 2026-08-10T01:59:05Z → 01:59:25Z (20 s end to end) |

The drill seeds its own entity, hard-deletes it at the end, and refuses to run at
all if the `cure --dry-run` plan names any dataset it did not seed. It touches
nothing the demo arc depends on: it was run, then `./run.sh live` was re-run
(Part A **PASS**, 12/12 payloads removed, held-out 3/3), then it was run twice
more. All three runs produced identical counts. The transcript published here is
the last of them.

**The two false positives are real strings**, loaded out of
[`docs/fp-corpus-manifest.json`](./fp-corpus-manifest.json) by sha256, not
invented for the drill:

- **dataset description** — `highways.hidot.hawaii.gov` dataset `2tw7-ygpr`, 557
  characters, sha256 `cdc68278bda75023…`, rule
  `exfiltration ('email' … 'email' → 'https://files.hawaii.gov/…/blkgrp20.pdf')`.
  Class A contact-and-link boilerplate — the class that is 21 of the 24 measured
  flags.
- **column description** — `opendata.maryland.gov` dataset `3xda-h6fq`, **3,448
  characters**, sha256 `0724d11f47d9bfff…`, rule
  `exfiltration ('Email' … 'Email' → 'GIS@mdot.state.md.us')`. Also Class A, and
  in the ≥2,000-character bucket the study warns about.

The field got a realistic history: a short draft first, then the curated text.
That single detail is what breaks the "one action" reading.

`python -m antigen cure --apply --max-mutations 8` then ran the shipped path and
quarantined both loci: **557 characters and 3,448 characters of curated
documentation replaced by a 486-character banner**, exit 0.

## Finding 1 — the one-call revert restores the *wrong* text

DataHub numbers versioned aspects with **0 = latest and 1 = oldest**
(`DataHubGraph.get_aspect`: *"Versions > 0 go from oldest to newest, so 1 is the
oldest"*). "Fetch the previous version" is therefore version 1 **only when the
field has been written exactly twice**.

On a field with a draft behind it, version 1 was the draft:

```
revert_naive_version_1   http_calls=1  got_chars=98  restores_curated_text=False
```

98 characters of superseded draft, restored over the top of the incident, with a
200 OK and no warning. That is a *worse* outcome than the cure: the operator
believes the description is back.

## Finding 2 — the cheapest correct revert is 2 calls; the obvious one is 4

Two procedures were run and both restored the 557 characters **byte-identically**
(sha256 `cdc68278bda75023…`):

| Procedure | HTTP calls | Detail |
|---|---:|---|
| Version probe — walk `?aspect=editableDatasetProperties&version=N` until 404, re-emit the highest | **4** | 3 GETs (200, 200, 404) to discover that the previous version is **2**, then 1 `POST /aspects?action=ingestProposal` |
| Timeline API — `GET /openapi/v2/timeline/v1/{urn}?categories=DOCUMENTATION`, take the second-newest description, write it back | **2** | 1 GET, 1 POST |

The version probe costs *N+1* reads on a field with *N* prior versions, because
neither the SDK nor the REST surface exposes a version count — you discover the
number by hitting a 404. The timeline route avoids the guess, but it is a
different API from the one that writes, it returns *change events* rather than
aspect values, and the operator still has to identify which event was the cure.

Neither is one action. The floor is **two**: one read to find the text, one write
to put it back.

## Finding 3 — the revert is itself a forward write

After the reverts, the aspect had **6 retained versions**. Nothing was removed;
the banner is still in history, and so is the restore. This matches the README's
"forward-only" framing and is worth stating explicitly: there is no operation
here that *undoes* anything, only operations that append.

## Finding 4 — for columns it is not "per field" at all

Column descriptions live in **one aspect for the whole schema**
(`editableSchemaMetadata`). Restoring a previous version of it restores **every**
column.

The drill ran the realistic sequence — cure lands, a colleague improves a
different column afterwards, operator reverts the cured column:

```
revert_column_version_probe  http_calls=5  column_byte_identical=True
                             restored_chars=3448  sibling_column_clobbered=True
   wanted: Feature identifier assigned by the source GIS. Stable across annual re…
   got:    Feature identifier assigned by the source GIS.
```

The 3,448-character column description came back exactly. The colleague's later
edit to `objectid` was silently rolled back with it. **"One action per field" is
not a description of this mechanism** — the unit of history is the aspect, and for
columns the aspect is the entire schema. Restoring a column safely means reading
the old version, taking only the one field out of it, and merging that into the
*current* aspect. The drill did not do that; it did the naive thing on purpose, to
show what the naive thing costs.

## Finding 5 — the text revert leaves three kinds of residue

Restoring the description does not undo the rest of the cure:

| Residue after the text was restored | State |
|---|---|
| `injection-quarantined` tag | still set |
| `antigen.contentSha256`, `antigen.payloadSha256`, `antigen.lastScanned` | all still set, now describing text that is no longer there |
| Incident KB documents | 2 written by this cure, 0 removed by the revert |

And a consequence worth naming: a re-run of `scan` **did not re-flag** the
restored false positive (`entity_reflagged=False`), because `scan` skips entities
already tagged `injection-quarantined`. Convenient here — the operator does not
fight the scanner every night — but it means the quarantine tag, not the text, is
what suppresses the finding. `rescan` exists for exactly this asymmetry.

A *complete* revert is therefore: restore the text (2–5 calls), remove the tag,
clear three structured properties, and decide what to do with the incident
document. Antigen automates none of it.

## Finding 6 — there is no UI path

Live GraphQL introspection against the same GMS: **169 mutations, 106 queries**.
The only revert-shaped mutation names are `rollbackIngestion` (rolls back an
ingestion *run* by `runId` — not a hand edit), `linkAssetVersion` and
`unlinkAssetVersion` (version *sets* of entities, not aspect versions).
`getTimeline` exists and is a **read**.

Scope this honestly: the drill checked the API the DataHub frontend is built on,
not the frontend itself — the quickstart here runs GMS only, with no
`datahub-frontend` container. What can be said is that **no mutation exists that
would put an old aspect value back**, so a UI control for it would have nothing to
call. An operator in the browser can at best read the old text out of a timeline
view and paste it into the description editor.

## Side finding — the live read path only shows the detector the first 1,000 characters

This one was not the goal of the drill; it fell out of trying to plant the
3,448-character false positive at the dataset locus and watching `cure` plan
nothing.

`datahub_agent_context.mcp_tools.helpers.DESCRIPTION_LENGTH_HARD_LIMIT = 1000`.
Every `description` in a `get_entities` response is HTML-sanitised and truncated
to 1,000 characters. That is the *only* way Antigen reads dataset descriptions, so
**the detector never sees past character ~997 of any dataset description on a live
GMS.**

Measured over the study's own 24 flagged strings, run through the pinned kit's own
`sanitize_and_truncate_description`:

| | |
|---|---:|
| False positives measured in the study (raw strings) | 24 |
| Still flagging after the live read path | **10** |
| Of those 24, longer than 1,000 characters | 14 |
| …of which still flag | **0** |

Two consequences, and they point in opposite directions:

1. **The study's headline length-conditional rate does not transfer to the live
   path.** "4.663% above 2,000 characters" is a property of the detector on raw
   text. Through `get_entities`, every one of those long flags disappears. The
   review burden on long dataset descriptions is lower than the study implies.
2. **That is a recall hole, not a feature.** The `search` tool returns the same
   description **untruncated** — verified live: a seeded 3,448-character
   description came back whole from `search` and 1,000 characters from
   `get_entities`. So a payload placed after character 1,000 of a dataset
   description reaches an agent that calls `search`, and is invisible to Antigen's
   sweep. Column descriptions curated through `update_description` are read from
   `editableSchemaMetadata` via the base SDK (`SdkGateway._merge_editable_columns`)
   and are **not** truncated, which is why the 3,448-character string could be used
   at the column locus at all.

This is a real gap in Antigen and it is not fixed here — the code is frozen for
this evidence pass. The fix is to read dataset descriptions from the
`datasetProperties` / `editableDatasetProperties` aspects rather than relying on
`get_entities` for the text, which is the same technique `_merge_editable_columns`
already uses for columns.

## What this establishes — and what it does not

**Establishes.** Against a real DataHub GMS v1.7.0: aspect version history does
retain the pre-cure text; a revert restores it byte-identically at both the
dataset and column locus; the cheapest correct revert is 2 API calls and the
obvious one is 4; version 1 is the oldest and the naive one-call revert restores
the wrong text; the column-level aspect is schema-wide and a revert clobbers
sibling columns edited after the cure; the tag, the structured properties and the
incident document all survive the revert; and no GraphQL mutation exists that
would back a UI revert control.

**Does not establish.** That the DataHub *UI* has no revert (the frontend was not
running — only the API it is built on was inspected). That version history is
retained under a non-default retention policy — this quickstart keeps all
versions, and a GMS configured with aspect-version retention could have discarded
the pre-cure value entirely, which would make recovery impossible rather than
merely multi-step. That the column locus is a realistic *placement*: the study
found **0 flags in 30,556 column descriptions**, so putting a real dataset-level
false positive into a column description is a constructed placement, chosen to
reach the untruncated read path. That any of this holds with metadata-service auth
enabled, or on a managed DataHub Cloud instance.

## Reproduce it

```bash
export DATAHUB_GMS_URL=http://localhost:8080
pip install -r requirements.txt          # live extras
python scripts/revert_drill.py           # ~15s; seeds, cures, reverts, cleans up
```

Exit 0 means every assertion about DataHub's behaviour held. Exit 1 is a finding —
read the output. Exit 2 means it could not run (no GMS, no SDK, or the catalog is
not in a fit state; the drill refuses to write against entities it did not seed).
`--keep` leaves the entity in place for inspection.

## The corrected claim

Before:

> **Rollback is DataHub's aspect version history**, one action per field.

After — the wording now in `README.md`:

> **Rollback is DataHub's aspect version history — two API calls at best, not one
> action, and not per field.** […] Measured end to end against a live GMS in
> [`docs/false-positive-revert.md`](docs/false-positive-revert.md).

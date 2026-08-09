# DEMO — reproduce every number in the pitch

Two paths. The **offline** path reproduces the graph-state proof, the detection numbers,
and the benchmark on any laptop with Python 3.10+ (no Docker, no keys). The **live** path
reproduces the full hijack → cure → 0/12 arc against a real DataHub GMS.
Every number below was observed on a real run; none is aspirational.

## Offline (seconds — well under 30 — zero dependencies)

```bash
./run.sh
```

Reproduces:

| Claim | Command | Expected |
|-------|---------|----------|
| Graph-state gate passes | `python verify.py` | `graph-state PASS (~5 ms) \| held-out 3/3` |
| 12/12 payloads detected | `python tests/test_detect.py` | `test_all_12_payloads_flagged PASS` |
| 3/3 held-out (never tuned on) | `python tests/test_detect.py` | `test_all_3_held_out_detected PASS` |
| 0 false positives (15 near-miss) | `python seed_near_miss.py` | `15/15 clean \| 0 false positives` |
| NFKC alone would miss zero-width | `python tests/test_detect.py` | `test_nfkc_alone_would_miss_zero_width PASS` |
| Payload + base64/hex absent post-cure | `python tests/test_cure.py` | `test_cure_neutralizes_every_readable_surface PASS` |
| Idempotent (`scan && cure` twice = no-op) | `python tests/test_cure.py` | `test_idempotent_second_run_is_noop PASS` |
| Tamper-evidence catches drift | `python tests/test_cure.py` | `test_rescan_detects_drift PASS` |
| Latency p50/p95/p99 | `python bench.py --runs 20` | scan+cure p50 ≈ 2 ms (offline) |
| The full hero arc | `python -m antigen demo --offline` | sweep → defuse → 0 remaining |

## Live (against a real DataHub GMS)

Verified end-to-end on `datahub docker quickstart` **v1.7.0** with
`acryl-datahub 1.6.0.6` / `datahub-agent-context 1.6.0.17`.

```bash
pip install -r requirements.txt

# 1. start a DataHub GMS (first run pulls ~9 GB of images; allow 10-15 min)
datahub docker quickstart

# quickstart runs with metadata-service auth DISABLED, so no PAT is needed.
export DATAHUB_GMS_URL=http://localhost:8080 DATAHUB_GMS_TOKEN=

# Verified BOTH ways. If your GMS has METADATA_SERVICE_AUTH_ENABLED=true, mint a
# Personal Access Token (UI -> Settings -> Access Tokens) and export it instead:
#   export DATAHUB_GMS_TOKEN=eyJhbGciOi...
# Antigen passes it through to every one of the 9 tools and to the base-SDK
# aspect reads; nothing else changes.
export TOOLS_IS_MUTATION_ENABLED=true SAVE_DOCUMENT_TOOL_ENABLED=true \
       SAVE_DOCUMENT_RESTRICT_UPDATES=false

# 2. build the clean ecommerce catalog the corpus targets, and wait for the
#    search index to catch up (DataHub indexes asynchronously)
python seed_catalog.py

# 3. one-time structured-property definitions (required before any cure:
#    add_structured_properties rejects a property that has no definition)
python -m antigen.register_properties

# 4. plant the corpus (the attacker step; labeled demo input)
python seed_corpus.py

# 5. the hero arc: sweep -> defuse -> blast radius -> certify -> prove standing
python -m antigen demo

# 6. the reproducible proof (re-runs its own scan+cure, so start from step 2
#    on a freshly reset instance)
python verify.py --live

# 7. inspect in the DataHub UI at http://localhost:9002  (login datahub/datahub)
#    - a poisoned entity's description, then the cleaned one (span gone) + quarantine tag
#    - the antigen-incident-* forensic doc (hashes + repo pointer, no payload)
#    - injection-blast-radius-* tags on downstream assets
```

Reset between runs: `datahub docker nuke`, then repeat from step 1. A cured entity
keeps its `injection-quarantined` tag and the sweep deliberately skips tagged
entities, so re-planting without a reset finds nothing.

Observed on a clean run:

| Step | Output |
|------|--------|
| `seed_catalog.py` | `13 datasets created` + 6 lineage edges |
| `seed_corpus.py` | `planted 12 payloads + 3 held-out injections` |
| `antigen demo` sweep | `17 entities + 2 documents \| 15 injection loci flagged \| 2 hidden in zero-width Unicode \| 13 via get_entities \| 2 via grep_documents` |
| `antigen demo` defuse | `cured 12 loci (12 excised, 0 field-quarantined)` |
| `antigen demo` blast radius | `10 downstream assets across 10 quarantined entities` |
| `verify.py --live` | `Part A — graph-state gate: PASS (7055 ms)` · `held-out 3/3` |

## Demo video

**https://youtu.be/rQas3GDPpfA** — 2:25. Shows the real DataHub UI before and after (poisoned description →
cleaned span + quarantine tag + sha256 stamps), the live sweep finding 15/15 loci, the
cure writing back through the 9 tools, the blast-radius tag on a downstream asset, and
`verify.py --live` reaching the graph-state PASS.

Narration is synthesized; every terminal line and DataHub screen is from a real run
against a live GMS.

## Measured hijack A/B

The victim is a **stock** LangChain catalog agent — `build_langchain_tools(client)`
with mutations OFF — so any hijack is a property of trusting stock tool output, not of
anything Antigen wrote. Both numbers are read from real model output, never hard-coded:

| Model | Before the cure | After the cure (cold re-run) |
|-------|-----------------|------------------------------|
| `claude-sonnet-5` | **2 / 12** | **0 / 12** |

Read this honestly: a frontier model already refuses most of these payloads unaided, so
the pre-cure rate is low. That is *why* the pass/fail gate is Part A's graph-state proof
rather than the hijack rate — Antigen removes the injected span from the graph, so the
outcome does not depend on which model happens to read it, or on how gullible it is.
A weaker or older model would be hijacked more often; the post-cure result is 0 either
way, because there is no payload left to obey.

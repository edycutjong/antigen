# DEMO — reproduce every number in the pitch

Two paths. The **offline** path reproduces the graph-state proof, the detection numbers,
and the benchmark on any laptop with Python 3.10+ (no Docker, no keys). The **live** path
reproduces the full hijack → cure → 0/12 arc against a real DataHub GMS.

## Offline (≈ 10 seconds, zero dependencies)

```bash
./run.sh
```

Reproduces:

| Claim | Command | Expected |
|-------|---------|----------|
| Graph-state gate passes | `python verify.py` | `graph-state PASS (~4 ms) \| held-out 3/3` |
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

```bash
# start DataHub + load the 1,049-entity Apache-2.0 sample datapack
datahub docker quickstart
datahub datapack load showcase-ecommerce

# enable mutation + document tools (self-hosted mcp-server-datahub env)
export TOOLS_IS_MUTATION_ENABLED=true SAVE_DOCUMENT_TOOL_ENABLED=true \
       SAVE_DOCUMENT_RESTRICT_UPDATES=false
export DATAHUB_GMS_URL=http://localhost:8080 DATAHUB_GMS_TOKEN=<PAT>

pip install -r requirements.txt
python antigen/register_properties.py     # one-time structured-property definitions

# 1. plant the corpus (the attacker step; labeled demo input)
python seed_corpus.py

# 2. watch the stock agent get hijacked, then cure, then re-run cold
python verify.py --live                    # Part A gate + Part B hijack <pre>/12 -> 0/12

# 3. inspect in the DataHub UI at http://localhost:9002
#    - a poisoned entity's description, then the cleaned one (span gone) + quarantine tag
#    - the Antigen/Incidents forensic doc (hashes + repo pointer, no payload)
#    - injection-blast-radius tags on downstream dashboards
```

Reset between runs: `datahub datapack load showcase-ecommerce --force`.

## Demo video

A < 3-minute walkthrough (hijack → sweep → defuse → cold re-run → `verify.py`) is linked on
the Devpost submission page. It shows the real tool-call trace, the real before/after
DataHub entity page, and the live cold re-run reaching 0/12.

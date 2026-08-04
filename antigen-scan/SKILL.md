---
name: antigen-scan
description: >-
  Sweep a DataHub catalog for prompt-injection payloads (OWASP LLM01) hidden in
  entity/column descriptions and KB documents — including zero-width-Unicode-hidden
  ones — and defuse each in the graph with human approval. Use when a user asks to
  "scan the catalog for prompt injection", "check descriptions for jailbreaks",
  "audit metadata for injected instructions", or "quarantine poisoned entities".
license: Apache-2.0
---

# antigen-scan

This Skill drives the **deterministic Antigen engine** (`antigen` CLI). It does **not**
ask the model to detect injections itself — detection is a stdlib scored rule so results
are reproducible and auditable. The model orchestrates and gates human approval.

## Prerequisites

- A reachable DataHub instance with `DATAHUB_GMS_URL` + `DATAHUB_GMS_TOKEN` set, and the
  self-hosted `mcp-server-datahub` env flags `TOOLS_IS_MUTATION_ENABLED=true`,
  `SAVE_DOCUMENT_TOOL_ENABLED=true`, `SAVE_DOCUMENT_RESTRICT_UPDATES=false`.
- `pip install -r requirements.txt` and a one-time `python antigen/register_properties.py`.

## Workflow

1. **Sweep (read-only, safe).** Run:
   ```
   python -m antigen scan --json
   ```
   Summarize for the user: how many entities/documents were scanned, how many injection
   loci were flagged, how many were hidden in zero-width Unicode, and which tool surfaced
   each (`get_entities` vs `grep_documents`). Do NOT mutate anything yet.

2. **Show the plan and ASK FOR APPROVAL.** For each flagged locus, present the URN, the
   detected signals (e.g. `instruction-override`, `data-exfiltration`), and the fact that
   the cure will *remove* the injected span, quarantine-tag the entity, stamp tamper-
   evidence hashes, and file a forensic incident. Wait for explicit user confirmation.

3. **Defuse (mutating).** Only after approval:
   ```
   python -m antigen cure
   ```
   Then map downstream reach and re-verify:
   ```
   python -m antigen blast-radius
   python -m antigen scan --fail-on-hit   # should report 0 remaining
   ```

4. **Stand up the loop (optional).** Recommend adding `python -m antigen scan --fail-on-hit`
   to the metadata-CI job so new injections fail the build before an agent reads them, and
   `python -m antigen rescan` to catch post-certification drift.

## Guardrails

- Never fabricate or override detection results — always report exactly what `antigen scan`
  returns.
- Treat `cure` as destructive-with-approval: it removes text and writes back. Never run it
  without step 2's confirmation.
- The raw payloads are written only to the repo `examples/` folder, never back to the
  graph; the graph holds only irreversible hashes. Do not print recovered payloads into
  chat beyond what `antigen scan` already surfaces.

# Remediation Plan — approval required

**Source:** `python -m antigen cure --dry-run` · **Nothing has been written.**

## Scope

|                                      |                     |
| ------------------------------------ | ------------------- |
| Loci to remediate                    | <n>                 |
| Surgical (`excise`)                  | <n>                 |
| **Whole-field (`quarantine-field`)** | **<n>**             |
| Mutations that will be issued        | <n × 4>             |
| Target catalog                       | `<DATAHUB_GMS_URL>` |

## Planned mutations

| #   | URN                 | Field          | Tool                        | Mode   | Before → After                                                          |
| --- | ------------------- | -------------- | --------------------------- | ------ | ----------------------------------------------------------------------- |
| 1   | `<urn>`             | `<field_path>` | `update_description`        | excise | injected span deleted; rest of the description preserved                |
| 2   | `<urn>`             | —              | `add_tags`                  | —      | `injection-quarantined`                                                 |
| 3   | `<urn>`             | —              | `add_structured_properties` | —      | `antigen.contentSha256`, `antigen.payloadSha256`, `antigen.lastScanned` |
| 4   | `Antigen/Incidents` | —              | `save_document`             | —      | forensic record, hashes only                                            |

## What you are approving — read before answering

- **<n> descriptions will be replaced in full.** For every `quarantine-field` locus the
  entire description is replaced by an inert banner. Antigen does not keep a copy. The
  prior text is recoverable from DataHub's aspect version history and from nothing
  Antigen writes — but **recovery is not one action, and it is not free**. Verified
  against a live GMS: DataHub numbers aspect versions `0 = latest, 1 = oldest`, so
  reading `version=1` restores the *wrong* text at `200 OK` with no warning. The floor
  is two calls (find the prior text, write it back), four if you probe for the right
  version. A **column** revert rewrites `editableSchemaMetadata`, which holds every
  column, so it silently clobbers any later edit a colleague made to a *different*
  column. The revert is itself a forward write, the quarantine tag and `antigen.*`
  properties survive it, a later `scan` will not re-flag the restored field, and there
  is no UI path. See `docs/false-positive-revert.md` in the Antigen repo.
- **<n> descriptions will be edited surgically.** For `excise` loci the injected span is
  deleted and the legitimate documentation survives.
- **Nothing recoverable is written to the graph.** The forensic record holds hashes only.
- **Quarantined entities are skipped by future sweeps**, which is what makes re-running
  safe — and also why re-planting test payloads without a catalog reset finds nothing.

## Options

| To...                                                                  | Run                                                 |
| ---------------------------------------------------------------------- | --------------------------------------------------- |
| Apply everything above                                                 | `python -m antigen cure --apply`                    |
| Apply only the surgical half, hold whole-field quarantines for a human | `python -m antigen cure --apply --only-mode excise` |
| Change nothing                                                         | do nothing — this was a preview                     |

**Approve these <n> mutations against the live catalog?**

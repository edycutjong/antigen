# Deploying Antigen — least privilege and environment

> Extracted from [`README.md`](../README.md) so the main page stays readable. This is the
> operator's page: the DataHub Policy to grant a dedicated service account, and the one
> environment variable the KB-document cure needs — including where **not** to set it.
> The adopter-facing quickstart stays in the README under
> [Running Antigen on your own catalog](../README.md#running-antigen-on-your-own-catalog).

---

## Least privilege — the DataHub Policy for a dedicated `antigen-svc` account

Antigen's threat model names the privileges an **attacker** needs (*Who can actually write
catalog free text*). The same privilege list, inverted, is what an operator should grant
Antigen — and no more. Do not run it as a superuser or as a human's PAT.

Create **two** service accounts, because the read path and the write path have genuinely
different blast radii, and only one of them ever needs to be automated:

| Account | Used by | Metadata Policy privileges | Resources |
|---|---|---|---|
| `antigen-scanner` | `scan`, `rescan`, the scheduled CI job | **`VIEW_ENTITY_PAGE`** only (read is otherwise ungated on OSS DataHub) | all, or the domains you sweep |
| `antigen-remediator` | `cure`, `certify`, `blast-radius` — human-triggered | **`EDIT_ENTITY_DOCS`** (entity descriptions) · **`EDIT_DATASET_COL_DESCRIPTION`** (column descriptions) · **`EDIT_ENTITY_TAGS`** (`injection-quarantined`, `agent-safe-certified`) · **`EDIT_ENTITY_PROPERTIES`** (the three `antigen.*` structured properties) | scope to the domains you actually remediate |

Notes that matter more than the table:

- **The scanner account is the one you automate**, and it should hold **no `EDIT_*`
  privilege at all**. `scan` writes nothing by construction; a read-only credential makes
  that a property of the deployment rather than a property of our code.
- **Do not use the default "Asset Owners - Metadata Policy" path.** That policy grants
  `EDIT_ENTITY_DOCS` and `EDIT_DATASET_COL_DESCRIPTION` to `resourceOwners` — it is
  exactly the grant the attack in *Who can actually write catalog free text* rides on.
  Give `antigen-remediator` an explicit, scoped policy instead of making it an owner.
- **The structured-property *definitions* are a separate, one-time step.**
  `python -m antigen.register_properties` creates them and needs
  `MANAGE_STRUCTURED_PROPERTIES`. Run it once, by a human, then take that privilege away —
  `add_structured_properties` only sets values.
- **Calibration:** these are the privileges the four mutations map to in DataHub's
  privilege list. We have run Antigen against a quickstart GMS with metadata-service auth
  disabled; we have **not** re-run the full arc under each scoped policy, so treat the
  table as the intended grant to verify in your own environment, not as a tested matrix.

## ⚠ `SAVE_DOCUMENT_RESTRICT_UPDATES=false` — set it on the Antigen job, never on a shared MCP server

The KB-document cure overwrites a poisoned document in place, which needs
`SAVE_DOCUMENT_RESTRICT_UPDATES=false`. **Where that variable has to be set is the part
worth getting right, and earlier versions of this README got it wrong** — so here is what
the pinned wheel actually does. Unzip `datahub_agent_context-1.6.0.17` and grep it:

- `SAVE_DOCUMENT_RESTRICT_UPDATES` is read at
  `datahub_agent_context/mcp_tools/save_document.py` via `os.environ.get(…, "true")`.
  It is read **in whatever process imports the Kit** — on Antigen's path, the Antigen
  Python process itself. It is not consulted over the wire and Antigen contacts no MCP
  server (`gateway.py` builds the tools in-process from `DataHubClient.from_env()`).
- `TOOLS_IS_MUTATION_ENABLED` and `SAVE_DOCUMENT_TOOL_ENABLED` are **never read** by that
  package. Both appear exactly once, in the module docstring of `save_document.py`, and
  nowhere else. Mutation tools — `save_document` included — are selected by the Python
  keyword argument `build_langchain_tools(client, include_mutations=True)`
  (`langchain_tools/builder.py`), which [`antigen/gateway.py`](../antigen/gateway.py) already
  passes. **Setting or unsetting those two variables changes nothing on Antigen's path**,
  and no earlier reproduction step depended on them working.

**Why this is still a warning and not a shrug.** In-process scoping is the *better* case:
`SAVE_DOCUMENT_RESTRICT_UPDATES=false` in the remediation job's environment lifts the
restriction for that job and for nothing else, which is a genuinely small blast radius. The
hazard is the deployment that looks equivalent and is not — **`mcp-server-datahub` runs
this same code in its own process**, so the same variable exported into a shared MCP
server's environment lifts the update restriction for *every* client of that server, giving
all of them the ability to overwrite arbitrary KB documents. That is a strictly larger hole
than the one Antigen is closing.

```bash
# in the ANTIGEN REMEDIATION JOB's environment — not in a shared mcp-server-datahub's
export SAVE_DOCUMENT_RESTRICT_UPDATES=false
```

The scheduled read-only sweep needs it off — `scan` writes nothing and never calls
`save_document`. If you also run a shared `mcp-server-datahub` for analysts, leave the
variable unset there.

<sub>Least-privilege applies unchanged either way: the env var governs one tool's update
rule, the DataHub **Policy** above governs what the credential may touch, and the Policy is
the control that matters. Verify the wheel claims yourself:
`pip download datahub-agent-context==1.6.0.17 && unzip -p …whl 'datahub_agent_context/mcp_tools/save_document.py' | grep -n environ`.</sub>

# Threat model — prior art, evidence, and why DataHub's own tooling doesn't close it

> Extracted from [`README.md`](../README.md) so the main page stays readable. **Nothing here
> was trimmed** — this is the full argument, and every citation in it was checked against the
> source. Read it if you are asking "isn't this just a Metadata Test with a regex?", "who
> could actually write this text?", or "what does the literature already do?".

**Contents:** [Prior art, and the gap it leaves](#prior-art-and-the-gap-it-leaves) ·
[The threat, grounded in evidence](#the-threat-grounded-in-evidence) ·
[DataHub's own automation is the amplifier](#datahubs-own-automation-is-the-amplifier) ·
[Who can actually write catalog free text](#who-can-actually-write-catalog-free-text) ·
[Why DataHub's own tooling doesn't close it](#why-datahubs-own-tooling-doesnt-close-it)

---

## Prior art, and the gap it leaves

**Antigen implements a published control; it does not invent one.** Saying so up front is
the honest framing — the new part is the surface it is applied to, not the technique.

- The **[OWASP RAG Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/RAG_Security_Cheat_Sheet.html)**
  already prescribes both halves of what Antigen does: *"Scan ingested documents for known
  adversarial patterns (prompt injection markers, hidden instructions, invisible Unicode
  characters, zero-width spaces)"* and *"Hash every document at ingestion time (SHA-256
  minimum) and store the hash alongside the document metadata."* The detector and
  `antigen.contentSha256` are that recommendation, executed against a metadata graph.
- **MITRE ATT&CK [T1027.018 — Invisible Unicode](https://attack.mitre.org/techniques/T1027/018/)**
  (created 2026-04-22) catalogues the zero-width evasion class, and shipped tools already
  detect it: LLM Guard's
  [`InvisibleText`](https://github.com/protectai/llm-guard/blob/main/llm_guard/input_scanners/invisible_text.py)
  scanner, NVIDIA [garak](https://github.com/NVIDIA/garak)'s `encoding` and `badchars`
  probes. Our `Cf`-strip pre-pass is table stakes, not a discovery.
- **Excising the injected span beats blocking the message** is the current research
  direction, not our idea, and it is older than the tools we first cited.
  **[Can Indirect Prompt Injection Attacks Be Detected and Removed?](https://arxiv.org/abs/2502.16580)**
  (arXiv 2502.16580, 2025-02-23, **ACL 2025 Main**) already benchmarks removal directly:
  *"the segmentation removal method, which segments the injected document and removes
  parts containing injected instructions,"* and *"the extraction removal method, which
  trains an extraction model to identify and remove injected instructions."* That is span
  excision as a published, benchmarked technique — and it predates
  [CommandSans](https://arxiv.org/abs/2510.08829) (arXiv 2510.08829, 2025-10-09), which
  surgically removes instructions from tool output at token level, by about seven months.
  [PromptArmor](https://arxiv.org/abs/2507.15219) (arXiv 2507.15219) detects and strips
  them from input. All three operate on the *copy in flight*. Antigen moves that operation
  out of the request path and into the **store of record** — clean for every future reader,
  not for one call.
- **The closest paper to Antigen stops one step short of it, and says so in its own
  abstract.** [Needle-in-RAG](https://arxiv.org/abs/2605.01782) (arXiv 2605.01782,
  2026-05-03) does *"black-box character-level poison traceback in RAG,"* localizing *"the
  responsible retrieved span for a concrete misgeneration event"* — precisely because
  *"Existing defenses and traceback methods are largely passage-level, which is too coarse
  for modern attacks whose effective payload may be a short fabricated claim, trigger
  phrase, or hidden instruction embedded inside an otherwise benign chunk."* Character-level
  localization of a poisoned span in a retrieval corpus: the hard half of what `cure` needs.
  Its stated destination is *"moving RAG forensics from document-level suspicion toward
  finer-grained evidence auditing and **potential remediation**"* — the emphasis is ours.
  It presents no remediation mechanism; remediation is named as what the approach enables,
  not as something it does. (Calibration: we are not claiming the paper defers remediation
  to a future-work section — we read the abstract, and the abstract stops at forensics.)
  **The literature localizes the span and sanitizes the copy. Nobody repairs the source of
  record.** That gap, not the detection rule, is what Antigen is.
- **Attacker-authored text inside a tool surface is an execution path** was settled by
  Invariant Labs' [MCP tool-poisoning disclosure](https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks)
  (2025-04-01) and quantified by [MCPTox](https://arxiv.org/abs/2508.14925).
- **Even the immune-system metaphor is taken.**
  [AgentAntibody](https://arxiv.org/abs/2608.04053) (arXiv 2608.04053, published
  2026-08-04 — six days before this hackathon's deadline) is literally *"An Adaptive
  Immune System for Defending LLM Agents against Prompt Injection."* The mechanism is
  the opposite pole of ours: it builds adaptive immunity *inside the agent at runtime* —
  a persistent antibody library that strengthens with each encounter — where Antigen
  sterilizes the environment, so agents that have never heard of it are safe too.
- **Pin-and-diff is prior art at the MCP layer.** Trail of Bits'
  [`mcp-context-protector`](https://blog.trailofbits.com/2025/07/28/we-built-the-security-layer-mcp-always-needed/)
  (2025-07-28) trust-on-first-use-pins a server's tool definitions and blocks on drift;
  [ETDI](https://arxiv.org/abs/2506.01333) (arXiv 2506.01333) signs and versions them.
  Both are direct antecedents of `antigen.contentSha256` + `rescan`. The difference is
  what gets pinned and where: they pin *tool definitions* in a proxy in front of one
  host; Antigen pins *catalog content* in the store of record, so drift is detectable
  by every consumer, not one proxy.
- **In-place redaction write-back is a decade-old DLP pattern.**
  [Nightfall](https://help.nightfall.ai/nightfall-ai/nightfall-for-slack/nightfall-for-slack-faqs/can-i-redact-sensitive-message-content-in-slack)
  edits a flagged Slack message in place with its redacted form;
  [Google Cloud Sensitive Data Protection](https://docs.cloud.google.com/sensitive-data-protection/docs/concepts-actions)
  runs scan → de-identify → write the de-identified copy back. Content Disarm &
  Reconstruction is the same idea for files: strip the payload, rebuild the clean,
  usable artifact. The novelty in Antigen is the payload class (instructions aimed at
  an LLM, not PII) and the surface (a metadata graph), not the pattern.

**The reframe: OWASP wrote the control; nobody built it for a data catalog.** MCP *tool
descriptions* got a scanner in about ten days — Invariant's post is dated 2025-04-01 and
its own *"Update Apr 11"* announces `mcp-scan`. The data catalog is a system whose entire
purpose is injecting human-written descriptions into an agent's query context, and whose
free text any asset owner or ingestion connector can rewrite. It got nothing.

## The threat, grounded in evidence

- **[OWASP LLM01:2026](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/)**
  (published 2026-08-04) now names *"a database row"* among indirect-injection delivery
  surfaces, and classes databases as a **trusted** surface: *"The developer's own
  repositories, databases, internal documents, and mail. The developer may not realize an
  attacker has placed content here, perhaps via an unrelated upstream vector."* That is the
  Antigen threat model in OWASP's own words. Now search the 122-page PDF: `metadata`
  appears **once** (about PDF metadata, under LLM02), and `column description`, `glossary`
  and `data catalog` appear **zero** times. The standard names the surface and stops at the
  table boundary — genuine whitespace, not a crowded field.
- **[Data Agents Under Attack](https://arxiv.org/abs/2606.08661)** (arXiv 2606.08661,
  2026-06-07) measures it. Technique **T4.1 Direct Analytical Field Poisoning** embeds
  instructions in *"schema comments, description fields, or analyst notes"* and scores
  **~24% ASR against Databricks Genie** and **~8% against BigQuery Conversational
  Analytics** — shipped products, unmodified.
- **The inversion that makes a catalog the worst case.** That same paper explains why T4.1
  *fails* when it fails: *"T4.1 often fails because poisoned facts are placed in passive
  metadata fields that agents do not reliably retrieve during ordinary analysis."* On a
  catalog MCP server that objection is void — **retrieving those fields is the server's
  entire job.** `get_entities` returns description and column text on every call;
  `grep_documents` exists to fetch KB prose. The mitigating factor behind the measured
  24% / 8% is precisely what a metadata catalog removes.
- **The same bug has already shipped elsewhere.**
  [CVE-2026-24764](https://nvd.nist.gov/vuln/detail/CVE-2026-24764) — a Slack channel's
  topic/description flowed into an assistant's **system** prompt, filed as remote code
  execution via system-prompt injection (fixed in OpenClaw 2026.2.3).
- **DataHub upstream has already conceded this sink.**
  [GHSA-8v62-ch9g-mvw9](https://github.com/datahub-project/datahub/security/advisories/GHSA-8v62-ch9g-mvw9)
  (2025-05-29) — stored XSS through the V1 UI *sidebar description*. Note the advisory's
  own detail: it was *"only exploitable through direct API calls, as the UI was already
  sanitizing inputs"*. The write path that matters is the one that never touches the UI.
- **Calibration:** there are **no publicly confirmed in-the-wild cases** of an attack via
  catalog metadata. The ASRs above are lab measurements against real products and the CVEs
  are adjacent surfaces. The claim is a demonstrated, standards-recognised exposure — not
  an active campaign.

## DataHub's own automation is the amplifier

Blast radius is usually told as impact analysis, and impact analysis earns nothing here —
lineage walks are table stakes in DataHub, Unity Catalog, Atlan and OpenMetadata alike.
The sharper fact is about DataHub's product itself:
[Documentation Propagation](https://docs.datahub.com/docs/automations/docs-propagation) —
*"This feature is enabled by default in Open Source DataHub"* — automatically propagates
column documentation *"to downstream columns and sibling columns that are derived or
dependent on the source column"*, over the same column-level lineage.

Chain that with ingestion path 2 below and the attack costs exactly one write: a
contractor runs `COMMENT ON COLUMN`, the Snowflake connector copies it into the catalog
(descriptions *"Enabled by default"*), and Documentation Propagation fans the identical
text downstream and to siblings — zero attacker effort, zero configuration. One poisoned
column becomes N agent-readable surfaces because the platform's own default-on automation
did the spreading. That is what Antigen's `get_lineage` blast radius is for: retracing the
platform's own propagation vector to find the copies, not generic *"what's downstream?"*
analysis.

**And DataHub does stamp the copies — which is the sharper finding, not a weaker one.**
The same page is explicit that provenance is preserved: *"you'll be able to recognize
propagated descriptions as those with the thunderbolt icon next to them,"* and *"The
tooltip will provide additional information, including where the description originated
and any intermediate hops that were used to propagate the description."* It is modelled
properly, too —
[`MetadataAttribution`](https://github.com/datahub-project/datahub/blob/master/metadata-models/src/main/pegasus/com/linkedin/common/MetadataAttribution.pdl)
carries `actor`, `source` and `sourceDetail`. **That provenance never reaches the agent
tool surface.** `get_entities` returns the description as a bare string — Antigen's own
reader takes `editableProperties.description` or `properties.description` and gets text,
with no attribution field and no propagation marker to take
(`antigen/gateway.py::_entity_description`). So the copy is fully traceable to a human
looking at the UI, and completely unmarked for the LLM reading the tool result — and the
LLM is the reader that acts on it. The mitigation DataHub built lands on the one consumer
that was never going to be fooled. (Calibration: this chain is assembled from DataHub's
own documented defaults; we have not measured end-to-end propagation on a live
deployment, and the tool-surface claim is about the fields the Agent Context Kit returns
today, which is what our gateway parses.)

## Who can actually write catalog free text

DataHub's [bootstrap `policies.json`](https://github.com/datahub-project/datahub/blob/master/metadata-service/war/src/main/resources/boot/policies.json)
grants **no `EDIT_*` privilege to `allUsers`** — so "anyone with an account" would be
wrong, and a judge who opens that file should see us not claiming it. Three paths are real:

1. **Any owner of any asset.** The default **"Asset Owners - Metadata Policy"** applies to
   `resourceOwners` and grants **`EDIT_ENTITY_DOCS`** and
   **`EDIT_DATASET_COL_DESCRIPTION`**. Ownership is the normal state of a data producer,
   not an escalation.
2. **Ingestion, which consults no DataHub policy at all — the widest path.** The
   [dbt](https://docs.datahub.com/docs/generated/ingestion/sources/dbt) connector ingests
   model and column descriptions; the
   [Snowflake](https://docs.datahub.com/docs/generated/ingestion/sources/snowflake)
   connector ships Descriptions *"Enabled by default"*, mapping `COMMENT ON COLUMN`
   straight into catalog text. The real authorship boundary is therefore **whoever can
   merge a dbt PR or run DDL in the warehouse** — reviewed as documentation, if at all.
   And nothing on the agent-readable path labels the result: `get_entities` hands the LLM
   a bare string, with no marker separating a reviewed human edit from connector output.
3. **DataHub Cloud Change Proposals.** `Propose Description` and `Propose Dataset Column
   Descriptions` are
   [granted by default to the **Reader** role](https://docs.datahub.com/docs/managed-datahub/change-proposals),
   and pending proposals sit in the Task Center **before** anyone approves them.

## Why DataHub's own tooling doesn't close it

To be precise, because overclaiming here is checkable: **DataHub Metadata Tests *can*
pattern-match description text.** They are a Cloud-only (`saasOnly`) feature whose Property
conditions support a **`Matches Regex`** operator, so a regex over asset descriptions is
buildable today. Three things it provably cannot do:

- **KB / Document entities are out of scope.** [Supported types](https://docs.datahub.com/docs/tests/metadata-tests)
  are *Dataset, Dashboard, Chart, Data Flow, Data Job, Container* — the two payloads
  Antigen recovers through `grep_documents` are invisible to it.
- **It is not a write-time gate you can rely on.** Scheduled evaluation runs *"typically
  every 24 hours"* and custom schedules *"cannot"* be configured. The same FAQ answer does
  describe real-time evaluation — *"When an individual asset changes in DataHub, all tests
  that include it in scope are evaluated"* — but it is *"typically disabled by default"* and
  *"can be enabled on demand"*, i.e. via your vendor. On the default configuration an agent
  that queries inside the scheduled window reads the payload.
- **Its actions are label-only** — *"Adding or removing specific Tags / Glossary Terms /
  Owners / Domain."* A Metadata Test can *mark* a poisoned asset. It cannot excise the
  span and it cannot hash the field. (It cannot walk lineage either — but the Actions
  framework *can*, and does; that concession is below.) The four mutations in the table
  below are the part with no native equivalent.

Three adjacent tools, then the three questions a DataHub PM asks next, complete the
survey.
[`datahub-classify`](https://github.com/acryldata/datahub-classify/blob/main/datahub-classify/README.md)
is the closest OSS ancestor — its `Description` prediction factor is a *"regex list
which is to be matched against column description"* — but it exists to type PII,
proposing glossary terms for what it matches rather than rewriting anything, and its
built-in `DataHubClassifier` has been
[removed from OSS](https://docs.datahub.com/docs/metadata-ingestion/docs/dev_guides/classification)
(it sat on the unmaintained `acryl-datahub-classify` stack, pinned to `numpy<2` and an
outdated spaCy) — and the library's own README now opens with *"**DEPRECATED:** This
library is deprecated and is no longer actively maintained… Please migrate away from
`acryl-datahub-classify`."*

**The [Actions framework](https://docs.datahub.com/docs/actions) deserves a real
concession, not a dismissal, and it is the one a DataHub PM would open the laptop for.**
Actions is arguably the right *packaging* for Antigen — an event-driven listener that
scans on every metadata change instead of on a schedule; it is named as roadmap below.
But it also already ships the mechanic in `antigen/blast_radius.py`. The
[**Tag Sync / Tag Propagation Action**](https://docs.datahub.com/docs/datahub-actions/src/datahub_actions/plugin/action/tag)
(`tag_propagation`) exists today: *"You can apply a tag (like `critical`) on a dataset
and have it propagate down to all the downstream datasets,"* it is lineage-driven, *"The
action supports both additions and removals of tags"* — and it carries a documented limitation:
*"Tag Propagation is currently only supported for downstream
datasets. Tags will not propagate to downstream dashboards or charts."* There is a sibling
[Glossary Term Propagation Action](https://docs.datahub.com/docs/datahub-actions/src/datahub_actions/plugin/action/term)
(`term_propagation`) with the same shape, and a Cloud-only
[Glossary Term Propagation automation](https://docs.datahub.com/docs/automations/glossary-term-propagation)
(*"currently in Public Beta in DataHub Cloud"*) that propagates terms *"to all downstream
lineage columns and sibling columns"* — the closest analogue anywhere to the
quarantine-tag mechanic, and the reason a Cloud user would rightly ask why we hand-rolled.

So, stated plainly: **blast radius is not an invention. It is DataHub's own documented
propagation semantics, pointed at a security label.** That is the honest frame and we
think it is the better one — the argument is not "we built lineage propagation," it is
"the platform propagates *documentation* by default and propagates *tags* on request, so
the correct place to put a quarantine marker is along the exact same edges the poison
travelled." What Actions does *not* ship is the other end of the loop: no bundled action
contains detection logic, and none of them excises a span, hashes a field, or writes a
forensic record. Packaging Antigen as an `antigen_scan` action — and, where the semantics
already exist, calling `tag_propagation` instead of re-walking lineage ourselves — is the
right next step, and it is on the roadmap below for that reason.

**The two questions after that, answered rather than skipped:**

- **[DataHub Cloud Agents](https://docs.datahub.com/docs/features/feature-guides/agents)
  and [Ask DataHub](https://docs.datahub.com/docs/features/feature-guides/ask-datahub) are the
  right *host*, not a competing control.** Agents (`saasOnly`, *"Private Beta"* from Cloud
  v1.0.1) is explicitly *"an automation platform"* built from **Agents**, **Tasks**
  (*"triggered manually, on a schedule, or by events"*) and **Decisions**
  (*"human-in-the-loop checkpoints where an agent pauses and requests input"*) — which is
  precisely the shape of `scan` → `cure --dry-run` → human `--apply`. So the honest reading
  is not "Cloud already does this"; it is *Antigen is the check a Task would run, and the
  approval gate it would pause at*. Ask DataHub — the conversational assistant grounded in
  the metadata graph — is the **victim class** shipping inside the product, not a
  substitute for the control.
- **[Assertions](https://docs.datahub.com/docs/managed-datahub/observe/assertions) cannot
  express this rule.** An assertion is *"a data quality test that finds data that violates
  a specified rule"*, and all six types (Freshness, Volume, Column Metric, Column Value,
  Custom SQL, Schema) evaluate rows, counts or schema — never metadata text. No assertion
  type can say *"this description contains an instruction."* That is why the survey names
  Metadata Tests, not Assertions, as the nearest native matcher.

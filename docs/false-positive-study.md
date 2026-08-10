# False-positive study — Antigen's detector on 38,031 catalog descriptions it did not write

> **Headline: 24 flags in 38,031 unique public catalog descriptions — a flag rate of
> 0.063 % (6.3 per 10,000). All 24 are false positives. Zero true positives.
> The rate is not uniform: it is 0.003 % on descriptions under 200 characters and
> 4.7 % on descriptions over 2,000 characters.**

Reproduce: `python scripts/fp_corpus.py all` · corpus digest
`485c9cec80cbc38d78810f7c2bfcfa03d99dc5e6350f1c4e309ebb9f18c15c58` ·
detector run at commit `b4daa52`, `antigen/detect.py` **unmodified** (`git status` clean
for that file for the whole study).

---

## Why this exists

Until this study, every negative example in this repository was written by the person who
wrote the detector: 18 `NearMiss` entries in `antigen/nearmiss.py` and 15 `BENIGN` strings
in `tests/test_robustness.py`. Both sets are still useful — they are an adversarial gauntlet,
deliberately built from the detector's own vocabulary — but *"0 false positives on 15 strings
I wrote"* is not a false-positive rate, and the 78-entity scale run does not help either,
because 60 of those 78 entities are self-generated padding.

The question a platform team actually asks before pointing a scanner at their catalog is:
**what is your flag rate on real descriptions?** This document answers it with text Antigen
never authored, on a corpus large enough that the answer has a decimal point.

`README.md` predicted the shape of the risk (*"Expect false positives on descriptions that
legitimately name an external endpoint. Reverse-ETL and vendor-sync documentation… is shaped
exactly like exfiltration"*). That prediction is **directionally right and specifically
wrong**: the co-occurrence of an external endpoint with data-movement vocabulary is indeed
what fires, but in real catalogs the endpoint is almost never a reverse-ETL sink. It is a
*contact-us address* or a *source link*. See [False-positive classes](#false-positive-classes).

---

## The corpus

| | |
|---|---|
| Raw descriptions harvested | **65,891** |
| Unique after de-duplication and filtering | **38,031** |
| English-like subset (crude stopword probe) | 25,565 (67 %) |
| Sources | 2 (public dbt projects on GitHub; Socrata open-data portals) |
| Provenance manifest | [`docs/fp-corpus-manifest.json`](./fp-corpus-manifest.json) |
| Per-item fingerprints | [`docs/fp-corpus-hashes.txt`](./fp-corpus-hashes.txt) |
| Text authored by Antigen | **none** |

### Source 1 — public dbt projects on GitHub (8,640 unique descriptions, 148 repositories)

dbt is the highest-value proxy available without somebody's production catalog, because a
dbt `description:` is not *like* a DataHub description — **it becomes one**. DataHub's dbt
connector copies model descriptions into `datasetProperties.description` and column
descriptions into `editableSchemaMetadata` field descriptions, with descriptions
"Enabled by default". The strings below are literally the text Antigen would scan.

Repositories were **discovered, not chosen**. `scripts/fp_corpus.py` runs the GitHub
code-search API for `filename:dbt_project.yml` (plus five sibling queries for `schema.yml` /
`sources.yml` under `models/`) and takes the repositories GitHub returns, in the order it
returns them. 220 candidates were discovered; 200 passed the ≤ 80 MB size filter (monorepos
are skipped — the tarball cost is not worth the descriptions) and were downloaded at their
pinned default-branch HEAD commit; **148** of those contained at least one dbt schema file
with a description and are recorded in the manifest with their exact commit SHA and SPDX
license. The mix is deliberately not curated: vendor packages (`fivetran/dbt_salesforce`,
`snowplow/dbt-snowplow-ecommerce`, `dbt-labs/dbt-proserv`) sit next to bootcamp projects and
personal portfolios, which is what a real catalog looks like too.

Extraction walks every `*.yml` / `*.yaml` whose top level declares `models` / `sources` /
`seeds` / `snapshots` / `exposures` / `metrics` / `semantic_models` / `macros` (so CI configs
and OpenAPI specs, which also use `description:`, are excluded) and pulls every `description`
value at any depth, plus every `{% docs %}` block in the repo's `*.md` files.
Pure `{{ doc('…') }}` pointers are dropped — they are not prose, and the prose they point at
is already harvested from the markdown, so counting them would pad the denominator with
strings that can never flag.

### Source 2 — Socrata open-data portals (29,391 unique descriptions, 6,000 datasets, 198 portals)

The Socrata Discovery API indexes the public data catalogs of several hundred cities, states
and agencies. Each record carries a dataset-level description **and** a list of per-column
descriptions — the open-data equivalent of a DataHub dataset description and its column
documentation, written by government data stewards for public consumption. 6,000 datasets
were scrolled in dataset-id order; the largest contributors were `www.datos.gov.co` (1,189
datasets), `data.cityofnewyork.us` (328), `data.bayareametro.gov` (249),
`opendata.maryland.gov` (212) and `data.edmonton.ca` (200).

Text is scanned **exactly as the portal stores it**, including embedded HTML — that is what
is in the field, and normalising it would be measuring a different corpus than the one that
exists.

### Sources attempted and not used

- **A live DataHub demo instance.** `https://demo.datahubproject.io/api/graphql` returns
  **HTTP 401** to unauthenticated requests, so no third-party DataHub metadata could be read.
- **data.gov (CKAN).** `https://catalog.data.gov/api/3/action/package_search` returns
  **HTTP 404** — the CKAN action API is no longer reachable at that path.
- **BigQuery / Snowflake public dataset documentation.** Both require an authenticated
  project to enumerate table and column descriptions; not obtainable cleanly and read-only.

---

## Method

1. Harvest into a local cache (`scripts/.fp_corpus_cache/`), recording for each string its
   source, origin (repository or portal), pinned reference (commit SHA or dataset id),
   locator (file path + node, or column name) and sha256.
2. De-duplicate on the exact string. dbt packages copy each other constantly — every Fivetran
   connector package repeats the same column docs — and portals republish boilerplate, so
   counting a string once is the only defensible denominator. 65,891 raw → 38,031 unique.
3. Run `antigen.detect.detect()` over every unique string, unmodified, offline, stdlib-only.
4. Read **every** flagged string by hand and record a verdict with reasoning.

Nothing was tuned. No threshold was moved, no pattern was narrowed, and the detector file was
not touched at any point during the study — deliberately, because the point of the exercise is
to *measure* the shipped detector, not to produce a flattering number for it.

---

## Results

```
raw descriptions harvested : 65,891
unique descriptions scanned: 38,031
flagged by detect()        : 24
flag rate                  : 0.0631 %   (6.3 per 10,000)
English-like subset        : 25,565 scanned, 24 flagged (0.0939 %)
```

| Slice | Scanned | Flagged | Flag rate |
|---|---:|---:|---:|
| **All** | **38,031** | **24** | **0.063 %** |
| dbt (all node types) | 8,640 | 2 | 0.023 % |
| Socrata (all) | 29,391 | 22 | 0.075 % |
| — Socrata dataset-level descriptions | 4,637 | 22 | **0.474 %** |
| — Socrata column descriptions | 24,754 | 0 | 0 % |
| — dbt column descriptions | 5,802 | 0 | 0 % |
| — dbt model descriptions | 1,021 | 0 | 0 % |
| — dbt `{% docs %}` blocks | 842 | 1 | 0.119 % |
| — dbt macro descriptions | 167 | 1 | 0.599 % |

### The rate is a function of length, and that is the finding an adopter should budget against

| Description length | Scanned | Flagged | Flag rate |
|---|---:|---:|---:|
| < 200 chars | 32,723 | 1 | 0.003 % |
| 200–500 | 3,674 | 5 | 0.136 % |
| 500–1,000 | 985 | 4 | 0.406 % |
| 1,000–2,000 | 456 | 5 | 1.096 % |
| ≥ 2,000 | 193 | 9 | **4.663 %** |

Median description length in the corpus is 57 characters; the median *flagged* description is
1,429. The reason length drives the rate is that the constituents of a **composite** signal
only have to co-occur **anywhere in the same field** — the rule does not require them to be
near each other — so every additional paragraph is another chance to supply a missing
constituent. That is the mechanism behind all 24: **23 scored on the exfiltration triple
alone** (transfer verb + sensitive object + external destination), which is a three-part
conjunction scattered across one long field. Note this is *not* a claim that every flag
needs two signals — instruction-override, persona jailbreak and reveal-a-secret each score
2 and flag on their own; only tool-poisoning is gated on a second cue. Short column docs are
effectively immune. Long,
hand-curated, high-value descriptions — a data dictionary entry for the `customers` table,
the sort of field a steward spent an afternoon on — flag at roughly **1 in 21**.

Read that next to `antigen/cure.py:236-243`: outside the demo corpus there is no fixture, so
a cured field is replaced **in its entirety** with `[field quarantined by Antigen pending
human review]`. The class of description most likely to be flagged is the class most
expensive to lose. That is the argument for `cure` staying dry-run by default, and it is now
an argument with a number attached instead of an intuition.

### Zero true positives

No description in 38,031 public catalog descriptions was an actual prompt injection. That is
consistent with `README.md`'s own statement that there are **no publicly confirmed
in-the-wild cases** of an attack via catalog metadata, and it is worth stating plainly: this
study found the threat's *absence* in the wild, and measured only the cost side of the
tradeoff.

---

## False-positive classes

**Class A — contact-and-link boilerplate (21 of 24, 88 %).** A dataset description that ends
with *"for questions, email x@y.gov"* or *"see https://…"* while using ordinary
data-engineering vocabulary — `records`, `export`, `copy`, `forward`, `contents of`,
`token`, `API key` — somewhere earlier in the same field. The exfiltration rule wants a
transfer verb + a sensitive object + an external destination; a contact footer supplies the
destination for free, and a long description supplies the other two by accident. This class
is the real-world generalisation of the reverse-ETL risk the README predicted, and it is far
more common than reverse-ETL documentation, because **every** mature catalog description has
a contact address or a source link.

**Class B — second-person product guidance (1 of 24).** *"You can use the tool to find
proposed projects near you."* `_READER_DIRECTED_RE` matches *you*; `_TOOL_POISON_RE` matches
*use the tool*; the pair scores 2. Written for a human reader, read as an instruction to an
agent. Any catalog whose descriptions address the reader ("you can join this to…") will
produce these.

**Class C — an example email address inside a column or macro doc (2 of 24).** Both dbt flags.
The shorter one is 52 characters — a `{% docs %}` block that dbt resolves into a column
description: *"Unique ID set by business e.g. 'jon.doe@email.com'"*. One
example address in one column description is enough to supply the "external destination", and
the word *email* doubles as the transfer verb. The other is documentation for a PII-**masking**
macro — a privacy tool's own docs flagged as exfiltration.

**Not observed, and therefore still unmeasured:** actual reverse-ETL / vendor-sync
documentation (*"syncs customer email addresses to Braze at https://…"*). Open-data portals do
not have it and the sampled dbt projects did not either. The README's specific prediction
remains untested; only its mechanism was confirmed.

---

## Every flagged string, verbatim, with a verdict

All 24 are reproduced below in full. Each is labelled with the exact rule that fired
(`Detection.rule_fired`, which quotes the matched spans) and a link to the public source.
The same 24 strings, plus their full sha256 and complete detection records, are in
[`docs/fp-corpus-manifest.json`](./fp-corpus-manifest.json).


### Class A — contact-and-link boilerplate (21 of 24)

#### [3] `data.cityofnewyork.us` · dataset `2iga-a6mk` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `292000942176bbe5`
- Rule fired: `exfiltration ('email' … 'email' → 'https://www1.nyc.gov/site/planning/applicants/applicant-portal/application-process.page">Application')`
- Source: <https://data.cityofnewyork.us/d/2iga-a6mk>
- Why it is a false positive: Names an email column, then closes with a *“To report data errors… email zap_feedback_dl@planning.nyc.gov”* footer and several source links.

<details><summary>Verbatim (1,538 characters) — click to expand</summary>

```text
The Department of City Planning (DCP) processes land use applications submitted by City or other public agencies and other (private) applicants. This data set provides information on land use applications, specifically the project tracking and description data related to approximately 30,000 projects since the late 1970s.

ZAP project data appears on NYC Planning - Zoning Application Portal Search. It includes data migrated from the prior applications tracking system (LUCATS) and covers all projects that have been "Noticed" (that they will appear before the City Planning Commission in 30 or more days for Certification as complete for the ULURP process to begin) or Filed (a CEQR or Land Use application has been formally submitted to the Department for review) through completion (approval, disapproval, withdrawal, or termination). For more information on the land use and environmental review application process see: <a href="https://www1.nyc.gov/site/planning/applicants/applicant-portal/application-process.page">Application Process Overview</a>

You can explore this data in the <a href="https://zap.planning.nyc.gov/projects">Zoning Application Portal</a>

To report data errors or for questions, email <a href="mailto:zap_feedback_dl@planning.nyc.gov">zap_feedback_dl@planning.nyc.gov</a>.

All previously released versions of this data are available on the <a href="https://www.nyc.gov/content/planning/pages/resources/datasets/zoning-application-portal">DCP Website: BYTES of the BIG APPLE</a>. Current version: 20260427
```

</details>

#### [4] `data.calgary.ca` · dataset `2jxp-s4bx` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `736c3bfbf9f0fb35`
- Rule fired: `exfiltration ('export' … 'records' → 'ceip@calgary.ca')`
- Source: <https://data.calgary.ca/d/2jxp-s4bx>
- Why it is a false positive: *“contains **records**…”* plus *“solar-**export** rates”* plus a contact address `ceip@calgary.ca` at the bottom.

<details><summary>Verbatim (2,927 characters) — click to expand</summary>

```text
This dataset contains records for completed Residential Clean Energy Improvement Program (RCEIP) projects in Calgary’s single-family detached homes from 2023 onward. Each row represents one home and includes the completion year, installed energy-efficiency and renewable-energy measures, financing and incentives disbursed, and estimated annual energy savings, greenhouse gas reductions and utility-cost avoidance.	
	
<b>What it contains</b> 
Each row describes one home with completed RCEIP upgrades. The row lists the completion year, property type, upgrade measures, financing and incentives paid, and estimated yearly energy, greenhouse gas (GHG), and utility-cost impacts.
	
<b>Coverage</b> 
This release contains completed single-family detached home records from 2023 onward. Approved or in-progress work is not included and may appear in a future update after completion.
	
<b>How to read counts</b> 
Upgrade-measure fields contain whole-number counts. A value of 0 means no measure was recorded. “Completed Projects” is the sum of the upgrade-measure fields in that row. It is not a count of buildings.
	
<b>Solar PV fields</b> 
The three fields labelled “with Solar PV” report the impact attributed to solar PV in this file. They are separate from the non-solar energy, GHG, and cost fields. “Total energy cost avoidance” adds the non-solar and solar PV cost avoidance amounts.
	
<b>Estimated results</b> 
Energy, GHG, and cost impacts are estimates, not measured utility-bill results. Actual results may differ because of equipment sizing, installation quality, occupant behaviour, weather, energy prices, and changes to emissions factors.
	
<b>Emissions factors</b> 
Estimated energy changes are converted to GHG impacts using electricity factors based on Alberta’s grid and standard natural-gas combustion factors. These factors can change over time.
	
<b>Energy costs</b> 
Estimated cost avoidance uses blended electricity and natural-gas rates. The estimates may use a reference year and a constant escalation assumption. They do not necessarily match current, site-specific, time-of-use, or premium solar-export rates.
	
<b>Zeros, blanks, and negative values</b> 
A zero means no value was reported for that impact. A blank means the value is missing. A negative savings or cost-avoidance value means the model estimated an increase rather than a reduction.
	
<b>Rounding</b> 
Values are rounded for publication. Component amounts may differ from a displayed total by up to $1 or 0.1 in the reported unit because calculations may use unrounded source values.
	
<b>Updates and use</b> 
This file reflects information available at publication and may be updated. It is provided for information only, without warranty of accuracy or completeness. Use of the data does not imply City endorsement of a product, service, contractor, or analysis.
	
<b>Contact</b> 
Questions about the dataset or RCEIP: ceip@calgary.ca
```

</details>

#### [5] `data.princegeorgescountymd.gov` · dataset `2qma-7ez9` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `61f261190f2539d1`
- Rule fired: `exfiltration ('send' … 'email' → 'https://princegeorgescountymd.legistar.com/Legislation.aspx,')`
- Source: <https://data.princegeorgescountymd.gov/d/2qma-7ez9>
- Why it is a false positive: *“please **send** an **email** at any time to: CountyClick311@co.pg.md.us”* with a legistar.com source URL earlier in the field.

<details><summary>Verbatim (1,431 characters) — click to expand</summary>

```text
This dataset allows you to view information about government spending. Disclosure of payments is based on the legislative requirements of CB-19-2011 which can be accessed via https://princegeorgescountymd.legistar.com/Legislation.aspx, which is an effort to provide enhanced transparency and convenient public access to this information. Certain expenditures are subject to review on a case-by-case basis to ensure that confidential or privileged material is maintained in accordance with legal requirements. As such, these expenditures may not appear on this website.

Unaudited data is updated quarterly for all payees with combined spending of $25,000 or more. When cumulative payee spending exceeds $25,000 threshold, all payments made during the Fiscal Year will be reported. Datasets, current and up to seven prior fiscal periods, will be available for your search by Fiscal Year. The following information will be displayed: Payee Name, County Agency Name, Payee Zip Code, Amount and Payment Description. Website options include: sorting, exporting data, creating graphs, and customizing your display format - among other features. There is an online tutorial.

If you have any questions or comments about this citizen portal site, please send an email at any time to: CountyClick311@co.pg.md.us, or call 3-1-1 (301-883-4748), Monday - Friday, 7am - 7pm, and a Customer Service Representative will be glad to assist you.
```

</details>

#### [6] `highways.hidot.hawaii.gov` · dataset `2tw7-ygpr` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `cdc68278bda75023`
- Rule fired: `exfiltration ('email' … 'email' → 'https://files.hawaii.gov/dbedt/op/gis/data/blkgrp20.pdf')`
- Source: <https://highways.hidot.hawaii.gov/d/2tw7-ygpr>
- Why it is a false positive: GIS metadata footer: *“email: gis@hawaii.gov”* plus a source-PDF URL.

Verbatim:

```text
This dataset shows 2020 Census Block Group Boundaries, with population, for the State of Hawaii, excluding northwest Hawaiian Islands and clipped to the coastline. 

Source: US Census Bureau, September 2021. For additional information about this layer, please refer to metadata at https://files.hawaii.gov/dbedt/op/gis/data/blkgrp20.pdf or contact Hawaii Statewide GIS Program, Office of Planning and Sustainable Development, State of Hawaii; PO Box 2359, Honolulu, Hi. 96804; (808) 587-2846; email: gis@hawaii.gov; Website: https://planning.hawaii.gov/gis.
```

#### [7] `data.cityofnewyork.us` · dataset `3aje-fhc5` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `49d4962705a623a1`
- Rule fired: `exfiltration ('email' … 'email' → 'https://www.nyc.gov/office-of-the-mayor/elected-officials-engagement-request.page')`
- Source: <https://data.cityofnewyork.us/d/3aje-fhc5>
- Why it is a false positive: The dataset genuinely **is** about emails (*“the name, position, and email of the requestor”*) and the field ends with the request-page URL.

Verbatim:

```text
The dataset contains the date/time of the request; the name, position, and email of the requestor; the name and email of the elected official; and the name(s) of the city agency/agencies they are requesting to engage.

https://www.nyc.gov/office-of-the-mayor/elected-officials-engagement-request.page
```

#### [8] `data.cdc.gov` · dataset `3cxc-4k8q` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `148012d851c86019`
- Rule fired: `exfiltration ('send' … 'the regional table' → 'https://www.cdc.gov/surveillance/nrevss/labs/index.html).')`
- Source: <https://data.cdc.gov/d/3cxc-4k8q>
- Why it is a false positive: *“Participating laboratories **send** weekly reports…”* + *“the regional **table**”* + CDC surveillance URLs.

<details><summary>Verbatim (3,460 characters) — click to expand</summary>

```text
More than 450 public health, clinical, and commercial laboratories located throughout the United States voluntarily participate in surveillance for respiratory syncytial virus (RSV) through CDC's National Respiratory and Enteric Virus Surveillance System (NREVSS) (https://www.cdc.gov/surveillance/nrevss/labs/index.html). The data contain weekly, aggregate counts of RSV tests performed and RSV detections as reported to NREVSS since April 11, 2020. 

NREVSS data are reported weekly at the national and 10 HHS regional levels (https://www.hhs.gov/about/agencies/iea/regional-offices/index.html). The presented data are RSV Nucleic Acid Amplification Test (NAAT) results, which include reverse transcription-polymerase chain reaction (RT-PCR) tests. These data exclude antigen, antibody, and at-home test results. Less than 5% of RSV tests reported to NREVSS are from antigen tests. All data are provisional and subject to change. Reporting is less complete for the most recent weeks, but relatively complete (>90%) for the period up to 2 weeks earlier. 

Percent positivity is a surveillance metric used to monitor RSV activity over time and by geographic area. Participating laboratories send weekly reports of the total number of RSV tests performed that week, and the number of those tests that were positive. In the table and upon hovering on the map, the total test counts reflect the latest data reported to NREVSS and may differ from data presented by public health jurisdictions. Public health jurisdictions may have additional data not reported to NREVSS and may use a different reporting cadence. The RSV trend graphs display the weekly average percent of tests positive for RSV among all the tests performed. Each point on the regional table displays the average number of RSV tests that were performed, and the average percent of those that were positive during a 3-week period (i.e., the specified week, and the weeks immediately preceding and following it). This is also known as a centered, 3-week moving average. The RSV detections displayed are the 5-week moving average (average of the 4 previous and current weeks) in accordance with the recommendations for assessing RSV trends by detections (https://academic.oup.com/jid/article/216/3/345/3860464). 

NREVSS strives to present precise estimates of respiratory viral trends and minimize reporting burden for participating laboratories. However, there are several limitations to this surveillance system. NREVSS is a laboratory-based surveillance system that does not have patient-specific data; multiple tests from a single patient may be included. In addition, NREVSS does not collect demographic or clinical data (i.e., hospitalizations or deaths). Testing practices may vary regionally, and the number of participating laboratories may change from year to year. Laboratories from all 50 states report data weekly, but reporting is voluntary and may not be representative of local RSV activity. The data do not include all test results within a jurisdiction and therefore do not reflect all RSV NAATs administered regionally or nationally. Participating laboratories vary in size, testing capabilities, and areas and populations served. Geographic results from clinical laboratories are based on testing location and laboratories may test samples from across one or more states.  For more information on NREVSS and RSV surveillance please visit: https://www.cdc.gov/surveillance/nrevss.
```

</details>

#### [10] `data.brla.gov` · dataset `3j5u-jyar` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `a53571f84cf1ae67`
- Rule fired: `exfiltration ('email' … 'email' → 'traffic@brgov.com')`
- Source: <https://data.brla.gov/d/3j5u-jyar>
- Why it is a false positive: *“contact the Criminal Traffic Division via **email** at traffic@brgov.com”*.

Verbatim:

```text
Listing of active warrants for Baton Rouge City Court.

Warrants are posted to the site daily, however it may take up to 7-10 days for information processed in court to be reflected on the site.  If you have questions please contact the Criminal Traffic Division via email at traffic@brgov.com or call (225) 389-5278.

This lookup is not confirmation of an active warrant.  All City Court warrants should be confirmed by the official court file.  Please contact the City Constable's Office at 389-3889 or 389-3004 for confirmation.
```

#### [11] `data.edmonton.ca` · dataset `3trg-p57p` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `0ab553df92636d4f`
- Rule fired: `exfiltration ('forward' … 'records' → 'https://www.edmonton.ca/city_government/documents/RoadsTraffic/City-wide_Flood_Mitigation_Study.pdf')`
- Source: <https://data.edmonton.ca/d/3trg-p57p>
- Why it is a false positive: *“include only **records** that can be mapped”* plus a study-PDF URL. Truncated by the Socrata API at its 4,000-character ceiling.

<details><summary>Verbatim (4,000 characters) — click to expand</summary>

```text
This map is a representation of each depth layers in the Surface Surcharge map from the 2014 Flood Mitigation Study.

This spatial data was created as a result of a 2016 study, using 2014 data, done for the Edmonton area to determine the vulnerable drainage and sewage areas of Edmonton in regards to a 1 in 100 year rainfall event.

Due to the constant changing of subsurface infrastructure (adding, upgrading, etc.) combined with the constant changing definition of a 1 in 100 year rainfall event (based on historic rainfall amounts), this raster file reflects the results of a study done in 2016 and should neither suggest previous year’s vulnerabilities nor future year’s vulnerabilities.

For a more regional Edmonton area breakdown of the Study’s results: 

https://www.edmonton.ca/city_government/documents/RoadsTraffic/City-wide_Flood_Mitigation_Study.pdf

There are three different colour to the vulnerability of the roadways and the corresponding ponding depth that would occur for that area during a large rainstorm.

Those colours are:

Green (representing the depth from surface that sanitary flows can surcharge from less than 2.5 m)
Yellow (representing the depth from surface that sanitary flows can surcharge from 1.5 to 2.5 m)
Red (representing the depth from surface that sanitary flows can surcharge from greater than 1.5 m)

This Raster file is best viewed overlaid with the 2016 Flood Mitigation Study - Drainage and Sanitation Surcharge Map; as the various coloured areas follow the subsurface infrastructure (and the corresponding roadways if you are also viewing the street map as a layer).

Disclaimer: No Warranty with Flood Risk Maps.
Your use of the flood risk maps is solely at your own risk, and you are fully responsible for any consequences arising from your use of the flood risk maps. The flood risk maps are provided on an “as is” and “as available” basis, and you agree to use them solely at your own risk. There are no warranties, expressed or implied in respect to the flood risk maps or your use of them, including without limitation, implied warranties and conditions of merchantability and fitness for any particular purpose.

Please note that the flood risk maps have been modified from their original source, and that all data visualization on maps are approximate and include only records that can be mapped.

This dataset is based on 2014 information and will not be updated further. The model is based on a theoretical, worst-case scenario storm that has never occurred in the Edmonton area.

Model Accuracy:

The LiDar used was a 5 meter grid system.  LiDar has an accuracy of ? cm horizontally/vertically.  Bare Earth LiDar was used in for this model surface.  
This is a spline fit interpolations model.  This is a 1D-1D model with 2D interpolations.The accuracy of the information provided in these data sets is plus or minus 10 cm vertically, and 10 cm horizontally.   

The 100 year flood was based on the 2015 Edmonton 4 year Chicago storm event over 20 plus neighbourhoods.  The data is a collection of the worst case scenario of model runs.  

This is a common practice for Edmonton drainage models.  These models are high level concept and projects determined from this data set will undergo finer, more detailed modeling.

These maps are a visual representation and intended to be used when prioritization of the best engineering solutions that are scheduled to be brought forward to Utility Council to mitigate future flooding in the City.  The best engineering solutions are high level concept designs and require further modeling and design.  At the time of the PDF release, November 9, 2016 there was no funding for any projects to be completed or for further design.  Strategy will be brought forward to Utility Committee on June 7, 2017.  Council will be determining funding and rate of project completion.  
The Storm size used in these models are larger than Edmonton has historically seen.  Histo
```

</details>

#### [12] `internal-data.ct.gov` · dataset `3txk-7972` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `5b7120290c922101`
- Rule fired: `exfiltration ('forward' … 'records' → 'https://libguides.ctstatelibrary.org/hg/divorce/indexes">county-specific')`
- Source: <https://internal-data.ct.gov/d/3txk-7972>
- Why it is a false positive: State-library finding aid: *“**records**”* throughout plus an *“email form”* link and libguides URLs.

<details><summary>Verbatim (3,999 characters) — click to expand</summary>

```text
Connecticut’s Superior Court was created in 1711. It was the second level of the court system, sitting above the county and probate courts, but below the final court of appeal, which up until 1785 was the General Assembly and afterward was the Supreme Court of Errors.

The early Superior Court was an itinerant or circuit court, meaning that instead of having separate sitting courts for each county, the four judges, as well as the clerks and other officers, traveled from county to county holding sessions in each several times per year.  Many famous names of Connecticut history were judges of the Superior Court, including Roger Sherman, Jonathan Trumbull, Eliphalet Dyer, William Pitkin, Jonathan Law, Oliver Ellsworth, and others.

This index of divorces is from the early Superior Court’s 31 volumes of record books, which were the official record of the court kept by the clerk. The record books run from the establishment of the court in 1711 to 1798, the first divorce is recorded in 1716.

In this time period, divorces were either granted by the General Assembly or by the Superior Court. Someone wishing to be divorced from their spouse would have to submit a petition to the court.

Divorce laws were very strict, usually permitting a petitioner to divorce their spouse only in very clear-cut cases of desertion, adultery, or deformity. Staunchly Puritan courts in the early part of the eighteenth century were very hesitant to grant divorces, but as the century wore on and divorce laws loosened up somewhat, they did so with much greater frequency. This process accelerated after independence from Great Britain; the majority of the 1,080 records in this index are from 1776 and after.

Divorce case records usually contain the husband and wife’s names, their marriage date, the town of the petitioner, and reasons why the petitioner is asking for the divorce. Due to the formal, legalistic way record entries were written, maiden names were usually not part of the record unless the husband was the one making the petition. This unfortunately means that maiden names were rarely recorded, as the vast majority of petitioners were female. Children were almost never mentioned.

In 1801, the General Assembly added two judges to the overburdened Superior Court and split it into two circuits of four counties each. All record books from 1798 forward are arranged by their respective counties, which is why this index ends with that year.

Please note that there are many direct quotes from the records books in the “notes” field and elsewhere. The index therefore includes terms that are considered archaic, offensive, and inappropriate to use in modern times.

Most, though not all, of these records have corresponding case files that may have more information. To find those, either consult <a href="https://libguides.ctstatelibrary.org/hg/divorce/indexes">county-specific indexes</a> or ask the History & Genealogy Unit staff for assistance.

To request a copy of a record, please contact the staff of the <a href="https://libguides.ctstatelibrary.org/hg/home">History & Genealogy Unit</a> by telephone at (860) 757-6580 or through our <a href="https://portal.ct.gov/csl/email-us?language=en_US">email form</a>.  When requesting a copy of a record, please include the names of the individuals as well as the volume and page number. You are also more than welcome to visit the Connecticut State Library to see the record books for yourself!

Several volumes have extra, non-numbered pages at the end; these are denoted by a typographical mark and the word “misc.”

*The February, 1769 term of the Superior Court in Fairfield is filed in a folder in the state archives RG 003, Superior Court Fairfield County Records/Dockets, Box 51.

**Volume 19 contains miscellaneous papers at the end of the numbered pages. These papers are mostly in chronological order, and include court files, invoices, and the records of a few Superior Court terms.

†Volume 21 contains miscellaneous papers
```

</details>

#### [13] `opendata.maryland.gov` · dataset `3xda-h6fq` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `0724d11f47d9bfff`
- Rule fired: `exfiltration ('Email' … 'Email' → 'GIS@mdot.state.md.us')`
- Source: <https://opendata.maryland.gov/d/3xda-h6fq>
- Why it is a false positive: *“For additional information, contact MDOT SHA Geospatial Technologies **Email**: GIS@mdot.state.md.us”*.

<details><summary>Verbatim (3,448 characters) — click to expand</summary>

```text
Maryland Roadway Centerline data consists of linear geometric features which represent the street centerline for all public roadways in the State of Maryland. The centerline represents the geographic location on the roadway between both shoulders (physical center), which often but not always coincides with the center painted line dividing bi-directional travel lanes. Roadway Centerlines data plays an important role in transportation management and planning, while also being the basis for all other roadway related data products. Maryland Roadway Centerline data is the end product of a statewide data sharing process between the Federal Highway Administration (FHWA), Maryland Department of Transportation (MDOT), Maryland Department of Transportation State Highway Administration (MDOT SHA), county governments and local municipal governments. Using a common centerline allows for better exchange of information related to the roadway system and provides opportunities for more efficient collection of information about roadway assets. Some centerlines were created in-house using imagery, GPS data, and MDOT SHA's Highway Performance Monitoring System (HPMS) database and others were received from county governments and updated in house using imagery, GPS data and MDOT SHA's HPMS database. The Centerline data includes annual HPMS updates / improvements submitted to the Federal Highway Administration (FHWA). Maryland Roadway Centerline data is needed for emergency response and management, routing buses and other vehicles, planning for land use and transportation needs, continuity of roadway data and display at county boundaries leading to the same "look and feel" across jurisdictions, tracking assets on and along the roadway network, producing maps at various scales, and numerous other applications. There are opportunities to make these processes more efficient, and this program addresses a shared foundation to solve some of these issues. This data is also used by various business units throughout MDOT, as well as many other Federal, State and local government agencies. Maryland Roadway Centerline data is updated and published on an annual basis for the prior year. This data is for the year 2017. For additional information, contact MDOT SHA Geospatial Technologies Email: GIS@mdot.state.md.us For additional information related to the Maryland Department of Transportation (MDOT) Website: https://www.mdot.maryland.gov/ For additional information related to the Maryland Department of Transportation State Highway Administration (MDOT SHA): Website: https://roads.maryland.gov/Home.aspx MDOT SHA Geospatial Data Legal Disclaimer: The Maryland Department of Transportation State Highway Administration (MDOT SHA) makes no warranty, expressed or implied, as to the use or appropriateness of geospatial data, and there are no warranties of merchantability or fitness for a particular purpose or use. The information contained in geospatial data is from publicly available sources, but no representation is made as to the accuracy or completeness of geospatial data. MDOT SHA shall not be subject to liability for human error, error due to software conversion, defect, or failure of machines, or any material used in the connection with the machines, including tapes, disks, CD-ROMs or DVD-ROMs and energy. MDOT SHA shall not be liable for any lost profits, consequential damages, or claims against MDOT SHA by third parties.
```

</details>

#### [14] `data.oaklandca.gov` · dataset `3z3b-ybca` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `bf0771d0a734825d`
- Rule fired: `exfiltration ('copy' … 'records' → 'www.oaklandca.gov/pec.')`
- Source: <https://data.oaklandca.gov/d/3z3b-ybca>
- Why it is a false positive: *“Any person whose request to inspect or **copy** public **records**…”* plus `www.oaklandca.gov/pec`.

Verbatim:

```text
Any person whose request to inspect or copy public records has been denied, delayed, or not completely fulfilled, may request mediation of their request through the Public Ethics Commission (PEC). The data below summarizes mediations completed by the PEC. For more information visit www.oaklandca.gov/pec.
```

#### [15] `data.oregon.gov` · dataset `3z65-a459` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `eb9e89c88fa1b650`
- Rule fired: `exfiltration ('email' … 'email address' → 'https://forms.gle/7a6wAfG2ZNgATrqF9)')`
- Source: <https://data.oregon.gov/d/3z65-a459>
- Why it is a false positive: *“the Oregon.Data@oregon.gov **email address**”* plus a Google Forms URL.

Verbatim:

```text
Public comments for the Oregon Draft Data Strategy.  Phase 1 extends from July 6, 2020 - August 24, 2020.
Comments are received through a google form (https://forms.gle/7a6wAfG2ZNgATrqF9) and synced daily at 5pm PST.

Individuals who submitted files (pdf, word) to the Oregon.Data@oregon.gov email address in lieu of using the google form will have their comments posted directly to the Oregon Data Strategy Website at https://www.oregon.gov/das/OSCIO/Pages/DataStrategy.aspx
```

#### [16] `data.cdc.gov` · dataset `45cq-cw4i` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `d04405ac0c721d84`
- Rule fired: `exfiltration ('email' … 'email' → 'https://www.cdc.gov/epidemiology-laboratory-capacity/php/our-work/index.html).')`
- Source: <https://data.cdc.gov/d/45cq-cw4i>
- Why it is a false positive: *“by accessing or **copying** any part of the database… (email: wwscan_stanford_emory@lists.stanford.edu)”*.

<details><summary>Verbatim (1,835 characters) — click to expand</summary>

```text
This dataset provides a complete time history of RSV wastewater sample data and calculated metrics from US sampling locations.

CDC’s National Wastewater Surveillance System (NWSS) includes data collected and reported by:
• All data with a source designation of “State_Territory” were generated by state and local health departments are reported to CDC and supported with funding through the Epidemiology and Laboratory Capacity for the Prevention and Control of Emerging Infectious Diseases (ELC) Cooperative Agreement (https://www.cdc.gov/epidemiology-laboratory-capacity/php/our-work/index.html).
• All data with a source designation of “CDC_Verily” were generated by CDC’s national wastewater testing contract (currently with Verily Life Sciences, LLC).
• All data with a source designation of “WastewaterSCAN” were generated by WastewaterSCAN, a partnership between Stanford University, Emory University, and Verily. All results are understood to be based on inputs that are experimental in nature and are not intended to diagnose or treat any disease. The results are provided “as is” and without warranty of any kind. Stanford does not accept liability for any claim arising out of or in connection with the disclosure of these results. WastewaterSCAN indicates that by accessing or copying any part of the database, the user accepts the terms of Stanford’s license (CC BY-NC 4.0). These data are being made available to inform public health decision making. Anyone seeking to use the database for other purposes or for research is required to contact the WastewaterSCAN / SCAN team (email: wwscan_stanford_emory@lists.stanford.edu) and any use of the data should be cited appropriately (https://data.wastewaterscan.org/about/#18).

Learn more at: https://www.cdc.gov/nwss/index.html.

This dataset is updated weekly on Fridays.
```

</details>

#### [17] `cityofchicago-v2.demo.socrata.com` · dataset `4spy-zn25` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `db8173b38473429a`
- Rule fired: `exfiltration ('Export' … 'records' → 'RDAnalysis@chicagopolice.org')`
- Source: <https://cityofchicago-v2.demo.socrata.com/d/4spy-zn25>
- Why it is a false positive: *“select CSV from the **Export** menu”* + *“65,000 **records**/rows”* + contact `RDAnalysis@chicagopolice.org`.

<details><summary>Verbatim (2,733 characters) — click to expand</summary>

```text
This dataset reflects reported incidents of crime (with the exception of murders where data exists for each victim) that occurred in the City of Chicago from 2001 to present, minus the most recent seven days. Data is extracted from the Chicago Police Department's CLEAR (Citizen Law Enforcement Analysis and Reporting) system. In order to protect the privacy of crime victims, addresses are shown at the block level only and specific locations are not identified. Should you have questions about this dataset, you may contact the Research & Development Division of the Chicago Police Department at 312.745.6071 or RDAnalysis@chicagopolice.org.  Disclaimer: These crimes may be based upon preliminary information supplied to the Police Department by the reporting parties that have not been verified. The preliminary crime classifications may be changed at a later date based upon additional investigation and there is always the possibility of mechanical or human error. Therefore, the Chicago Police Department does not guarantee (either expressed or implied) the accuracy, completeness, timeliness, or correct sequencing of the information and the information should not be used for comparison purposes over time. The Chicago Police Department will not be responsible for any error or omission, or for the use of, or the results obtained from the use of this information. All data visualizations on maps should be considered approximate and attempts to derive specific addresses are strictly prohibited. The Chicago Police Department is not responsible for the content of any off-site pages that are referenced by or that reference this web page other than an official City of Chicago or Chicago Police Department web page. The user specifically acknowledges that the Chicago Police Department is not responsible for any defamatory, offensive, misleading, or illegal conduct of other users, links, or third parties and that the risk of injury from the foregoing rests entirely with the user.  The unauthorized use of the words "Chicago Police Department," "Chicago Police," or any colorable imitation of these words or the unauthorized use of the Chicago Police Department logo is unlawful. This web page does not, in any way, authorize such use. Data are updated daily. The dataset contains more than 65,000 records/rows of data and cannot be viewed in full in Microsoft Excel. Therefore, when downloading the file, select CSV from the Export menu. Open the file in an ASCII text editor, such as Wordpad, to view and search. To access a list of Chicago Police Department - Illinois Uniform Crime Reporting (IUCR) codes, go to http://data.cityofchicago.org/Public-Safety/Chicago-Police-Department-Illinois-Uniform-Crime-R/c7ck-438e
```

</details>

#### [18] `data.princegeorgescountymd.gov` · dataset `5aqg-y7tm` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `cd414add5a2fd0e8`
- Rule fired: `exfiltration ('send' … 'email' → 'https://princegeorgescountymd.legistar.com/Legislation.aspx,')`
- Source: <https://data.princegeorgescountymd.gov/d/5aqg-y7tm>
- Why it is a false positive: Byte-different duplicate of [5] on a second dataset in the same portal.

<details><summary>Verbatim (1,427 characters) — click to expand</summary>

```text
This dataset allows you to view information about government spending. Disclosure of payments is based on the legislative requirements of CB-19-2011 which can be accessed via https://princegeorgescountymd.legistar.com/Legislation.aspx, which is an effort to provide enhanced transparency and convenient public access to this information. Certain expenditures are subject to review on a case-by-case basis to ensure that confidential or privileged material is maintained in accordance with legal requirements. As such, these expenditures may not appear on this website.

Unaudited data is updated quarterly for all payees with combined spending of $25,000 or more. When cumulative payee spending exceeds $25,000 threshold, all payments made during the Fiscal Year will be reported. Datasets, current and up to seven prior fiscal periods, will be available for your search by Fiscal Year. The following information will be displayed: Payee Name, County Agency Name, Payee Zip Code, Amount and Payment Description. Website options include: sorting, exporting data, creating graphs, and customizing your display format - among other features. There is an online tutorial.

If you have any questions or comments about this citizen portal site, please send an email at any time to: CountyClick311@co.pg.md.us, or call 3-1-1 (301-883-4748), Monday - Friday, 7am - 7pm, and a Customer Service Representative will be glad to assist you.
```

</details>

#### [19] `opendata.maryland.gov` · dataset `5dkb-uymf` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `471d9dc0874711b1`
- Rule fired: `exfiltration ('Email' … 'Email' → 'GIS@mdot.state.md.us')`
- Source: <https://opendata.maryland.gov/d/5dkb-uymf>
- Why it is a false positive: Same MDOT boilerplate as [13] on the roadway-maintenance dataset.

<details><summary>Verbatim (2,982 characters) — click to expand</summary>

```text
Roadway Maintenance Responsibility data consists of linear geometric features which specifically show the government agencies responsible for maintain roadways throughout the State of Maryland. Roadway Maintenance Responsibility data is primarily used for general planning and road maintenance coordination purposes, and for Federal Highway Administration (FHWA) Highway Performance Monitoring System (HPMS) annual submission & coordination. The Maryland Department of Transportation State Highway Administration (MDOT SHA) currently reports this data only on the ing publicinventory direction (generally North or East) side of the roadway. Roadway Maintenance Responsibility data is not a complete representation of all roadway geometry. Roadway Maintenance Responsibility data is developed as part of the Highway Performance Monitoring System (HPMS) which maintains and reports transportation related information to the Federal Highway Administration (FHWA) on an annual basis. HPMS is maintained by the Maryland Department of Transportation State Highway Administration (MDOT SHA), under the Office of Planning and Preliminary Engineering (OPPE) Data Services Division (DSD). Roadway Maintenance Responsibility data is used by various business units throughout MDOT, as well as many other Federal, State and local government agencies. Roadway Maintenance Responsibility data is key to understanding which government agenices are responsible for maintaining public roadways throughout the State of Maryland. Roadway Maintenance Responsibility data is updated and published on an annual basis for the prior year. This data is for the year 2017. View the most current Roadway Maintenance Responsibility data in the Maryland Know Your Roads Application. For additional information, contact the MDOT SHA Geospatial Technologies Email: GIS@mdot.state.md.us For additional information related to the Maryland Department of Transportation (MDOT) Website: https://www.mdot.maryland.gov/ For additional information related to the Maryland Department of Transportation State Highway Administration (MDOT SHA): Website: https://roads.maryland.gov/Home.aspx MDOT SHA Geospatial Data Legal Disclaimer: The Maryland Department of Transportation State Highway Administration (MDOT SHA) makes no warranty, expressed or implied, as to the use or appropriateness of geospatial data, and there are no warranties of merchantability or fitness for a particular purpose or use. The information contained in geospatial data is from publicly available sources, but no representation is made as to the accuracy or completeness of geospatial data. MDOT SHA shall not be subject to liability for human error, error due to software conversion, defect, or failure of machines, or any material used in the connection with the machines, including tapes, disks, CD-ROMs or DVD-ROMs and energy. MDOT SHA shall not be liable for any lost profits, consequential damages, or claims against MDOT SHA by third parties.
```

</details>

#### [20] `data.cityofchicago.org` · dataset `5n77-2d6a` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `e1933a6d582c78c8`
- Rule fired: `exfiltration ('copy' … 'token' → 'https://forms.office.com/Pages/DesignPageV2.aspx?subpage=design&token=bfa6889e0f674cd6a4f1fedccb402c8d&wdlor=cF4F6C0D3-9163-45CB-A834-4D4CA5D9F255&id=qc02cC0GUUGBRJfdxW5wJ2WUSmVcTNRNtAgDSPV9FxxUMUMyUDQ5RUw1WTRSTDdNRlY2U1lCVUhDVy4u&analysis=false">this')`
- Source: <https://data.cityofchicago.org/d/5n77-2d6a>
- Why it is a false positive: *“A **copy** of the original survey is at …”* where the link is a Microsoft Forms URL containing a `&token=…` query parameter. The sensitive object is a **URL query-string key**, not a credential.

<details><summary>Verbatim (1,241 characters) — click to expand</summary>

```text
In association with the November 2022 process for 12th ward residents to apply for the opportunity to fill the aldermanic vacancy in that ward, residents were also invited to fill out an online survey, seeking their opinions on issues. The results of that survey are shown in this dataset.

Respondents were presented with seven issues and asked to rank them from most urgent to least urgent.

The final question was free text, intended to capture other issues but if the respondent provided other text, it is included.

Please note that the survey is not and was not intended to be a random sample or otherwise scientifically or statistically valid. There were no formal barriers to people not residents of the 12th ward responding, people responding more than once, or other things of that nature. It was intended only as a simple tool to collect such information as people cared to submit and should be interpreted in that spirit.

A copy of the original survey is at <a href="https://forms.office.com/Pages/DesignPageV2.aspx?subpage=design&token=bfa6889e0f674cd6a4f1fedccb402c8d&wdlor=cF4F6C0D3-9163-45CB-A834-4D4CA5D9F255&id=qc02cC0GUUGBRJfdxW5wJ2WUSmVcTNRNtAgDSPV9FxxUMUMyUDQ5RUw1WTRSTDdNRlY2U1lCVUhDVy4u&analysis=false">this link</a>.
```

</details>

#### [21] `data.cityofnewyork.us` · dataset `5tub-eh45` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `97c1308d1783bfed`
- Rule fired: `exfiltration ('email' … 'contents of' → 'https://app.powerbigov.us/view?r=eyJrIjoiMGIxY2IxMTEtMTBlOS00NGUxLTgyYzMtMTFkMGQ5MmZiMmJjIiwidCI6IjMyZjU2ZmM3LTVmODEtNGUyMi1hOTViLTE1ZGE2NjUxM2JlZiJ9">Drivers')`
- Source: <https://data.cityofnewyork.us/d/5tub-eh45>
- Why it is a false positive: *“For inquiries about the **contents of** this dataset, please **email** licensinginquiries@tlc.nyc.gov”*.

<details><summary>Verbatim (741 characters) — click to expand</summary>

```text
PLEASE NOTE: This dataset of all TLC licensed street hail livery (SHL) drivers in good standing is updated daily between 4–7 PM. Check the “Last Update Date” to confirm it shows today’s or yesterday’s date. If it’s older, find the latest data here: <a href="https://app.powerbigov.us/view?r=eyJrIjoiMGIxY2IxMTEtMTBlOS00NGUxLTgyYzMtMTFkMGQ5MmZiMmJjIiwidCI6IjMyZjU2ZmM3LTVmODEtNGUyMi1hOTViLTE1ZGE2NjUxM2JlZiJ9">Drivers List</a>

NYC TLC Licensed Street Hail Livery drivers that are currently active and in good standing and able to drive. This list is accurate to the date and time represented in the Last Date Updated and Last Time Updated fields. For inquiries about the contents of this dataset, please email licensinginquiries@tlc.nyc.gov.
```

</details>

#### [22] `data.cityofberkeley.info` · dataset `5vy5-rwja` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `ff9f5917cfa6f570`
- Rule fired: `exfiltration ('email' … 'email' → 'BESO@BerkeleyCA.gov')`
- Source: <https://data.cityofberkeley.info/d/5vy5-rwja>
- Why it is a false positive: *“If the status for your property is incorrect, **email** BESO@BerkeleyCA.gov”*.

Verbatim:

```text
This dataset contains the compliance status and reported energy metrics of medium and large buildings (greater than 15,000 square feet) subject to BESO's energy benchmarking and assessment requirement. If the status for your property is incorrect, email BESO@BerkeleyCA.gov. For more information about the requirements for medium and large buildings, please visit: www.berkeleyca.gov/BESO
```

#### [23] `data.edmonton.ca` · dataset `66kp-sqm8` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `6027ce07d3406523`
- Rule fired: `exfiltration ('forward' … 'records' → 'https://www.edmonton.ca/city_government/documents/RoadsTraffic/City-wide_Flood_Mitigation_Study.pdf')`
- Source: <https://data.edmonton.ca/d/66kp-sqm8>
- Why it is a false positive: Sibling of [11] — the same Edmonton flood-study boilerplate on a second depth layer.

<details><summary>Verbatim (4,000 characters) — click to expand</summary>

```text
This spatial data represents the drainage infrastructure that exists at a depth between 1.5 m and 2.5 m below ground.  The colour assigned to this is data is Orange.

This spatial data was created as a result of a 2016 study, using 2014 data, done for the Edmonton area to determine the vulnerable drainage and sewage areas of Edmonton in regards to a 1 in 100 year rainfall event.

Due to the constant changing of subsurface infrastructure (adding, upgrading, etc.) combined with the constant changing definition of a 1 in 100 year rainfall event (based on historic rainfall amounts), this raster file reflects the results of a study done in 2016 and should neither suggest previous year’s vulnerabilities nor future year’s vulnerabilities.

For a more regional Edmonton area breakdown of the Study’s results: 

https://www.edmonton.ca/city_government/documents/RoadsTraffic/City-wide_Flood_Mitigation_Study.pdf

There are three different colour to the vulnerability of the roadways and the corresponding ponding depth that would occur for that area during a large rainstorm.

Those colours are:

Green (representing the depth from surface that sanitary flows can surcharge from less than 2.5 m)
Yellow (representing the depth from surface that sanitary flows can surcharge from 1.5 to 2.5 m)
Red (representing the depth from surface that sanitary flows can surcharge from greater than 1.5 m)

This Raster file is best viewed overlaid with the 2016 Flood Mitigation Study - Drainage and Sanitation Surcharge Map; as the various coloured areas follow the subsurface infrastructure (and the corresponding roadways if you are also viewing the street map as a layer).

Disclaimer: No Warranty with Flood Risk Maps.
Your use of the flood risk maps is solely at your own risk, and you are fully responsible for any consequences arising from your use of the flood risk maps. The flood risk maps are provided on an “as is” and “as available” basis, and you agree to use them solely at your own risk. There are no warranties, expressed or implied in respect to the flood risk maps or your use of them, including without limitation, implied warranties and conditions of merchantability and fitness for any particular purpose.

Please note that the flood risk maps have been modified from their original source, and that all data visualization on maps are approximate and include only records that can be mapped.

This dataset is based on 2014 information and will not be updated further. The model is based on a theoretical, worst-case scenario storm that has never occurred in the Edmonton area.

Model Accuracy:

The LiDar used was a 5 meter grid system.  LiDar has an accuracy of ? cm horizontally/vertically.  Bare Earth LiDar was used in for this model surface.  
This is a spline fit interpolations model.  This is a 1D-1D model with 2D interpolations.The accuracy of the information provided in these data sets is plus or minus 10 cm vertically, and 10 cm horizontally.   

The 100 year flood was based on the 2015 Edmonton 4 year Chicago storm event over 20 plus neighbourhoods.  The data is a collection of the worst case scenario of model runs.  

This is a common practice for Edmonton drainage models.  These models are high level concept and projects determined from this data set will undergo finer, more detailed modeling.

These maps are a visual representation and intended to be used when prioritization of the best engineering solutions that are scheduled to be brought forward to Utility Council to mitigate future flooding in the City.  The best engineering solutions are high level concept designs and require further modeling and design.  At the time of the PDF release, November 9, 2016 there was no funding for any projects to be completed or for further design.  Strategy will be brought forward to Utility Committee on June 7, 2017.  Council will be determining funding and rate of project completion.  
The Storm size used in these models are l
```

</details>

#### [24] `datahub.transportation.gov` · dataset `69qe-yiui` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `5f5002d643ff1fd6`
- Rule fired: `exfiltration ('Export' … 'API Key' → 'https://github.com/usdot-jpo-ode/wzdx/tree/develophttps:/github.com/usdot-jpo-ode/wzdx/tree/develop/schemas/schemas">GitHub')`
- Source: <https://datahub.transportation.gov/d/69qe-yiui>
- Why it is a false positive: The closest call in the study. It is genuinely documentation about **exporting data to an API endpoint using an API key**: *“the ‘**Export**’ button… access the **API** endpoint… create their own **API access key**”* with GitHub schema URLs. Shaped exactly like exfiltration prose; obviously benign to a human.

<details><summary>Verbatim (3,366 characters) — click to expand</summary>

```text
This dataset contains the up-to-date metadata on Work Zone feeds that meet the Work Zone Data Exchange (WZDx) specification or Connected Work Zone (CWZ) Standard and are registered with USDOT ITS DataHub. The current work zone data from each feed can be accessed through their respective API links. 

To access the Work Zone Data Feed Registry’s list of current work zone data feeds, click the “Data” tab to view current data or the “Export” button to download as a CSV or access the API endpoint.

Some links provide direct access, while others require a user to create their own API access key for authentication. Please see the API Key Instructions document linked in the About this Dataset > Attachments section to learn how to sign up for API keys for feeds.

<b>Data Schemas</b>
The WZDx Feed Registry lists feeds following the WZDx Specification and CWZ Standard, published by ITE. JSON schemas for the WZDx Specification version 2.0 and later are available on the specification’s <a href="https://github.com/usdot-jpo-ode/wzdx/tree/develophttps:/github.com/usdot-jpo-ode/wzdx/tree/develop/schemas/schemas">GitHub repository</a>. JSON schemas for the CWZ Standard are available on the standard’s <a href="https://github.com/ite-org/cwz/tree/main/schemas">GitHub repository</a>.

<b>Registry Updates</b>
The dataset changelog captures all changes to the Work Zone Data Feed Registry, including addition of new feeds, updates to existing feeds, or removal of old or unmaintained feeds.

New feeds are added periodically to the Feed Registry periodically. They appear as new lines in the “Data” table and are logged in the dataset changelog (starting February 2025). If you have a WZDx or CWZ feed that you would like to add to the Feed Registry, please email the dataset point of contact listed below.

When organizations update their feeds to use a new specification version, to a new URL, or to require user authentication with an API key, the Feed Registry will create a new entry in the dataset with the feed’s new information and assign an end date to the current listing, signifying the end of that feed’s support. When the end date passes, the old feed information will be removed from the Feed Registry and the removal will be logged in the dataset changelog. 

If a feed listed on the registry is no longer maintained by the dataset owner – typically evident by the feed being offline for an extended period of time or the data in the feed being significantly out of date –  the feed will be removed from the Feed Registry and the removal will be logged in the dataset changelog.

Report any errors in the Feed Registry by emailing the dataset point of contact.

<b>Work Zone Data Archive</b>
The ITS JPO has archived work zone data collections from 23 states covering various parts of the time period from 10/2019 to 08/2024 depending on when the feed was active. The data is split into two archives: raw data and processed data.  The raw data contains the collection of .json or .geojson files exactly as they were on the individual state’s WZDx feed at the time of collection. The processed data is organized by work zone, so that as information about the work zone changed through feed updates they would be collected in a single file for that work zone. To request access fill out the form <a href="https://its.dot.gov/data/data-request">here</a>.
```

</details>


### Class B — second-person product guidance (1 of 24)

#### [9] `opendata.maryland.gov` · dataset `3iva-5cca` · dataset-level description

- **Verdict: FALSE POSITIVE** · signals `tool-poisoning` · score 2 · sha256 `d3f04de451318c8c`
- Rule fired: `tool-poisoning ('use the tool')`
- Source: <https://opendata.maryland.gov/d/3iva-5cca>
- Why it is a false positive: Second-person product guidance aimed at a **human**: *“You can **use the tool** to find proposed projects near you…”*. `_READER_DIRECTED_RE` matches *you*, `_TOOL_POISON_RE` matches *use the tool*, and the pair scores 2.

Verbatim:

```text
This tool makes it easier to explore environmental permits that may affect your area. It includes applications for projects regulated under state law, such as landfills, incinerators, industrial and municipal water discharges, sewage sludge use, and the handling of hazardous substances. You can use the tool to find proposed projects near you, check the status of applications, see upcoming public meetings or hearings, and learn how to get involved in the review process by submitting comments or attending hearings. If you need help or can’t find what you’re looking for, call us at 410-537-3000.
```


### Class C — an example email address inside a column or macro doc (2 of 24)

#### [1] `pvcy/dbt-privacy` @ `4b2092ea09` · `macros/docs/mask_email.yml#mask_email`

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `ab8a3dbad5c682be`
- Rule fired: `exfiltration ('email' … 'email address' → 'personal@famouscelebrity.com')`
- Source: <https://github.com/pvcy/dbt-privacy/blob/4b2092ea09f63520052debbd5234804e281ea8d1/macros/docs/mask_email.yml>
- Why it is a false positive: Documentation for a PII-**masking** macro. `email` (a transfer verb in the rule's bank) co-occurs with `email address` and with the illustrative address `personal@famouscelebrity.com`, which the destination pattern reads as an external recipient. The most ironic flag in the study: a privacy tool's own docs.

Verbatim:

```text
Splits an email address into its address and domain parts. Will `safe_mask` the address and also `safe_mask` the domain, if there are fewer than `domain_n` records with that domain.
Returns `null` if `expr` is `null`, but does not return `null` if `expr` is not a valid email address (with no "@").
Note: Masking unique domains is important for protecting individuals with addresses like `personal@famouscelebrity.com`

```

#### [2] `snowplow/dbt-snowplow-media-player` @ `941a77f7c4` · `docs/markdown/snowplow_media_player_common_cols.md#col_user_id`

- **Verdict: FALSE POSITIVE** · signals `data-exfiltration` · score 2 · sha256 `a08e601521b1f887`
- Rule fired: `exfiltration ('email' … 'email' → 'jon.doe@email.com')`
- Source: <https://github.com/snowplow/dbt-snowplow-media-player/blob/941a77f7c4792d1397e40370c4c40553d7a123ab/docs/markdown/snowplow_media_player_common_cols.md>
- Why it is a false positive: A 52-character `{% docs %}` block that dbt resolves into the `user_id` column description, and whose only sin is an example value. This is the shortest flag in the corpus and the cheapest to trigger — one example address in one column doc is enough.

Verbatim:

```text

Unique ID set by business e.g. ‘jon.doe@email.com’

```


---

## What this study does *not* establish

Stated plainly, because the point of the exercise was calibration:

1. **It is not a production catalog.** Open-data portals and public dbt projects are public
   by construction. An enterprise catalog contains vendor-integration docs, runbooks, incident
   notes and PII handling instructions — prose that is *closer* to the detector's signature
   bank than anything measured here. The true enterprise rate is plausibly **higher** than
   0.063 %, not lower.
2. **A third of the corpus is not English.** The English-like subset is 25,565 of 38,031
   (67 %); the largest single portal, `www.datos.gov.co`, is Spanish. Antigen's detector is an
   English-language rule, so non-English text is clean for free. The English-only rate is
   **0.094 %**, and that is the more honest headline for an English-speaking deployment. It is
   printed alongside the main number by the script for exactly that reason.
3. **It measures precision, not recall.** No injected payloads were planted in this corpus, so
   it says nothing about what the detector misses. The known misses (base64 indirection,
   character spacing, the bare plural `emails`, non-English payloads, full TR39 confusables)
   are documented in `README.md` *Honest limitations* and are unaffected by this study.
4. **Socrata truncates.** The Discovery API returns dataset descriptions capped at 4,000
   characters; two flagged items ([11] and [23]) hit that ceiling. Since the flag rate rises
   with length, truncation can only have *lowered* the measured rate.
5. **De-duplication is by exact string.** Near-duplicates (the same boilerplate with one word
   changed) are counted separately, which inflates the denominator slightly. Items [5]/[18]
   and [13]/[19] and [11]/[23] are examples that survived de-duplication as distinct strings.
6. **Search ranking is not stable, but the corpus is.** Re-running discovery months from now
   will return a different repository list. That is why the manifest pins every repository to a
   commit SHA and every description to a sha256: the *exact* corpus behind this number is
   reproducible even though the query that found it is not.
7. **No detector bug was found.** Every one of the 24 flags is the documented rule behaving as
   designed. The finding is about the rule's *shape* — whole-field co-occurrence with no
   proximity requirement — not about a defect in its implementation. Nothing in `antigen/` was
   changed by this study.

## Reproducing this

```bash
# 1. Harvest (network). Caches to scripts/.fp_corpus_cache/. Respects rate limits;
#    the dbt source needs an authenticated `gh` CLI or GITHUB_TOKEN, plus PyYAML.
python scripts/fp_corpus.py harvest --dbt-repos 220 --socrata-datasets 6000

# 2. Detect + report (offline, stdlib only)
python scripts/fp_corpus.py run
python scripts/fp_corpus.py report      # rewrites docs/fp-corpus-manifest.json + hashes

# or all three at once, reusing any cache that already exists
python scripts/fp_corpus.py all
```

The run that produced this document took about an hour of wall-clock time (the two sources
were harvested in parallel), almost all of it spent downloading 200 repository tarballs and
scrolling 60 pages of the Socrata API. Detection over all 38,031 strings takes a few seconds.

## Licensing and redistribution

The harvested text is **not redistributed in this repository**. `docs/fp-corpus-manifest.json`
carries provenance (repository + commit SHA + SPDX license, or portal domain + dataset id) and
`docs/fp-corpus-hashes.txt` carries a truncated sha256 per description, so the corpus can be
re-derived and verified byte-for-byte without this repo republishing anyone's content. The
only text quoted in full anywhere in this repo is the 24 flagged strings, quoted here and in
the manifest as evidence for the verdicts.

- **dbt sources.** 148 repositories: 33 Apache-2.0, 21 MIT, 5 GPL-3.0, and 89 with no license
  declared (`NOASSERTION`). Undeclared-license repositories are exactly why the raw corpus is
  not committed — every repository, its owner, its license and its pinned commit is listed in
  the manifest so attribution is traceable per item.
- **Socrata portals.** Descriptions are the metadata of public open-data datasets published by
  government agencies; individual portals carry their own terms (most US municipal portals are
  public domain or CC-BY). Portal domain and dataset id are recorded for every item, and each
  flagged item links to its canonical dataset page.
- The Antigen authors wrote **none** of the corpus.

## Where this leaves the claim

The number is small and it is real: **24 flags in 38,031 external descriptions, all of them
false positives, none of them a detector bug.** For a nightly read-only sweep over a
small-to-medium catalog — the shape `examples/ci/metadata-injection-scan.yml` actually
delivers — a handful of flags per 10,000 fields is an affordable review queue.

The number that should change behaviour is the conditional one: **4.7 % on descriptions over
2,000 characters**, i.e. the long, curated, expensive ones. Combined with the fact that
`cure` replaces a flagged field wholesale outside the demo corpus, this is the empirical case
for the gates the tool already has — dry-run by default, `--apply` required, `--max-mutations`
as a circuit breaker, and a human reading the plan.

"""seed_catalog.py — create the clean `ecommerce` catalog Antigen is demonstrated on.

This is ENVIRONMENT SETUP, not part of the product: it builds the pristine catalog
that `seed_corpus.py` then poisons. Everything written here is benign, realistic
metadata — no payloads, no Antigen tags, no hashes.

Run order for a live demo on a fresh `datahub docker quickstart`:

    python seed_catalog.py      # 1. clean ecommerce catalog (this file)
    python -m antigen.register_properties   # 2. structured-property definitions
    python seed_corpus.py       # 3. plant the attack corpus
    python -m antigen cure --dry-run   # 4. preview every write (live default)
    python -m antigen demo --apply     # 5. sweep -> defuse -> prove (mutates; --apply
                                       #    is REQUIRED against a live catalog)
    python verify.py --live            # 6. the reproducible proof

Why it exists: DataHub's own `ingest-sample-data` ships ~7 unrelated Hive/HDFS
datasets, none of which carry the columns the corpus targets
(`shipments.recipient_email`, `returns.status`). Re-homing payloads onto whatever
sample entities happen to exist also lands them on `dataFlow`/`corpuser` URNs, which
DataHub's `update_description` rejects outright ("Unsupported resource type").

Uses base `acryl-datahub` emits — the same category as the structured-property
definitions, and deliberately NOT part of the 9-agent-tool surface Antigen is
grounded on.

`--scale N` appends N extra CLEAN padding datasets on top of the 13 above. It exists
for one reason: the live GMS clamps `search` to 50 rows per page, so a 13-dataset
catalog never leaves page one and the paging loop in `SdkGateway._paged_urns` is
never exercised against a real server. `python seed_catalog.py --scale 60` pushes the
catalog past that cap so the loop has to page. The padding carries no payloads and no
Antigen tags; it changes nothing about detection, only the size of the enumeration.
"""

from __future__ import annotations

import argparse
import os

PLATFORM_DATASETS: list[tuple[str, str, str, list[tuple[str, str, str]]]] = [
    # (platform, name, description, [(field, type, field description)])
    ("snowflake", "ecommerce.public.customers",
     "Master customer record, one row per registered account.",
     [("customer_id", "NUMBER", "Surrogate key for the customer."),
      ("email", "VARCHAR", "Primary contact email address."),
      ("country", "VARCHAR", "ISO-3166 country of residence."),
      ("created_at", "TIMESTAMP", "Account creation timestamp, UTC.")]),
    ("snowflake", "ecommerce.public.orders",
     "One row per placed order, including cancelled orders.",
     [("order_id", "NUMBER", "Surrogate key for the order."),
      ("customer_id", "NUMBER", "FK to ecommerce.public.customers."),
      ("order_total", "NUMBER", "Order gross total in minor units."),
      ("placed_at", "TIMESTAMP", "Order placement timestamp, UTC.")]),
    ("snowflake", "ecommerce.public.payments",
     "Settled and failed payment attempts against orders.",
     [("payment_id", "NUMBER", "Surrogate key for the payment attempt."),
      ("order_id", "NUMBER", "FK to ecommerce.public.orders."),
      ("amount", "NUMBER", "Captured amount in minor units."),
      ("status", "VARCHAR", "Gateway settlement status.")]),
    ("snowflake", "ecommerce.public.products",
     "Sellable product catalogue with current list pricing.",
     [("product_id", "NUMBER", "Surrogate key for the product."),
      ("sku", "VARCHAR", "Stock keeping unit code."),
      ("list_price", "NUMBER", "Current list price in minor units.")]),
    ("snowflake", "ecommerce.public.shipments",
     "Outbound shipments and their carrier tracking state.",
     [("shipment_id", "NUMBER", "Surrogate key for the shipment."),
      ("order_id", "NUMBER", "FK to ecommerce.public.orders."),
      # Column-locus payload target #1.
      ("recipient_email", "VARCHAR", "Delivery notification address."),
      ("carrier", "VARCHAR", "Fulfilment carrier name.")]),
    ("snowflake", "ecommerce.public.returns",
     "Customer-initiated returns and their disposition.",
     [("return_id", "NUMBER", "Surrogate key for the return."),
      ("order_id", "NUMBER", "FK to ecommerce.public.orders."),
      # Column-locus payload target #2.
      ("status", "VARCHAR", "Current return disposition."),
      ("refund_amount", "NUMBER", "Refunded amount in minor units.")]),
    ("postgres", "ecommerce.public.sessions",
     "Web and app session events for logged-in and anonymous visitors.",
     [("session_id", "VARCHAR", "Session identifier."),
      ("customer_id", "NUMBER", "FK to customers; null when anonymous."),
      ("started_at", "TIMESTAMP", "Session start timestamp, UTC.")]),
    ("postgres", "ecommerce.public.support_tickets",
     "Support tickets raised by customers, with resolution state.",
     [("ticket_id", "NUMBER", "Surrogate key for the ticket."),
      ("customer_id", "NUMBER", "FK to ecommerce.public.customers."),
      ("subject", "VARCHAR", "Customer-supplied ticket subject.")]),
    ("dbt", "ecommerce.analytics.daily_revenue",
     "Daily gross and net revenue, modelled from orders and payments.",
     [("revenue_date", "DATE", "Calendar date, UTC."),
      ("gross_revenue", "NUMBER", "Gross revenue in minor units."),
      ("net_revenue", "NUMBER", "Net of refunds, in minor units.")]),
    ("looker", "ecommerce.marketing.campaigns",
     "Marketing campaign performance rollup used by the growth team.",
     [("campaign_id", "VARCHAR", "Campaign identifier."),
      ("spend", "NUMBER", "Campaign spend in minor units."),
      ("attributed_revenue", "NUMBER", "Revenue attributed to the campaign.")]),
    # --- held-out injection targets (H01-H03) ------------------------------ #
    # The held-out set is planted on these; without them the seeder re-homes onto
    # whatever exists (mlFeature/corpGroup URNs), which is not a catalog surface an
    # analyst agent would ever read.
    ("snowflake", "ecommerce.public.inventory",
     "Per-warehouse stock levels, refreshed hourly.",
     [("sku", "VARCHAR", "Stock keeping unit code."),
      ("warehouse_id", "VARCHAR", "Fulfilment warehouse identifier."),
      ("on_hand", "NUMBER", "Units currently on hand.")]),
    ("postgres", "ecommerce.public.reviews",
     "Customer product reviews, including free-text bodies.",
     [("review_id", "NUMBER", "Surrogate key for the review."),
      ("product_id", "NUMBER", "FK to ecommerce.public.products."),
      ("body", "VARCHAR", "Customer-supplied review text.")]),
    ("s3", "ecommerce.raw.events",
     "Raw clickstream event landing zone, partitioned by ingest date.",
     [("event_id", "VARCHAR", "Event identifier."),
      ("event_type", "VARCHAR", "Event category."),
      ("payload", "VARCHAR", "Raw event body as JSON.")]),
]

#: (upstream, downstream) — gives `blast_radius` real consumers to walk.
LINEAGE: list[tuple[tuple[str, str], tuple[str, str]]] = [
    (("snowflake", "ecommerce.public.orders"), ("dbt", "ecommerce.analytics.daily_revenue")),
    (("snowflake", "ecommerce.public.payments"), ("dbt", "ecommerce.analytics.daily_revenue")),
    (("snowflake", "ecommerce.public.returns"), ("dbt", "ecommerce.analytics.daily_revenue")),
    (("dbt", "ecommerce.analytics.daily_revenue"), ("looker", "ecommerce.marketing.campaigns")),
    (("postgres", "ecommerce.public.sessions"), ("looker", "ecommerce.marketing.campaigns")),
    (("snowflake", "ecommerce.public.customers"), ("snowflake", "ecommerce.public.orders")),
]


#: Description carried by every `--scale` padding dataset. Deliberately self-describing:
#: anyone reading the catalog (or the transcript) can see these are enumeration padding,
#: not part of the demonstrated corpus.
PADDING_DESCRIPTION = (
    "Synthetic padding dataset. Clean — carries no payload and no Antigen tag. Exists "
    "only to push the catalog past the live GMS's 50-row `search` page so the paging "
    "loop in SdkGateway._paged_urns runs against a real server."
)


def padding_datasets(count: int) -> list[tuple[str, str, str, list[tuple[str, str, str]]]]:
    """N clean filler datasets, shaped exactly like the real ones."""
    return [
        ("snowflake", f"ecommerce.scale.padding_{i:03d}", PADDING_DESCRIPTION,
         [("row_id", "NUMBER", "Synthetic surrogate key."),
          ("value", "VARCHAR", "Synthetic value column.")])
        for i in range(1, count + 1)
    ]


def _urn(platform: str, name: str) -> str:
    from datahub.emitter.mce_builder import make_dataset_urn
    return make_dataset_urn(platform=platform, name=name, env="PROD")


def seed(verbose: bool = True, scale: int = 0) -> list[str]:
    """Emit the clean catalog. Idempotent — re-running overwrites in place.

    `scale` appends that many clean padding datasets (see `padding_datasets`).
    """
    from datahub.emitter.mcp import MetadataChangeProposalWrapper
    from datahub.ingestion.graph.client import DatahubClientConfig, DataHubGraph
    from datahub.metadata.schema_classes import (
        AuditStampClass,
        DatasetLineageTypeClass,
        DatasetPropertiesClass,
        NumberTypeClass,
        OtherSchemaClass,
        SchemaFieldClass,
        SchemaFieldDataTypeClass,
        SchemaMetadataClass,
        StringTypeClass,
        UpstreamClass,
        UpstreamLineageClass,
    )

    graph = DataHubGraph(DatahubClientConfig(
        server=os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080"),
        token=os.environ.get("DATAHUB_GMS_TOKEN") or None,
    ))
    stamp = AuditStampClass(time=0, actor="urn:li:corpuser:datahub")
    created: list[str] = []

    padding = padding_datasets(scale)
    padding_names = {name for _, name, _, _ in padding}

    for platform, name, description, fields in PLATFORM_DATASETS + padding:
        urn = _urn(platform, name)
        graph.emit(MetadataChangeProposalWrapper(
            entityUrn=urn,
            aspect=DatasetPropertiesClass(name=name.split(".")[-1],
                                          qualifiedName=name,
                                          description=description),
        ))
        graph.emit(MetadataChangeProposalWrapper(
            entityUrn=urn,
            aspect=SchemaMetadataClass(
                schemaName=name, platform=f"urn:li:dataPlatform:{platform}",
                version=0, hash="", created=stamp, lastModified=stamp,
                platformSchema=OtherSchemaClass(rawSchema=""),
                fields=[
                    SchemaFieldClass(
                        fieldPath=f,
                        type=SchemaFieldDataTypeClass(
                            type=NumberTypeClass() if t == "NUMBER"
                            else StringTypeClass()),
                        nativeDataType=t,
                        description=d,
                    ) for f, t, d in fields
                ],
            ),
        ))
        created.append(urn)
        if verbose and name not in padding_names:
            print(f"  + {name}  ({len(fields)} columns)")
    if verbose and padding:
        print(f"  + {len(padding)} clean padding datasets "
              f"(ecommerce.scale.padding_001 … _{len(padding):03d})")

    downstreams: dict[str, list[str]] = {}
    for up, down in LINEAGE:
        downstreams.setdefault(_urn(*down), []).append(_urn(*up))
    for down_urn, up_urns in downstreams.items():
        graph.emit(MetadataChangeProposalWrapper(
            entityUrn=down_urn,
            aspect=UpstreamLineageClass(upstreams=[
                UpstreamClass(dataset=u, type=DatasetLineageTypeClass.TRANSFORMED)
                for u in up_urns
            ]),
        ))
    if verbose:
        print(f"  + lineage edges: {len(LINEAGE)}")
    return created


def await_indexed(expected: int, timeout_s: int = 120, verbose: bool = True) -> int:
    """Block until `search` can see the datasets we just emitted.

    Writes go to MySQL immediately but reach the OpenSearch index asynchronously.
    `seed_corpus.py` enumerates targets with `search`, so running it too early makes
    the planted payloads re-home onto whatever happens to be indexed — on a fresh
    instance that is `urn:li:corpuser:datahub`, which `update_description` rejects as
    an unsupported resource type. Waiting here keeps the demo deterministic.
    """
    import time

    from antigen.gateway import SdkGateway

    gw = SdkGateway()
    deadline = time.time() + timeout_s
    seen = 0
    while time.time() < deadline:
        seen = sum(1 for u in gw.search_all() if u.startswith("urn:li:dataset:"))
        if seen >= expected:
            if verbose:
                print(f"  search index caught up: {seen} datasets visible")
            return seen
        time.sleep(3)
    print(f"  WARNING: only {seen}/{expected} datasets indexed after {timeout_s}s; "
          f"seed_corpus.py may re-home payloads.")
    return seen


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scale", type=int, default=0, metavar="N",
                    help="append N extra CLEAN padding datasets, to push the catalog "
                         "past the GMS's 50-row search page and exercise paging live")
    args = ap.parse_args(argv)
    print(f"Seeding clean ecommerce catalog into "
          f"{os.environ.get('DATAHUB_GMS_URL', 'http://localhost:8080')}")
    urns = seed(scale=args.scale)
    # Indexing is asynchronous and roughly linear in catalog size; 13 datasets settle
    # well inside 120 s, a --scale run needs longer.
    await_indexed(len(urns), timeout_s=max(120, 5 * len(urns)))
    print(f"\n{len(urns)} datasets created. Catalog is CLEAN "
          f"(no payloads — run seed_corpus.py next).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

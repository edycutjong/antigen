"""Seed the attack corpus into a graph, and build cure fixtures from it.

`build_corpus_gateway()` returns an `InMemoryGateway` populated exactly like a seeded
`showcase-ecommerce`: the 12 payloads (8 entity / 2 column / 2 doc), the 3 held-out
public injections, the 15 near-miss fields, plus clean filler entities and some
downstream lineage — so the full scan → cure → rescan → blast-radius pipeline runs
offline. `corpus_fixtures()` maps every payload to the original text the cure restores.

The live path (`seed_corpus.py`) plants the identical corpus into a real GMS via the
SDK gateway; this module is the deterministic offline twin used by tests and by
`verify.py` Part A when no Docker is present.
"""

from __future__ import annotations

from ._testkit import InMemoryGateway
from .corpus import HELD_OUT, PAYLOADS
from .corpus import Locus as CorpusLocus
from .cure import Fixture, Fixtures
from .gateway import Column, Document, Entity
from .nearmiss import NEAR_MISS

# Clean filler entities (benign prose) so the scan reports a real clean set.
_CLEAN_PROSE = [
    "Currency dimension: ISO-4217 codes and exchange rates by day.",
    "Store locations dimension with region and timezone.",
    "Promotion calendar: active campaigns and discount windows.",
    "Shipping carriers reference table with SLA tiers.",
    "Tax jurisdiction lookup keyed by postal code.",
    "Loyalty tier definitions and point thresholds.",
    "Warehouse capacity snapshots by facility.",
    "Category hierarchy for the product taxonomy.",
    "Employee roster for store staffing (HR-owned).",
    "Vendor master with procurement terms.",
]


def build_corpus_gateway() -> InMemoryGateway:
    gw = InMemoryGateway()

    # --- 12 authored payloads ------------------------------------------- #
    # Group column payloads by URN so an entity can carry a poisoned column
    # plus a benign base description.
    entity_desc_payloads = [p for p in PAYLOADS if p.locus is CorpusLocus.ENTITY_DESCRIPTION]
    column_payloads = [p for p in PAYLOADS if p.locus is CorpusLocus.COLUMN_DESCRIPTION]
    doc_payloads = [p for p in PAYLOADS if p.locus is CorpusLocus.KB_DOCUMENT]

    for p in entity_desc_payloads:
        gw.add_entity(Entity(urn=p.urn, description=p.poisoned_text))

    for p in column_payloads:
        assert p.field_path is not None  # invariant: column loci carry a field_path
        gw.add_entity(Entity(
            urn=p.urn,
            description="Fulfillment fact table for the ecommerce warehouse.",
            columns={p.field_path: Column(field_path=p.field_path,
                                          description=p.poisoned_text)},
        ))

    for p in doc_payloads:
        assert p.doc_title is not None  # invariant: doc loci carry a (parent, title)
        gw.add_document(Document(urn=p.urn, title=p.doc_title,
                                 content=p.poisoned_text, parent=p.doc_parent))

    # --- 3 held-out public injections (detection-only) ------------------ #
    for h in HELD_OUT:
        gw.add_entity(Entity(urn=h.urn, description=f"{h.original_text} {h.injection}"))

    # --- 15 near-miss (must scan clean) --------------------------------- #
    for n in NEAR_MISS:
        gw.add_entity(Entity(
            urn=f"urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.nearmiss.{n.id},PROD)",
            description=n.text,
        ))

    # --- clean filler --------------------------------------------------- #
    for i, prose in enumerate(_CLEAN_PROSE):
        gw.add_entity(Entity(
            urn=f"urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.clean.t{i:02d},PROD)",
            description=prose,
        ))

    # --- downstream lineage for blast-radius on a couple of poisoned URNs #
    # Downstream consumers exist as real entities so add_tags can land on them.
    customers = "urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.customers,PROD)"
    d_360 = "urn:li:dashboard:(looker,customer_360)"
    d_ltv = "urn:li:dataset:(urn:li:dataPlatform:dbt,ecommerce.analytics.customer_ltv,PROD)"
    d_exec = "urn:li:dashboard:(tableau,exec_revenue)"
    for urn, desc in [
        (d_360, "Customer 360 dashboard consuming the customers dimension."),
        (d_ltv, "Customer lifetime-value model built from customers and orders."),
        (d_exec, "Executive revenue dashboard."),
    ]:
        gw.add_entity(Entity(urn=urn, description=desc))
    gw.add_lineage(customers, [d_360, d_ltv])
    gw.add_lineage(d_ltv, [d_exec])
    return gw


def corpus_fixtures() -> Fixtures:
    fixtures: Fixtures = {}
    for p in PAYLOADS:
        key = (p.urn, p.field_path or "")
        fixtures[key] = Fixture(original_text=p.original_text,
                                payload_text=p.injection,
                                payload_id=p.id)
    return fixtures

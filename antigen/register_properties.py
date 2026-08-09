"""Register the three Antigen structured-property DEFINITIONS (one-time setup).

DataHub requires a structured-property *definition* (URN + value type + cardinality)
to exist before `add_structured_properties` can set a value. Definition creation is a
base `acryl-datahub` operation — NOT part of the Agent Context Kit tool surface — so
it is called directly here, not through `build_langchain_tools`. This is called out
explicitly so the "9 agent tools" grounding claim stays honest: this is one of the four
base-SDK calls the README names (`emit_mcp`, alongside `emit`/`exists` for tag-entity
creation and `get_aspect` for the editableSchemaMetadata overlay), and it is a setup
emit, not an agent tool.

Three definitions, using valid dotted identifiers (never hyphens):
    antigen.contentSha256   string   — tamper-evidence hash of the cleaned field
    antigen.payloadSha256   string   — irreversible hash of the removed payload
    antigen.lastScanned     string   — ISO timestamp of the last Antigen sweep
"""

from __future__ import annotations

#: Entity types the definitions are scoped to.
#:
#: These were `dataset` ONLY, which did not match what Antigen actually sweeps.
#: `SdkGateway.search_all` enumerates with a bare `query="*"` and no entity-type
#: filter, so `cure` and `certify` reach every free-text-carrying type the catalog
#: returns — the offline corpus alone certifies 26 datasets AND 2 dashboards, and a
#: poisoned dashboard description would have sent `add_structured_properties` at a
#: type the definition did not cover.
#:
#: The list is the set DataHub documents as carrying descriptions and supporting
#: Metadata Tests — Dataset, Dashboard, Chart, Data Flow, Data Job, Container.
#: Widening a definition costs nothing and cannot create a false positive; narrowing
#: the enumeration instead would silently stop sweeping types that really do carry
#: agent-readable text, which is the failure this project exists to prevent.
ENTITY_TYPES = [
    "urn:li:entityType:datahub.dataset",
    "urn:li:entityType:datahub.dashboard",
    "urn:li:entityType:datahub.chart",
    "urn:li:entityType:datahub.dataFlow",
    "urn:li:entityType:datahub.dataJob",
    "urn:li:entityType:datahub.container",
]

PROPERTY_DEFINITIONS = [
    {"qualified_name": "antigen.contentSha256", "value_type": "string",
     "cardinality": "SINGLE",
     "description": "SHA-256 of the cleaned field, for tamper-evidence rescan."},
    {"qualified_name": "antigen.payloadSha256", "value_type": "string",
     "cardinality": "SINGLE",
     "description": "Irreversible SHA-256 of the removed injection payload (forensic)."},
    {"qualified_name": "antigen.lastScanned", "value_type": "string",
     "cardinality": "SINGLE",
     "description": "ISO-8601 timestamp of the last Antigen sweep of this entity."},
]


def register_properties(client=None) -> list[str]:
    """Create the three property definitions against a live GMS.

    Uses `datahub.api.entities.structuredproperties.StructuredProperties` (base
    acryl-datahub). Returns the created URNs. Imported lazily so this module stays
    importable without the SDK (the definitions list above is used by tests/README).
    """
    import os

    from datahub.emitter.mce_builder import make_data_platform_urn  # noqa: F401  (sanity import)
    from datahub.ingestion.graph.client import DatahubClientConfig, DataHubGraph
    from datahub.metadata.schema_classes import (
        PropertyValueClass,  # noqa: F401
        StructuredPropertyDefinitionClass,
    )

    graph = DataHubGraph(DatahubClientConfig(
        server=os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080"),
        token=os.environ.get("DATAHUB_GMS_TOKEN"),
    ))

    created: list[str] = []
    for d in PROPERTY_DEFINITIONS:
        prop_urn = f"urn:li:structuredProperty:{d['qualified_name']}"
        definition = StructuredPropertyDefinitionClass(
            qualifiedName=d["qualified_name"],
            valueType="urn:li:dataType:datahub.string",
            cardinality=d["cardinality"],
            entityTypes=list(ENTITY_TYPES),
            description=d["description"],
        )
        graph.emit_mcp(_mcp(prop_urn, definition))
        created.append(prop_urn)
    return created


def _mcp(entity_urn: str, aspect):
    from datahub.emitter.mcp import MetadataChangeProposalWrapper
    return MetadataChangeProposalWrapper(entityUrn=entity_urn, aspect=aspect)


if __name__ == "__main__":  # pragma: no cover
    urns = register_properties()
    for u in urns:
        print(f"registered {u}")

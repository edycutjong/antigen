"""Which DataHub entity types each MUTATION tool can actually write.

Antigen enumerates with a bare `search(query="*")` and no entity-type restriction
(`gateway.SdkGateway.search_all`), and that is deliberate: narrowing the *enumeration*
is how a sweep silently stops looking at a type that really does carry agent-readable
text. It puts an obligation on the WRITE side instead — the tool surface does not
accept every type the sweep can hand it, and the three mutation tools do not agree
with each other about which ones they take.

**`update_description` is the one that bites.** DataHub's GraphQL resolver switches on
the target URN's entity type and throws for anything it does not name::

    // datahub-graphql-core/src/main/java/com/linkedin/datahub/graphql/
    //     resolvers/mutate/UpdateDescriptionResolver.java
    switch (targetUrn.getEntityType()) {
      case Constants.DATASET_ENTITY_NAME: ...
      ... 17 arms ...
      default:
        throw new RuntimeException(String.format(
            "Failed to update description. Unsupported resource type %s provided.",
            targetUrn));
    }

Seventeen arms, and `chart`, `dashboard`, `dataFlow`, `dataJob` and `corpuser` are not
among them — all five carry descriptions in the DataHub UI, and all five come back
from `search`. This is the finding Antigen filed upstream as
`datahub-project/datahub#19034`, which corrects the Agent Context Kit's own tool
docstring: the shipped text at `datahub_agent_context/mcp_tools/descriptions.py:144`
advertises the tool as "useful for documenting datasets, containers, charts,
dashboards, data flows, data jobs…", and the server rejects four of those six.

Before this module `cure` called `update_description` unconditionally, so the FIRST
poisoned dashboard on a real catalog raised out of the middle of the run — after
earlier loci had already been written — and the blanket handler in `cli.main` reported
that half-remediated catalog as exit 2, "nothing about the catalog was determined
either way". It had been determined, and written to.

**The other two mutation tools do NOT share that accept list**, which is why they are
tracked separately here rather than assumed to match it:

* `add_tags` → `batchAddTags` → `BatchAddTagsResolver`, which has no entity-type
  switch at all. It validates that the tag exists and that the resource exists
  (`LabelUtils.validateResource`), then emits a generic `globalTags` aspect — so it
  lands on every type whose entity-registry entry declares that aspect, and `chart`,
  `dashboard`, `dataFlow`, `dataJob` and `corpuser` all do. Tagging is therefore
  available on exactly the types where describing is not, which is what makes
  containment (see `cure.cure`) a real action rather than an apology.
* `add_structured_properties` → `upsertStructuredProperties`, likewise type-agnostic
  at the resolver but gated by the *definition*'s `entityTypes` list — and that list
  is ours, in `register_properties.ENTITY_TYPES`. So it is READ FROM THERE rather than
  duplicated: widening the definition automatically widens what Antigen will stamp,
  and the two can never drift apart.

The consequence for `cure` is in `cure.cure`: a locus whose type cannot take an
`update_description` is CONTAINED, not cured — tagged `injection-contained`, stamped,
and given a forensic record, with the payload still live in the field and said so out
loud in the summary, the exit code and the incident record.
"""

from __future__ import annotations

from .register_properties import ENTITY_TYPES as _PROPERTY_ENTITY_TYPES

#: Prefix of the entity-type URNs a structured-property definition is scoped to.
_ENTITY_TYPE_URN_PREFIX = "urn:li:entityType:datahub."

#: The 17 `case` arms of `UpdateDescriptionResolver` (see the module docstring).
#: Anything outside this set reaches the resolver's `default:` and raises
#: "Failed to update description. Unsupported resource type <urn> provided."
UPDATE_DESCRIPTION_TYPES = frozenset({
    "dataset", "container", "domain", "glossaryTerm", "glossaryNode", "tag",
    "corpGroup", "notebook", "mlModel", "mlModelGroup", "mlFeatureTable",
    "mlFeature", "mlPrimaryKey", "dataProduct", "businessAttribute", "application",
    "document",
})

#: The types Antigen's own structured-property definitions cover. Derived from
#: `register_properties.ENTITY_TYPES` so the definition stays the single source of
#: truth — see the module docstring.
STRUCTURED_PROPERTY_TYPES = frozenset(
    t.rsplit(_ENTITY_TYPE_URN_PREFIX, 1)[-1] for t in _PROPERTY_ENTITY_TYPES
)

#: The types a poisoned description can live on but `update_description` refuses.
#: Named only for the operator-facing message; the CHECK is `UPDATE_DESCRIPTION_TYPES`
#: membership, so a type nobody thought of still fails closed into containment.
KNOWN_UNSUPPORTED = ("chart", "dashboard", "dataFlow", "dataJob", "corpuser")


def entity_type(urn: str) -> str:
    """The entity-type segment of a DataHub URN — `urn:li:<type>:<key>`.

    Returns `""` for anything that is not a well-formed `urn:li:` URN, which fails
    CLOSED: an unparseable URN is treated as unsupported by every tool below rather
    than being handed to a mutation that would raise mid-run.
    """
    parts = urn.split(":", 3)
    if len(parts) < 3 or parts[0] != "urn" or parts[1] != "li":
        return ""
    return parts[2]


def supports_update_description(urn: str) -> bool:
    """True if DataHub's `updateDescription` resolver accepts this URN's type."""
    return entity_type(urn) in UPDATE_DESCRIPTION_TYPES


def supports_structured_properties(urn: str) -> bool:
    """True if Antigen's property definitions are scoped to this URN's type."""
    return entity_type(urn) in STRUCTURED_PROPERTY_TYPES


def unsupported_reason(urn: str) -> str:
    """Why this locus cannot be defused, in the words the operator needs to act."""
    etype = entity_type(urn) or "unparseable-urn"
    return (
        f"`update_description` is rejected server-side for entity type `{etype}`: "
        "DataHub's UpdateDescriptionResolver names 17 entity types and throws "
        "\"Failed to update description. Unsupported resource type\" for the rest "
        f"(chart, dashboard, dataFlow, dataJob and corpuser among them). The payload "
        "is STILL LIVE in this field — remove it in the DataHub UI, or at the source "
        "the connector ingests it from."
    )

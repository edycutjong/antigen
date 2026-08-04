"""antigen blast-radius — the lineage depth layer (criterion #1's named "lineage").

For each quarantined entity, walk `get_lineage(urn, direction="downstream", hops=2)`
to find the dashboards/tables that consumed the poisoned entity, and tag each with an
informational `injection-blast-radius:<source-urn>` via `add_tags` (a SECOND, distinct
use of the tool). This is "reachable from," not "infected by" — it never gates the
downstream entity's own lifecycle. It answers the platform team's real question:
"did an agent already act on this poison downstream?"

Additive and clearly secondary: it emits `avg blast radius: N/hit` and never replaces
the headline 0/12 number.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .gateway import Gateway


def _blast_tag(source_urn: str) -> str:
    return f"injection-blast-radius:{source_urn}"


@dataclass
class BlastRadiusResult:
    per_source: dict[str, list[str]] = field(default_factory=dict)

    @property
    def total_downstream(self) -> int:
        return sum(len(v) for v in self.per_source.values())

    @property
    def avg_per_hit(self) -> float:
        return self.total_downstream / len(self.per_source) if self.per_source else 0.0

    def summary(self) -> str:
        return (f"blast radius: {self.total_downstream} downstream assets across "
                f"{len(self.per_source)} quarantined entities "
                f"(avg {self.avg_per_hit:.1f}/hit)")


def map_blast_radius(gateway: Gateway, source_urns: list[str], *,
                     hops: int = 2, tag_downstream: bool = True) -> BlastRadiusResult:
    result = BlastRadiusResult()
    for src in source_urns:
        downstream = gateway.get_lineage(src, direction="downstream", hops=hops)
        result.per_source[src] = downstream
        if tag_downstream:
            for d in downstream:
                gateway.add_tags(d, [_blast_tag(src)])
    return result

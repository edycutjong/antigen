"""In-memory DataHub graph — a transport double for offline tests. NOT production.

Implements `antigen.gateway.Gateway`. Records aspect version history on every
description write (mirroring GMS's real behavior), which is what powers the
one-action false-positive revert story — and lets a test prove the pre-cure text is
NOT reachable through any stock READ tool afterwards.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..gateway import Document, Entity


@dataclass
class _VersionHistory:
    """Native GMS aspect versioning — retained but NOT exposed by READ tools."""

    entries: list[tuple[str, str]] = field(default_factory=list)  # (field_path|'', text)

    def push(self, field_path: str, text: str) -> None:
        self.entries.append((field_path or "", text))


class InMemoryGateway:
    def __init__(self) -> None:
        self._entities: dict[str, Entity] = {}
        self._documents: dict[tuple[str, str], Document] = {}  # (parent, title) -> Document
        self._lineage: dict[str, list[str]] = {}   # urn -> downstream urns
        self._history: dict[str, _VersionHistory] = {}
        self.calls: list[tuple[str, tuple]] = []    # audit log for tests

    # -- seeding (test setup only; not part of the Gateway interface) ----- #
    def add_entity(self, entity: Entity) -> None:
        self._entities[entity.urn] = entity
        self._history.setdefault(entity.urn, _VersionHistory())

    def add_document(self, doc: Document) -> None:
        # Documents are identified by (parent, title) — the real save/overwrite key.
        self._documents[(doc.parent, doc.title)] = doc

    def add_lineage(self, urn: str, downstream: list[str]) -> None:
        self._lineage[urn] = downstream

    def version_history(self, urn: str) -> list[tuple[str, str]]:
        return list(self._history.get(urn, _VersionHistory()).entries)

    # -- READ ------------------------------------------------------------- #
    def search_all(self) -> list[str]:
        self.calls.append(("search", ()))
        return list(self._entities)

    def get_entities(self, urns: list[str]) -> list[Entity]:
        self.calls.append(("get_entities", tuple(urns)))
        return [self._entities[u] for u in urns if u in self._entities]

    def grep_documents(self, pattern: str) -> list[Document]:
        self.calls.append(("grep_documents", (pattern,)))
        rx = re.compile(pattern, re.IGNORECASE | re.DOTALL)
        return [d for d in self._documents.values() if rx.search(d.content)]

    def get_lineage(self, urn: str, direction: str = "downstream",
                    hops: int = 2) -> list[str]:
        self.calls.append(("get_lineage", (urn, direction, hops)))
        # Simple BFS over the recorded downstream edges up to `hops`.
        seen: set[str] = set()
        frontier = [urn]
        for _ in range(hops):
            nxt: list[str] = []
            for u in frontier:
                for d in self._lineage.get(u, []):
                    if d not in seen:
                        seen.add(d)
                        nxt.append(d)
            frontier = nxt
        return list(seen)

    # -- MUTATION --------------------------------------------------------- #
    def update_description(self, urn: str, description: str,
                           field_path: str | None = None) -> None:
        self.calls.append(("update_description", (urn, field_path)))
        ent = self._entities.get(urn)
        if ent is None:
            raise KeyError(f"unknown entity {urn}")
        if field_path:
            col = ent.columns.get(field_path)
            if col is None:
                raise KeyError(f"unknown column {urn}::{field_path}")
            self._history[urn].push(field_path, col.description)  # version the old text
            col.description = description
        else:
            self._history[urn].push("", ent.description)
            ent.description = description

    def add_tags(self, urn: str, tags: list[str],
                 field_path: str | None = None) -> None:
        self.calls.append(("add_tags", (urn, field_path, tuple(tags))))
        ent = self._entities.get(urn)
        if ent is None:
            raise KeyError(f"unknown entity {urn}")
        target = ent.columns[field_path].tags if field_path else ent.tags
        for t in tags:
            if t not in target:
                target.append(t)

    def add_structured_properties(self, urn: str, properties: dict[str, str]) -> None:
        self.calls.append(("add_structured_properties", (urn, tuple(properties))))
        ent = self._entities.get(urn)
        if ent is None:
            raise KeyError(f"unknown entity {urn}")
        ent.structured_properties.update(properties)

    def save_document(self, title: str, content: str,
                      parent: str = "Antigen/Incidents",
                      urn: str | None = None,
                      related_assets: list[str] | None = None,
                      related_documents: list[str] | None = None) -> str | None:
        # Overwrite in place by (parent, title), exactly like the real tool with
        # SAVE_DOCUMENT_RESTRICT_UPDATES=false. `related_assets`/`related_documents`
        # are retained so an offline test can assert the incident record is an EDGE
        # from the poisoned asset and not an orphan node.
        self.calls.append(("save_document", (parent, title)))
        from ..corpus import doc_urn
        assigned = urn or doc_urn(parent, title)
        self._documents[(parent, title)] = Document(
            urn=assigned, title=title, content=content, parent=parent,
            related_assets=list(related_assets or []),
            related_documents=list(related_documents or []))
        return assigned

    # -- convenience ------------------------------------------------------ #
    def get_entity(self, urn: str) -> Entity | None:
        return self._entities.get(urn)

    def get_document(self, parent: str, title: str) -> Document | None:
        return self._documents.get((parent, title))

"""antigen scan — the READ-only sweep engine.

Enumerates the whole catalog via `search`, batch-pulls description + column text via
`get_entities`, and regex-hunts KB documents via `grep_documents`, running the real
`antigen.detect` scored rule on every free-text surface an agent could read.

Idempotency: entities already tagged `injection-quarantined` are skipped, so
`antigen scan && antigen cure` run twice with no state reset is a no-op.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .detect import Detection, detect
from .gateway import Gateway

QUARANTINE_TAG = "injection-quarantined"
CERTIFIED_TAG = "agent-safe-certified"

# Broad signature pre-filter for grep_documents. `grep_documents` narrows the doc
# set to candidates containing any trigger token; `detect` then confirms with the
# full scored rule. This keeps grep_documents load-bearing (not decorative) while
# the precision still comes from the scored rule.
DOC_GREP_PATTERN = (
    r"ignore|disregard|forget|override|bypass|system\s+prompt|"
    r"exfiltrat|export|send|email|invoke|reveal|credential|instruction|"
    r"api[\s_-]?key|do\s+anything\s+now"
)

#: Title prefix of Antigen's own forensic incident records.
INCIDENT_TITLE_PREFIX = "antigen-incident-"


def is_own_incident(title: str | None) -> bool:
    """True for Antigen's own incident ledger, which the sweep must not scan.

    An incident report names the categories it remediated ("detection signals:
    instruction-override, reveal-secret"). Those category names are themselves
    detector triggers, so scanning our own ledger re-flags it — and because a cure
    writes an incident record, curing one would emit another, forever.

    This is the same exemption an antivirus grants its own quarantine store. The
    record holds only irreversible hashes, never a payload, so exempting it cannot
    hide attacker-controlled text.

    Trade-off, stated plainly: the exemption is title-based, so an attacker who can
    write a KB document could name it `antigen-incident-*` to avoid being scanned.
    Closing that needs provenance the document tool does not expose (no author or
    signature field) — it is written up in docs/RFC-output-sanitization.md.
    """
    return title is not None and title.startswith(INCIDENT_TITLE_PREFIX)

_BATCH = 100


class Locus(str, Enum):
    ENTITY = "entity-description"
    COLUMN = "column-description"
    DOCUMENT = "kb-document"


@dataclass
class ScanHit:
    urn: str
    locus: Locus
    field_path: str | None
    source_tool: str            # which READ tool surfaced it
    text: str                   # the poisoned text as read
    detection: Detection
    doc_title: str | None = None    # for document loci: the (parent, title) identity
    doc_parent: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.urn, self.field_path or "")


@dataclass
class ScanReport:
    hits: list[ScanHit]
    entities_scanned: int
    documents_scanned: int
    skipped_quarantined: int
    clean_entity_urns: list[str] = field(default_factory=list)

    def summary(self) -> str:
        by_tool: dict[str, int] = {}
        hidden = 0
        for h in self.hits:
            by_tool[h.source_tool] = by_tool.get(h.source_tool, 0) + 1
            if h.detection.hidden_unicode:
                hidden += 1
        parts = [
            f"scanned {self.entities_scanned} entities + {self.documents_scanned} documents",
            f"{len(self.hits)} injection loci flagged",
            f"{hidden} hidden in zero-width Unicode",
        ]
        parts += [f"{n} via {t}" for t, n in sorted(by_tool.items())]
        if self.skipped_quarantined:
            parts.append(f"{self.skipped_quarantined} already-quarantined (skipped)")
        return " | ".join(parts)


def scan(gateway: Gateway, *, skip_quarantined: bool = True,
         grep_documents: bool = True) -> ScanReport:
    urns = gateway.search_all()
    hits: list[ScanHit] = []
    clean: list[str] = []
    scanned = 0
    skipped = 0

    for start in range(0, len(urns), _BATCH):
        batch = urns[start:start + _BATCH]
        for ent in gateway.get_entities(batch):
            scanned += 1
            if skip_quarantined and QUARANTINE_TAG in ent.tags:
                skipped += 1
                continue

            entity_flagged = False

            d = detect(ent.description)
            if d.flagged:
                hits.append(ScanHit(ent.urn, Locus.ENTITY, None,
                                    "get_entities", ent.description, d))
                entity_flagged = True

            for col in ent.columns.values():
                dc = detect(col.description)
                if dc.flagged:
                    hits.append(ScanHit(ent.urn, Locus.COLUMN, col.field_path,
                                        "get_entities", col.description, dc))
                    entity_flagged = True

            if not entity_flagged:
                clean.append(ent.urn)

    docs_scanned = 0
    if grep_documents:
        for doc in gateway.grep_documents(DOC_GREP_PATTERN):
            if is_own_incident(doc.title):
                continue
            docs_scanned += 1
            dd = detect(doc.content)
            if dd.flagged:
                hits.append(ScanHit(doc.urn, Locus.DOCUMENT, None,
                                    "grep_documents", doc.content, dd,
                                    doc_title=doc.title, doc_parent=doc.parent))

    return ScanReport(hits=hits, entities_scanned=scanned,
                      documents_scanned=docs_scanned, skipped_quarantined=skipped,
                      clean_entity_urns=clean)

"""antigen scan — the READ-only sweep engine.

Enumerates the whole catalog via `search`, batch-pulls description + column text via
`get_entities`, and regex-hunts KB documents via `grep_documents`, running the real
`antigen.detect` scored rule on every free-text surface an agent could read.

Idempotency: entities already tagged `injection-quarantined` are skipped, so
`antigen scan && antigen cure` run twice with no state reset is a no-op.

Fail-closed: a sweep that enumerated nothing, that was handed back fewer entities than
it asked for, or whose reads degraded records why in `ScanReport.degraded_reasons` and
is reported as DEGRADED rather than clean. A dead or misconfigured GMS returns an empty
catalog that is indistinguishable on the wire from a clean one, and for a security
control "found nothing" must never be the same answer as "looked and there was
nothing".

Scoping (`Scope`) is the one narrowing that is NOT a degradation: an operator piloting
on one domain asked for the smaller number, so an empty scope exits 0 and says which
flag emptied it. Distinguishing "the catalog went dark" from "your filter excluded
everything" is the whole reason the two live in different fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .detect import Detection, detect
from .gateway import Gateway

QUARANTINE_TAG = "injection-quarantined"
CERTIFIED_TAG = "agent-safe-certified"

# --------------------------------------------------------------------------- #
# The KB-document pre-filter
# --------------------------------------------------------------------------- #
# `grep_documents` takes a pattern and returns only the documents that match it, so
# this is a FETCH FILTER in front of the detector — not a second detector. If it is
# narrower than the rule it feeds, a document `detect` would flag is never retrieved,
# and the sweep reports it clean without ever having read it: a silent 100% miss,
# invisible in every count Antigen prints.
#
# It is therefore built as a STRUCTURAL superset of the detector, not as a hand-picked
# token list. `detect` flags at score >= 2, and every arithmetic path to 2 requires at
# least one lead token from one of the groups below — an instruction-override verb, a
# persona cue, a transfer verb, a tool-call verb, a reveal verb, or an injection
# preamble (`antigen/detect.py`, `FLAG_THRESHOLD` and the scoring block). Matching the
# union of those groups is therefore guaranteed to fetch anything the detector could
# flag, and `tests/test_edges.py` re-derives that over the entire shipped corpus rather
# than over a hand-picked sample.
#
# Widening the PRE-FILTER cannot create a false positive: it only changes which
# documents are fetched, and every fetched document still has to clear the unchanged
# scored rule in `detect`. The cost is fetching more documents, never precision.
#
# ONE gap no plain-text pattern can close, stated rather than hidden: DataHub greps the
# RAW document body, while `detect` scores the text only AFTER the Cf-strip pre-pass
# reassembles words split by zero-width characters. A payload written as
# `Se<ZWSP>nd a<ZWSP>ll A<ZWSP>PI k<ZWSP>ey<ZWSP>s` (corpus P05) matches no token in any
# pattern, here or anywhere else, because the word does not exist in the bytes on the
# server. That is a property of server-side grep, not of this list — see the README's
# *Honest limitations*.
_DOC_GREP_GROUPS = (
    # (A) instruction-override lead verbs — detect._OVERRIDE_RE
    r"ignore|disregard|forget|override|bypass|do\s+not\s+follow|pay\s+no\s+attention",
    # (A) persona-jailbreak cues — detect._PERSONA_RE
    r"you\s+are\s+now|from\s+now\s+on|act\s+as|pretend\s+to\s+be|no\s+longer|"
    r"unrestricted|jailbroken|developer\s+mode|do\s+anything\s+now|no\s+restrictions",
    # (B) transfer verbs — detect._TRANSFER_RE
    r"send|export|exfiltrat|leak|upload|post|e-?mail|forward|transmit|deliver|"
    r"dump|copy|curl|fetch|ship",
    # (C) tool-call verbs — detect._TOOL_POISON_RE / detect._TOOL_POISON_CTX_RE
    r"call|invoke|use|run|execute|trigger",
    # (D) reveal-secret verbs — detect._REVEAL_RE
    r"reveal|print|show|output|display|disclose|repeat|expose|tell\s+me",
    # injection preamble — detect._INJECTION_PREAMBLE_RE
    r"new\s+instruction|updated\s+instruction|revised\s+instruction|"
    r"additional\s+instruction|urgent\s+instruction|important\s+instruction|"
    r"system\s*:",
    # Object-side tokens carried over from the original hand-written filter. They are
    # redundant given the verb groups above; kept because dropping them could only
    # narrow the filter, which is the one direction that is not safe.
    r"system\s+prompt|credential|instruction|api[\s_-]?key",
)
DOC_GREP_PATTERN = "|".join(_DOC_GREP_GROUPS)

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


#: What a sweep that enumerated nothing has to say for itself. A dead or
#: misconfigured GMS returns an empty catalog, which is indistinguishable from a clean
#: one on the wire — so it must never be reported as clean.
EMPTY_CATALOG_REASON = ("0 entities enumerated — catalog empty or gateway "
                        "misconfigured")

#: The same fail-closed rule, one step later in the pipeline. The enumeration guard
#: above only proves the catalog answered `search`; it says nothing about whether the
#: entities it named were ever READ. A gateway that lists 800 URNs and hands back 12
#: entities (`_as_list` maps a `None` or an error envelope to `[]` without raising)
#: produced a sweep that looked at 12 fields and reported the other 788 clean.
#: Document scope already refuses that trade (`gateway._document_urns`); this is the
#: entity-scope analogue, on the path that carries 10 of the 12 corpus payloads.
UNDER_FETCH_REASON = ("get_entities returned {scanned}/{requested} requested entities "
                      "— {missing} were never read, and an entity that was not read "
                      "cannot be reported clean")


@dataclass(frozen=True)
class Scope:
    """A read-side narrowing of the sweep — `scan --urn-contains / --max-entities`.

    Why it exists: the standard way a platform team adopts a control is to pilot it on
    one domain before pointing it at everything. Until this, the only lever for that
    was a DataHub policy on a SECOND scoped service account — so "try it on finance
    first" was a credential-provisioning exercise rather than a flag.

    What it is NOT: server-side. It filters the URN list `search_all()` already
    returned, so it saves `get_entities` round-trips and never the enumeration — and
    that is deliberate, because the enumeration is what the fail-closed check reads.
    `urn_contains` is a plain case-insensitive SUBSTRING, not a regex: a DataHub URN
    is full of `(`, `)` and `,`, and every one of those is a regex metacharacter.

    `urn_contains` narrows EVERY locus, KB documents included, so the flag means one
    thing everywhere: sweep the URNs that contain this. `max_entities` is entity-only,
    as its name says — truncating a document sweep to "the first N" is not a scope an
    operator can reason about. `summary()` states both counts either way.
    """

    urn_contains: str | None = None
    max_entities: int | None = None

    @property
    def active(self) -> bool:
        return self.urn_contains is not None or self.max_entities is not None

    def matches_urn(self, urn: str) -> bool:
        """True if `urn` is inside the scope. The `--max-entities` cut is separate."""
        return self.urn_contains is None or self.urn_contains.lower() in urn.lower()

    def apply(self, urns: list[str]) -> list[str]:
        selected = [u for u in urns if self.matches_urn(u)]
        if self.max_entities is not None:
            # Clamped at 0 because a negative bound would slice from the END of the
            # list — a scope that quietly scans nearly everything when the operator
            # asked for a handful is the one way a limit must never fail.
            selected = selected[:max(self.max_entities, 0)]
        return selected

    def describe(self) -> str:
        flags = []
        if self.urn_contains is not None:
            flags.append(f"--urn-contains {self.urn_contains!r}")
        if self.max_entities is not None:
            flags.append(f"--max-entities {self.max_entities}")
        return " ".join(flags)


@dataclass
class ScanReport:
    hits: list[ScanHit]
    entities_scanned: int
    documents_scanned: int
    skipped_quarantined: int
    clean_entity_urns: list[str] = field(default_factory=list)
    #: Reads that failed or returned nothing. Non-empty ⇒ this sweep is NOT an
    #: all-clear, however few hits it found.
    degraded_reasons: list[str] = field(default_factory=list)
    #: URNs `search_all` returned, BEFORE any scope. The fail-closed check reads this
    #: one — a scope narrowing 800 entities to 3 is not a blackout, an enumeration
    #: that returned 0 is.
    entities_enumerated: int = 0
    #: URNs left after the scope, i.e. what `get_entities` was asked for.
    entities_in_scope: int = 0
    #: The scope that narrowed this run, or None when the whole catalog was swept.
    scope: Scope | None = None

    @property
    def degraded(self) -> bool:
        return bool(self.degraded_reasons)

    @property
    def scope_empty(self) -> bool:
        """True when the operator's own filter — not a blackout — read nothing.

        Deliberately NOT a degradation. `0 entities enumerated` means the catalog went
        dark and has to fail closed; `--urn-contains finance` matching none of 78
        enumerated entities is the filter doing exactly what it was asked to do.
        Failing that closed would exit 2 on a working pilot run and teach operators
        that exit 2 is noise — which is the one lesson that makes the real blackout
        invisible.
        """
        return self.scope is not None and self.entities_enumerated > 0 \
            and self.entities_in_scope == 0

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
        if self.scope is not None:
            # A scoped run must never print a bare count that reads like whole-catalog
            # coverage: say what was excluded, and by which flag.
            parts.append(f"SCOPED by {self.scope.describe()}: "
                         f"{self.entities_in_scope} of {self.entities_enumerated} "
                         "enumerated entities")
        if self.degraded_reasons:
            # Never let a confident-looking count stand alone over a broken sweep.
            parts.append("DEGRADED: " + "; ".join(self.degraded_reasons))
        return " | ".join(parts)


def scan(gateway: Gateway, *, skip_quarantined: bool = True,
         grep_documents: bool = True, scope: Scope | None = None) -> ScanReport:
    enumerated = gateway.search_all()
    scope = scope if scope is not None and scope.active else None
    urns = scope.apply(enumerated) if scope is not None else enumerated
    degraded: list[str] = [] if enumerated else [EMPTY_CATALOG_REASON]
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

    if scanned < len(urns):
        degraded.append(UNDER_FETCH_REASON.format(
            scanned=scanned, requested=len(urns), missing=len(urns) - scanned))

    docs_scanned = 0
    if grep_documents:
        for doc in gateway.grep_documents(DOC_GREP_PATTERN):
            if is_own_incident(doc.title):
                continue
            if scope is not None and not scope.matches_urn(doc.urn):
                continue
            docs_scanned += 1
            dd = detect(doc.content)
            if dd.flagged:
                hits.append(ScanHit(doc.urn, Locus.DOCUMENT, None,
                                    "grep_documents", doc.content, dd,
                                    doc_title=doc.title, doc_parent=doc.parent))

    # Collected AFTER the document pass so a failed `search_documents` is included.
    degraded += list(getattr(gateway, "degradations", list)())

    return ScanReport(hits=hits, entities_scanned=scanned,
                      documents_scanned=docs_scanned, skipped_quarantined=skipped,
                      clean_entity_urns=clean, degraded_reasons=degraded,
                      entities_enumerated=len(enumerated),
                      entities_in_scope=len(urns), scope=scope)

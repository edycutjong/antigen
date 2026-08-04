"""antigen cure — defuse by REMOVAL, chaining the 4 DataHub write-back tools.

For every scan hit, in order:

  1. update_description        reconstruct clean text with the injected span DELETED
                              (not quoted — an LLM can obey text inside a quote block)
                              plus a short inert banner.
  2. add_tags                  `injection-quarantined` on the poisoned entity.
  3. add_structured_properties `antigen.contentSha256` (hash of the cleaned field, for
                              tamper-evidence) + `antigen.lastScanned` +
                              `antigen.payloadSha256` (an IRREVERSIBLE hash of the
                              removed payload, forensic correlation only).
  4. save_document             forensic incident report (hashes + repo pointer, never
                              the recoverable payload) into `Antigen/Incidents`; for
                              document loci, also overwrite the poisoned KB doc.

No recoverable payload — plaintext or encoded — is ever written to the graph. The raw
payloads live only in the repo `examples/` folder.

Cleaning strategy:
  * fixture-backed (corpus/demo): the fixture records the field's original legitimate
    text, so removal is exact.
  * out-of-corpus (CI/live): no fixture exists, so the whole field is quarantined —
    replaced by the banner, its content moved to defanged evidence — rather than
    claiming guaranteed clean auto-excision on arbitrary text.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field

from .gateway import Entity, Gateway
from .scan import QUARANTINE_TAG, Locus, ScanHit

CONTENT_SHA_PROP = "antigen.contentSha256"
PAYLOAD_SHA_PROP = "antigen.payloadSha256"
LAST_SCANNED_PROP = "antigen.lastScanned"
INCIDENTS_FOLDER = "Antigen/Incidents"

# The banner marker that separates the cleaned content from Antigen's inert notice.
# `content-sha256` is computed over the text BEFORE this marker, so a later edit to
# the real content trips rescan while the banner itself is excluded from the hash.
BANNER_MARKER = "\n\n> ⚠ Antigen:"

# The inert banner left in place of the removed payload. Contains no imperative.
BANNER = (BANNER_MARKER + " a prompt-injection payload was removed from this field on "
          "{date}. Forensic evidence: {evidence}. Detection signals: {rule}.")

EVIDENCE_POINTER = "repo examples/payloads/{pid}.txt (out-of-band; not on the graph)"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_content(entity: Entity) -> str:
    """The exact slice `antigen.contentSha256` covers for an entity.

    Concatenates every free-text surface on the entity — its description and each
    column description — taking the text BEFORE the Antigen banner where a banner is
    present (a cured surface) and the whole text otherwise (a clean/certified
    surface). Used by `cure`, `certify`, AND `rescan`, so all three agree exactly:
    any later edit to any real content — on a quarantined OR a certified entity —
    changes this string and trips drift detection. The banner itself is excluded so
    Antigen's own notice never perturbs the hash.
    """
    parts: list[str] = []
    surfaces = [entity.description or ""]
    surfaces += [c.description or "" for c in entity.columns.values()]
    for text in surfaces:
        parts.append(text.split(BANNER_MARKER)[0] if BANNER_MARKER in text else text)
    return "\n".join(parts)


# Back-compat alias (older imports).
hashed_content = canonical_content


@dataclass
class Fixture:
    """What the demo/corpus knows about a planted payload (for exact excision)."""

    original_text: str
    payload_text: str
    payload_id: str = "unknown"


# fixtures keyed by (urn, field_path or "")
Fixtures = dict[tuple[str, str], Fixture]


@dataclass
class CureAction:
    urn: str
    locus: Locus
    field_path: str | None
    payload_id: str
    content_sha256: str
    payload_sha256: str
    cleaned_text: str
    mode: str            # "excise" (fixture-backed) or "quarantine-field" (out-of-corpus)
    incident_urn: str
    blast_radius: int = 0


@dataclass
class CureResult:
    actions: list[CureAction] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)   # already-cured (idempotency)

    def summary(self) -> str:
        excised = sum(1 for a in self.actions if a.mode == "excise")
        quarantined = sum(1 for a in self.actions if a.mode == "quarantine-field")
        s = f"cured {len(self.actions)} loci ({excised} excised, {quarantined} field-quarantined)"
        if self.skipped:
            s += f" | {len(self.skipped)} already-cured (idempotent no-op)"
        return s


def cure(gateway: Gateway, hits: list[ScanHit], *,
         fixtures: Fixtures | None = None,
         now: str = "1970-01-01T00:00:00Z",
         clock: Callable[[], str] | None = None) -> CureResult:
    """Apply the 4-write-back cure to every hit. Idempotent by construction."""
    fixtures = fixtures or {}
    timestamp = clock() if clock else now
    result = CureResult()
    seen_this_run: set[str] = set()   # entities we have already begun curing this call

    for hit in hits:
        ent = gateway.get_entity(hit.urn) if hit.locus is not Locus.DOCUMENT else None

        # Idempotency guard. Skip only if the entity was cured in a PRIOR run (already
        # quarantined + stamped and NOT yet touched this run). A second hit on an
        # entity within THIS run — e.g. a poisoned description AND a poisoned column on
        # the same entity — must still be processed, or that locus would survive.
        if ent is not None and hit.urn not in seen_this_run \
                and QUARANTINE_TAG in ent.tags \
                and CONTENT_SHA_PROP in ent.structured_properties:
            result.skipped.append(hit.urn)
            continue
        if ent is not None:
            seen_this_run.add(hit.urn)

        fx = fixtures.get(hit.key)
        payload_id = fx.payload_id if fx else "adhoc"

        # --- decide clean text + removed payload --------------------------
        if fx is not None:
            cleaned = fx.original_text
            removed_payload = fx.payload_text
            mode = "excise"
        else:
            # Out-of-corpus: quarantine the whole field, move content to evidence.
            removed_payload = hit.detection.matched_text or hit.text
            cleaned = "[field quarantined by Antigen pending human review]"
            mode = "quarantine-field"

        payload_sha = _sha256(removed_payload)
        incident_title = f"antigen-incident-{payload_id}"
        incident_urn = f"urn:li:document:{INCIDENTS_FOLDER}/{incident_title}"

        banner = BANNER.format(
            date=timestamp,
            evidence=EVIDENCE_POINTER.format(pid=payload_id),
            rule=hit.detection.safe_summary,   # SAFE labels only, never payload text
        )
        clean_with_banner = cleaned + banner

        if hit.locus is Locus.DOCUMENT:
            # (4b) overwrite the poisoned KB document IN PLACE, by its own (parent,
            # title) identity — the only key the real save_document tool accepts.
            assert hit.doc_title is not None  # scan sets these for every doc hit
            gateway.save_document(title=hit.doc_title, content=clean_with_banner,
                                  parent=hit.doc_parent or "Shared")
            content_sha = _sha256(cleaned)
        else:
            # (1) update_description — the DEFUSE.
            gateway.update_description(hit.urn, clean_with_banner,
                                      field_path=hit.field_path)
            # (2) add_tags — quarantine the entity.
            gateway.add_tags(hit.urn, [QUARANTINE_TAG])
            # (3) add_structured_properties — tamper-evidence, hashes ONLY.
            # Hash the cured surface as it now reads back, so rescan agrees exactly.
            cured_entity = gateway.get_entity(hit.urn)
            content_sha = _sha256(canonical_content(cured_entity)) if cured_entity \
                else _sha256(cleaned)
            gateway.add_structured_properties(hit.urn, {
                CONTENT_SHA_PROP: content_sha,
                PAYLOAD_SHA_PROP: payload_sha,
                LAST_SCANNED_PROP: timestamp,
            })

        # (4) save_document — forensic incident (hashes + repo pointer, NO payload),
        # itself overwritten in place on re-runs (idempotent, no duplicate incidents).
        gateway.save_document(
            title=incident_title,
            content=_forensic_report(hit, payload_id, content_sha, payload_sha,
                                     timestamp, mode),
            parent=INCIDENTS_FOLDER,
        )

        result.actions.append(CureAction(
            urn=hit.urn, locus=hit.locus, field_path=hit.field_path,
            payload_id=payload_id, content_sha256=content_sha,
            payload_sha256=payload_sha, cleaned_text=cleaned, mode=mode,
            incident_urn=incident_urn,
        ))

    return result


def _forensic_report(hit: ScanHit, payload_id: str, content_sha: str,
                     payload_sha: str, timestamp: str, mode: str) -> str:
    return (
        f"# Antigen incident — {payload_id}\n\n"
        f"- entity: `{hit.urn}`\n"
        f"- locus: {hit.locus.value}"
        f"{f' (column `{hit.field_path}`)' if hit.field_path else ''}\n"
        f"- surfaced by: `{hit.source_tool}`\n"
        f"- detected: {timestamp}\n"
        f"- detection signals: {hit.detection.safe_summary}\n"
        f"- categories: {', '.join(c.value for c in hit.detection.categories)}\n"
        f"- hidden in zero-width Unicode: {hit.detection.hidden_unicode}\n"
        f"- remediation mode: {mode}\n"
        f"- content-sha256 (cleaned field): `{content_sha}`\n"
        f"- payload-sha256 (removed payload, irreversible): `{payload_sha}`\n"
        f"- raw payload location: repo `examples/payloads/{payload_id}.txt` "
        f"(NEVER stored on the graph)\n\n"
        f"The injected span was **removed** from every agent-readable surface. This "
        f"record holds only irreversible hashes; it cannot be obeyed or decoded back "
        f"into the payload.\n"
    )

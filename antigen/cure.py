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
  4. save_document             forensic incident report (hashes only — plus a repo
                              pointer for the 12 checked-in corpus payloads) into
                              `Antigen/Incidents`; for document loci, also overwrite
                              the poisoned KB doc.

No recoverable payload — plaintext or encoded — is ever written to the graph. The 12
corpus payloads exist as files in the repo `examples/` folder; an out-of-corpus payload
is retained NOWHERE, by design.

Cleaning strategy:
  * fixture-backed (corpus/demo): the fixture records the field's original legitimate
    text, so removal is exact and the legitimate documentation survives.
  * out-of-corpus (CI/live): no fixture exists, so the WHOLE field is replaced by the
    banner — rather than claiming guaranteed clean auto-excision on arbitrary text.
    Be plain about the cost: Antigen does not preserve the removed text anywhere. The
    field's prior content is recoverable from DataHub's native aspect version history
    (one action per field), and from nothing Antigen writes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field

from .detect import detect
from .gateway import Entity, Gateway
from .scan import INCIDENT_TITLE_PREFIX, QUARANTINE_TAG, Locus, ScanHit

CONTENT_SHA_PROP = "antigen.contentSha256"
PAYLOAD_SHA_PROP = "antigen.payloadSha256"
LAST_SCANNED_PROP = "antigen.lastScanned"
INCIDENTS_FOLDER = "Antigen/Incidents"

#: Content substring every forensic incident record carries, used to resolve the
#: existing incident ledger so a re-cure overwrites instead of duplicating.
INCIDENT_GREP = r"Antigen incident"

# The banner marker that separates the cleaned content from Antigen's inert notice.
# `content-sha256` is computed over the text BEFORE this marker, so a later edit to
# the real content trips rescan while the banner itself is excluded from the hash.
BANNER_MARKER = "\n\n> ⚠ Antigen:"

# The inert banner left in place of the removed payload. Contains no imperative — and,
# deliberately, no detection CATEGORY LABEL either.
#
# It used to end `Detection signals: {rule}`, interpolating the safe labels straight
# from the detector ("instruction-override, reveal-secret"). Those labels are English
# phrases that the detector's own rules match: `reveal-secret` alone scores 2 on the
# reveal-secret rule, which is the flag threshold. So Antigen's remediation notice
# re-tripped Antigen's detector, and a cured field flagged again on the next sweep.
#
# Entities survived that by accident — `scan` skips anything tagged
# `injection-quarantined`, and `cure`'s idempotency guard skips an already-stamped
# entity. A KB DOCUMENT has neither shield: its title is unchanged by the cure, so
# `is_own_incident` does not exempt it. The result was a cure/scan loop that never
# converged, a `scan --fail-on-hit` cron that never went green again, and an incident
# ledger growing one record per cycle whose `payload-sha256` was the digest of
# Antigen's own banner.
#
# The labels now live ONLY in the forensic incident record, which `scan` already
# exempts by title prefix. The banner points at it by name instead.
BANNER = (BANNER_MARKER + " a prompt-injection payload was removed from this field on "
          "{date}. Forensic evidence: {evidence}. Detection signals: recorded in the "
          "Antigen incident record `{incident}` (the category labels are not repeated "
          "here — they are detector triggers themselves).")

#: Structural backstop for the same failure: if anything interpolated into the banner
#: would still make the written text flag, fall back to this, which carries no
#: free-text pointer at all.
MINIMAL_BANNER = (BANNER_MARKER + " a prompt-injection payload was removed from this "
                  "field on {date}. See the Antigen incident record `{incident}`.")

EVIDENCE_POINTER = "repo examples/payloads/{pid}.txt (out-of-band; not on the graph)"

# Out-of-corpus hits have no checked-in payload file, and the incident record holds
# hashes ONLY — so this pointer must not imply the removed text can be retrieved from
# it. Name the digest as the handle and DataHub's aspect history as the recovery path.
ADHOC_EVIDENCE_POINTER = ("Antigen incident record for payload sha256 {sha}… (hashes "
                          "only; restore the field's prior text from DataHub aspect "
                          "version history)")


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


def inert_banner(cleaned: str, *, date: str, evidence: str, incident: str) -> str:
    """Compose the remediation banner, guaranteed not to flag the text it is added to.

    THE CONVERGENCE INVARIANT: Antigen must never write to the graph any text its own
    detector flags. If it does, the next sweep re-flags the field it just cured, cures
    it again, writes another incident record, and the loop never terminates — for KB
    documents, which carry neither the `injection-quarantined` skip nor an
    `antigen-incident-` title, that loop is unbounded.

    The banner text is already label-free (see ``BANNER``), so the full form is what
    normally ships. This function is the backstop that makes the invariant structural
    rather than a property of one carefully-worded string: it scores the exact text
    that would be written, with the real detector, and degrades to ``MINIMAL_BANNER``
    if the evidence pointer or the incident id would trip it.

    If ``cleaned`` flags on its own the banner is not the problem and is returned
    unchanged — shortening a notice cannot fix content that is still poisoned, and
    silently swapping it would hide that.
    """
    full = BANNER.format(date=date, evidence=evidence, incident=incident)
    if detect(cleaned + full).flagged and not detect(cleaned).flagged:
        return MINIMAL_BANNER.format(date=date, incident=incident)
    return full


def existing_incident_urns(gateway: Gateway) -> dict[str, str]:
    """Title → URN for the forensic incident records already on the graph.

    `save_document` WITHOUT a `urn` mints a brand-new document on a live GMS (the
    offline double keys on `(parent, title)` and overwrites, which is exactly why
    re-running the demo never surfaced this). So the incident save was not the
    idempotent overwrite its comment claimed: on the live path a re-cure of the same
    payload left a duplicate record behind, every run.

    One `grep_documents` call per `cure` run — the same tool the sweep already uses —
    resolves the ledger so each save can address its record by URN.
    """
    return {d.title: d.urn for d in gateway.grep_documents(INCIDENT_GREP)
            if d.urn and d.title.startswith(INCIDENT_TITLE_PREFIX)}


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
    # Resolved lazily: only a run that actually cures something pays the extra read.
    incident_ledger: dict[str, str] | None = None

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

        # --- decide clean text + removed payload --------------------------
        if fx is not None:
            cleaned = fx.original_text
            removed_payload = fx.payload_text
            mode = "excise"
        else:
            # Out-of-corpus: no fixture, so the WHOLE field is replaced. The removed
            # text is not preserved by Antigen — recovery is DataHub aspect history.
            removed_payload = hit.detection.matched_text or hit.text
            cleaned = "[field quarantined by Antigen pending human review]"
            mode = "quarantine-field"

        payload_sha = _sha256(removed_payload)
        # Fixture-backed hits carry a stable corpus id. Out-of-corpus hits are keyed
        # by payload digest — a shared "adhoc" id would collapse every incident on a
        # real catalog into one document title and overwrite each other's evidence.
        payload_id = fx.payload_id if fx else f"adhoc-{payload_sha[:12]}"
        incident_title = f"antigen-incident-{payload_id}"
        incident_urn = f"urn:li:document:{INCIDENTS_FOLDER}/{incident_title}"

        banner = inert_banner(
            cleaned,
            date=timestamp,
            # Only corpus payloads have a checked-in raw file to point at.
            evidence=(EVIDENCE_POINTER.format(pid=payload_id) if fx is not None
                      else ADHOC_EVIDENCE_POINTER.format(sha=payload_sha[:12])),
            incident=incident_title,
        )
        clean_with_banner = cleaned + banner

        if hit.locus is Locus.DOCUMENT:
            # (4b) overwrite the poisoned KB document IN PLACE, addressed by its own
            # URN. Title is NOT an identity key on a live GMS — saving without the URN
            # creates a second document and leaves the poisoned original readable.
            assert hit.doc_title is not None  # scan sets these for every doc hit
            gateway.save_document(title=hit.doc_title, content=clean_with_banner,
                                  parent=hit.doc_parent or "Shared", urn=hit.urn)
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

        # (4) save_document — forensic incident (hashes + repo pointer, NO payload).
        # Addressed by the EXISTING record's URN when one is already on the graph, so a
        # re-cure overwrites it rather than minting a duplicate (title is not an
        # identity key on a live GMS; see `existing_incident_urns`).
        if incident_ledger is None:
            incident_ledger = existing_incident_urns(gateway)
        gateway.save_document(
            title=incident_title,
            content=_forensic_report(hit, payload_id, content_sha, payload_sha,
                                     timestamp, mode, has_payload_file=fx is not None),
            parent=INCIDENTS_FOLDER,
            urn=incident_ledger.get(incident_title),
        )

        result.actions.append(CureAction(
            urn=hit.urn, locus=hit.locus, field_path=hit.field_path,
            payload_id=payload_id, content_sha256=content_sha,
            payload_sha256=payload_sha, cleaned_text=cleaned, mode=mode,
            incident_urn=incident_urn,
        ))

    return result


def _forensic_report(hit: ScanHit, payload_id: str, content_sha: str,
                     payload_sha: str, timestamp: str, mode: str, *,
                     has_payload_file: bool) -> str:
    # Only the 12 checked-in corpus payloads have a raw file. Emitting this pointer
    # unconditionally made EVERY real-catalog incident record cite
    # `examples/payloads/adhoc-<sha12>.txt` — a file that is never written. The banner
    # already guards its own pointer this way; this second site was simply missed.
    evidence = (
        f"- raw payload location: repo `examples/payloads/{payload_id}.txt` "
        "(NEVER stored on the graph)\n"
        if has_payload_file else
        "- raw payload location: none. Out-of-corpus hit — there is no checked-in "
        "payload file, and Antigen does not retain the removed text anywhere. The "
        "payload-sha256 above is the only handle; the field's prior content is "
        "recoverable from DataHub aspect version history, not from this record.\n"
    )
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
        f"{evidence}\n"
        f"The injected span was **removed** from every agent-readable surface. This "
        f"record holds only irreversible hashes; it cannot be obeyed or decoded back "
        f"into the payload.\n"
    )

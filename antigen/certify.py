"""antigen certify — tag the clean remainder `agent-safe-certified`.

This is a SEPARATE, untimed pass (~1,000 mutation round-trips on the full datapack),
deliberately excluded from the <30s `verify.py` Part-A gate so the headline timing
claim stays honest. It is real write-back, not a claim: every clean entity gets the
`agent-safe-certified` tag, making scan status queryable in the same catalog every
agent already uses.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from .cure import CONTENT_SHA_PROP, LAST_SCANNED_PROP, canonical_content
from .gateway import Gateway
from .scan import CERTIFIED_TAG


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class CertifyResult:
    certified: int = 0
    #: Already certified at this exact content hash — re-stamping them writes two
    #: real aspect versions per entity for zero information gain.
    unchanged: int = 0

    def summary(self) -> str:
        s = f"certified {self.certified} clean entities `{CERTIFIED_TAG}` (+ content hash)"
        if self.unchanged:
            s += f" | {self.unchanged} already certified at the same content hash (skipped)"
        return s


def certify(gateway: Gateway, clean_urns: list[str], *,
            now: str = "1970-01-01T00:00:00Z",
            clock: Callable[[], str] | None = None) -> CertifyResult:
    """Tag each clean entity `agent-safe-certified` AND stamp `antigen.contentSha256`.

    Stamping the hash here is what makes certification a *standing* control: `rescan`
    re-hashes every stamped entity, so a certified-clean entity whose content later
    changes is auto-re-flagged. Without the stamp, certification would silently rot.

    Incremental by content hash. An entity already carrying `agent-safe-certified`
    whose `antigen.contentSha256` still matches its current text is skipped: nothing
    about it has changed since the last sweep, and each re-stamp is a real aspect
    version plus a Kafka MCL event driving search reindex and timeline noise. On a
    nightly cron over a large catalog the unconditional loop re-emitted two mutations
    per clean entity, every night, forever. Content that DID change fails the hash
    comparison and is re-stamped — which is also how `antigen.lastScanned` stays
    meaningful: it is the timestamp of the last sweep that observed a *change*, and
    the standing freshness signal is the cron's own exit status, not this field.

    `clock` supplies the real time (`cli._clock`); `now` is the fixed fallback that
    keeps tests deterministic. Previously `now` defaulted to the literal string
    `"certify"`, which was written into `antigen.lastScanned` on every clean entity —
    a property the registered definition documents as an ISO-8601 timestamp, and one
    `cure` fills with a real one, so the field was mixed-type by construction.
    """
    timestamp = clock() if clock else now
    result = CertifyResult()
    for ent in gateway.get_entities(clean_urns):
        content_sha = _sha256(canonical_content(ent))
        if (CERTIFIED_TAG in ent.tags
                and ent.structured_properties.get(CONTENT_SHA_PROP) == content_sha):
            result.unchanged += 1
            continue
        gateway.add_tags(ent.urn, [CERTIFIED_TAG])
        gateway.add_structured_properties(ent.urn, {
            CONTENT_SHA_PROP: content_sha,
            LAST_SCANNED_PROP: timestamp,
        })
        result.certified += 1
    return result

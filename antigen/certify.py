"""antigen certify — tag the clean remainder `agent-safe-certified`.

This is a SEPARATE, untimed pass (~1,000 mutation round-trips on the full datapack),
deliberately excluded from the <30s `verify.py` Part-A gate so the headline timing
claim stays honest. It is real write-back, not a claim: every clean entity gets the
`agent-safe-certified` tag, making scan status queryable in the same catalog every
agent already uses.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .cure import CONTENT_SHA_PROP, LAST_SCANNED_PROP, canonical_content
from .gateway import Gateway
from .scan import CERTIFIED_TAG


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class CertifyResult:
    certified: int = 0

    def summary(self) -> str:
        return f"certified {self.certified} clean entities `{CERTIFIED_TAG}` (+ content hash)"


def certify(gateway: Gateway, clean_urns: list[str], *,
            now: str = "certify") -> CertifyResult:
    """Tag each clean entity `agent-safe-certified` AND stamp `antigen.contentSha256`.

    Stamping the hash here is what makes certification a *standing* control: `rescan`
    re-hashes every stamped entity, so a certified-clean entity whose content later
    changes is auto-re-flagged. Without the stamp, certification would silently rot.
    """
    result = CertifyResult()
    for ent in gateway.get_entities(clean_urns):
        gateway.add_tags(ent.urn, [CERTIFIED_TAG])
        gateway.add_structured_properties(ent.urn, {
            CONTENT_SHA_PROP: _sha256(canonical_content(ent)),
            LAST_SCANNED_PROP: now,
        })
        result.certified += 1
    return result

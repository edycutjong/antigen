"""antigen rescan — the standing tamper-evident loop (proves the defense stands).

Re-reads live content via `get_entities`, re-hashes the current cleaned field, and
compares it to the `antigen.contentSha256` stamped at cure time. A mismatch means the
field changed after certification — a new edit (possibly a fresh injection) — and is
auto-re-flagged for rescan. This is what makes Antigen a *standing control*, not a
one-shot: certification cannot silently rot.

Exposed to CI as `antigen scan --fail-on-hit`: a non-empty drift/hit list exits non-zero.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .cure import CONTENT_SHA_PROP, canonical_content
from .gateway import Gateway


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class RescanResult:
    drifted: list[str] = field(default_factory=list)     # stamped but content changed
    stamped_checked: int = 0

    @property
    def clean(self) -> bool:
        return not self.drifted

    def summary(self) -> str:
        return (f"rescanned {self.stamped_checked} stamped entities | "
                f"{len(self.drifted)} drifted since certification")


def rescan(gateway: Gateway, stamped_urns: list[str]) -> RescanResult:
    result = RescanResult()
    for ent in gateway.get_entities(stamped_urns):
        stamped = ent.structured_properties.get(CONTENT_SHA_PROP)
        if not stamped:
            continue
        result.stamped_checked += 1
        current = _sha256(canonical_content(ent))
        if current != stamped:
            result.drifted.append(ent.urn)
    return result

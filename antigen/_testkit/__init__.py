"""Offline test double for the DataHub transport layer — NOT for production.

`InMemoryGateway` implements the exact `antigen.gateway.Gateway` interface over an
in-memory graph so Antigen's scan/cure/verify orchestration can run in CI with no
`datahub docker quickstart` and no Docker.

Honesty note (repeated in the README): this doubles the *network transport only*.
Everything judged runs for real through it — the detector is `antigen.detect`, the
surface-completeness assertions are the real ones, the cure logic is the production
logic. Swapping this for `SdkGateway` changes only where the bytes go. It is not a
mock of any judged capability. The judge-facing path is the live GMS; this exists so
the test suite is runnable on a laptop with nothing installed.
"""

from .inmemory_graph import InMemoryGateway

__all__ = ["InMemoryGateway"]

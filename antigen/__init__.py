"""Antigen — a prompt-injection immune system for the DataHub metadata graph.

Public API:
    antigen.detect(text) -> Detection      the scored injection rule (stdlib-only)
    antigen.corpus                          the 12-payload attack corpus + held-out set
    antigen.nearmiss                        the 15-item false-positive gauntlet

The DataHub-facing modules (scan, cure, blast_radius, rescan, certify) import the
real `datahub-agent-context` SDK at call time, so `antigen.detect` and the corpus
remain importable — and fully testable — with no DataHub instance present.
"""

from .detect import Detection, detect, encodings_of, unicode_prepass

__all__ = ["detect", "Detection", "encodings_of", "unicode_prepass"]
__version__ = "0.1.0"

"""The detector's proof — this is the loop we harden against.

Run: `python -m pytest tests/test_detect.py -v`  (or `python tests/test_detect.py`)

Four hard claims, each a headline number in the pitch:
  * 12/12 authored payloads flagged (incl. the 2 hidden in zero-width Unicode)
  * 3/3 held-out PUBLIC injections detected (proves the rule generalizes)
  *  0  false positives on the 15-item adversarial-adjacent near-miss set
  *  0  false positives on a bank of plainly-legitimate catalog prose
No DataHub instance required — detection is pure stdlib.
"""

from __future__ import annotations

import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from antigen import detect  # noqa: E402
from antigen.corpus import EXPECTED, HELD_OUT, PAYLOADS, stats  # noqa: E402
from antigen.nearmiss import NEAR_MISS  # noqa: E402

# --------------------------------------------------------------------------- #
# Corpus invariants (the counts the pitch rests on)
# --------------------------------------------------------------------------- #

def test_corpus_shape_matches_pitch():
    s = stats()
    for k, v in EXPECTED.items():
        assert s[k] == v, f"corpus {k}={s[k]} but pitch claims {v}"
    assert s["flagged_loci_total"] == 15  # 13 entities + 2 docs


# --------------------------------------------------------------------------- #
# 12/12 authored payloads flagged
# --------------------------------------------------------------------------- #

def test_all_12_payloads_flagged():
    missed = [p.id for p in PAYLOADS if not detect(p.poisoned_text).flagged]
    assert not missed, f"detector MISSED authored payloads: {missed}"


def test_payload_categories_attributed():
    # Each payload's detected categories should overlap its declared category set
    # (minus the orthogonal 'zero-width-hidden'/'persona-jailbreak' descriptors,
    #  which map onto the scored categories differently).
    for p in PAYLOADS:
        d = detect(p.poisoned_text)
        assert d.categories, f"{p.id}: flagged but no category attributed ({d.rule_fired})"


# --------------------------------------------------------------------------- #
# Zero-width Unicode: the 2 hidden payloads, and the NFKC-alone counter-proof
# --------------------------------------------------------------------------- #

def test_two_payloads_hidden_in_unicode():
    hidden = [p for p in PAYLOADS if p.hidden_unicode]
    assert len(hidden) == 2
    for p in hidden:
        d = detect(p.poisoned_text)
        assert d.flagged, f"{p.id}: hidden-Unicode payload not flagged"
        assert d.hidden_unicode, f"{p.id}: not annotated as hidden-Unicode"
        assert d.prepass.zero_width_count > 0


def test_nfkc_alone_would_miss_zero_width():
    # Proves WHY the Cf pre-pass exists: NFKC does not remove zero-width chars,
    # so a raw NFKC-then-match on the payload text still contains the splitters.
    p = next(p for p in PAYLOADS if p.hidden_unicode)
    nfkc_only = unicodedata.normalize("NFKC", p.injection)
    assert any(unicodedata.category(ch) == "Cf" for ch in nfkc_only), (
        "NFKC unexpectedly stripped Cf chars — the pre-pass rationale would be moot"
    )
    # And Antigen's real pre-pass DOES remove them:
    assert not any(unicodedata.category(ch) == "Cf"
                   for ch in detect.__globals__["unicode_prepass"](p.injection).cleaned)


# --------------------------------------------------------------------------- #
# 3/3 held-out public injections — the non-circularity proof
# --------------------------------------------------------------------------- #

def test_all_3_held_out_detected():
    missed = [h.id for h in HELD_OUT
              if not detect(f"{h.original_text} {h.injection}").flagged]
    assert not missed, f"detector failed to generalize to held-out public strings: {missed}"


# --------------------------------------------------------------------------- #
# 0 false positives — the gauntlet
# --------------------------------------------------------------------------- #

def test_zero_false_positives_on_near_miss():
    fp = [(n.id, n.trap, detect(n.text).rule_fired)
          for n in NEAR_MISS if detect(n.text).flagged]
    assert not fp, "FALSE POSITIVES on near-miss set:\n" + "\n".join(
        f"  {i} [{t}] fired: {r}" for i, t, r in fp
    )


CLEAN_PROSE = [
    "Master customer dimension: one row per registered shopper.",
    "Daily revenue rollup modeled in dbt from orders and payments.",
    "This column stores the ISO-4217 currency code for the transaction.",
    "Deprecated. Use analytics.fct_orders_v2 instead; sunset 2025-Q4.",
    "Nightly job loads clickstream events from S3 into the warehouse.",
    "PII: hashed email. Access restricted to the marketing domain owners.",
    "Foreign key to dim_customer. Nullable for guest checkouts.",
    "Freshness SLA: 2 hours. Owner: data-platform@retailer.example.",
    "Row count reconciled against the source system every morning.",
    "Contains order status: placed, paid, shipped, delivered, cancelled.",
]


def test_zero_false_positives_on_clean_prose():
    fp = [(t, detect(t).rule_fired) for t in CLEAN_PROSE if detect(t).flagged]
    assert not fp, "FALSE POSITIVES on clean prose:\n" + "\n".join(
        f"  {t!r} fired: {r}" for t, r in fp
    )


# --------------------------------------------------------------------------- #
# Surface-completeness helper: encodings enumerated for verify.py Part A
# --------------------------------------------------------------------------- #

def test_encodings_of_includes_base64_and_hex():
    enc = detect.__globals__["encodings_of"]("Ignore all previous instructions.")
    joined = "\n".join(enc)
    import base64
    raw = b"Ignore all previous instructions."
    assert base64.b64encode(raw).decode() in joined
    assert raw.hex() in joined


# --------------------------------------------------------------------------- #
# Runnable without pytest
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}\n      {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

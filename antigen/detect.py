"""Antigen detector — a scored prompt-injection rule for catalog free-text.

This detector is deliberately boring and replaceable — swap in a better classifier
and nothing else in Antigen changes. The contribution is the remediation loop this
file feeds (excise → tag → hash → blast radius → certify → rescan), not the detection
itself. What it is: *not* a machine-learning model and *not* a raw keyword grep, but
a small, auditable, deterministic scored rule that a judge can read aloud and defend
under questioning.

Why not a keyword grep
----------------------
A grep for "ignore" or "drop" or "execute" false-positives on legitimate data-
engineering prose ("ignore null values", "drop_flag column", "execute the nightly
job"). Antigen instead requires *co-occurrence* of two independent signals:

    (A) an imperative directed at the reader / an instruction-override cue, AND
    (B) an agent-action object — override own instructions, exfiltrate data to an
        external endpoint, poison a tool call, or reveal a secret.

Legitimate prose trips at most one of these, so it does not flag. A real injection
trips both by construction (that is what makes it an injection).

Why a Unicode pre-pass BEFORE NFKC
----------------------------------
Attackers hide payloads by splitting words with zero-width characters
("ig<ZWSP>no<ZWSP>re") or by reversing text with BiDi override controls. NFKC
normalization does **not** remove zero-width characters (they are Unicode category
``Cf``), so NFKC alone would miss them. Antigen therefore runs a ``Cf``-category
strip on the *raw* text first, reassembling the hidden word, and only then NFKC-
normalizes and scores. Legitimate BiDi marks used in real right-to-left business
names (LRM/RLM/ALM) are allowlisted so they never inflate the "hidden Unicode" count.

Everything here is Python standard library. No network, no LLM, no model file.
"""

from __future__ import annotations

import base64
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum

# --------------------------------------------------------------------------- #
# Unicode pre-pass
# --------------------------------------------------------------------------- #

# Genuine zero-width evasion characters (no legitimate use inside a description).
ZERO_WIDTH = {
    "​",  # ZERO WIDTH SPACE
    "‌",  # ZERO WIDTH NON-JOINER
    "‍",  # ZERO WIDTH JOINER
    "﻿",  # ZERO WIDTH NO-BREAK SPACE / BOM
    "⁠",  # WORD JOINER
}

# BiDi *override/embedding* controls. Unbalanced use of these is an evasion signal
# (RLO/LRO can visually reverse a payload so a human reviewer never reads it).
BIDI_FORMATTING = {
    "‪",  # LEFT-TO-RIGHT EMBEDDING
    "‫",  # RIGHT-TO-LEFT EMBEDDING
    "‬",  # POP DIRECTIONAL FORMATTING
    "‭",  # LEFT-TO-RIGHT OVERRIDE
    "‮",  # RIGHT-TO-LEFT OVERRIDE
    "⁦",  # LEFT-TO-RIGHT ISOLATE
    "⁧",  # RIGHT-TO-LEFT ISOLATE
    "⁨",  # FIRST STRONG ISOLATE
    "⁩",  # POP DIRECTIONAL ISOLATE
}

# Legitimate directional marks that appear in real RTL business/entity names.
# Allowlisted: their mere presence is NOT counted as hidden-Unicode evasion.
ALLOWLISTED_BIDI = {
    "‎",  # LEFT-TO-RIGHT MARK
    "‏",  # RIGHT-TO-LEFT MARK
    "؜",  # ARABIC LETTER MARK
}


@dataclass
class UnicodePrepass:
    """Result of the raw-text Unicode pre-pass."""

    cleaned: str  # text with all Cf-category chars removed (word-reassembled)
    hidden_unicode: bool  # zero-width evasion or unbalanced BiDi override present
    zero_width_count: int
    bidi_override_count: int
    stripped_codepoints: list[str] = field(default_factory=list)


def unicode_prepass(text: str) -> UnicodePrepass:
    """Strip Cf-category characters and flag zero-width / BiDi-override evasion.

    Returns the de-obfuscated string (used for scoring) plus whether genuine
    hidden-Unicode evasion was detected (used for the "2 hidden in Unicode" count).
    """
    cleaned_chars: list[str] = []
    zero_width = 0
    bidi_override = 0
    stripped: list[str] = []
    bidi_depth = 0
    unbalanced_bidi = False

    for ch in text:
        cat = unicodedata.category(ch)
        if cat == "Cf":
            stripped.append(f"U+{ord(ch):04X}")
            # Drop the char from the scoring text (this reassembles split words).
            if ch in ALLOWLISTED_BIDI:
                # Legitimate mark: removed from scoring text but not an evasion signal.
                continue
            if ch in ZERO_WIDTH:
                zero_width += 1
                continue
            if ch in BIDI_FORMATTING:
                bidi_override += 1
                if ch in ("‪", "‫", "‭", "‮",
                          "⁦", "⁧", "⁨"):
                    bidi_depth += 1
                elif ch in ("‬", "⁩"):
                    if bidi_depth == 0:
                        unbalanced_bidi = True
                    else:
                        bidi_depth -= 1
                continue
            # Any other Cf char: strip but treat conservatively as zero-width-like.
            zero_width += 1
            continue
        cleaned_chars.append(ch)

    if bidi_depth != 0:
        unbalanced_bidi = True

    hidden = zero_width > 0 or (bidi_override > 0 and unbalanced_bidi)
    return UnicodePrepass(
        cleaned="".join(cleaned_chars),
        hidden_unicode=hidden,
        zero_width_count=zero_width,
        bidi_override_count=bidi_override,
        stripped_codepoints=stripped,
    )


# --------------------------------------------------------------------------- #
# Signal bank (the scored rule)
# --------------------------------------------------------------------------- #

class Category(str, Enum):
    OVERRIDE = "instruction-override"
    EXFIL = "data-exfiltration"
    TOOL_POISON = "tool-poisoning"
    REVEAL_SECRET = "reveal-secret"


# (A) Instruction-override: an imperative to disregard prior/own instructions.
# Anchored so "ignore null values" / "disregard test schemas" do NOT match — the
# object must be the model's own instructions/prompt/policy, not arbitrary nouns.
_OVERRIDE_RE = re.compile(
    r"\b(?:ignore|disregard|forget|override|bypass|do\s+not\s+follow|"
    r"pay\s+no\s+attention\s+to)\b[^.\n]{0,40}?\b"
    r"(?:all\s+|any\s+|the\s+|your\s+|previous\s+|prior\s+|earlier\s+|above\s+)*"
    r"(?:previous|prior|earlier|above|preceding|foregoing|prior)?\s*"
    r"(?:instruction|instructions|direction|directions|directive|directives|"
    r"prompt|prompts|system\s+prompt|rule|rules|guardrail|guardrails|"
    r"guideline|guidelines|content\s+polic(?:y|ies)|content\s+moderation|"
    r"restriction|restrictions|constraint|constraints)\b",
    re.IGNORECASE,
)

# Persona-override jailbreaks ("you are now DAN", "act as an unrestricted ...").
_PERSONA_RE = re.compile(
    r"\b(?:you\s+are\s+now|from\s+now\s+on\s+you\s+are|act\s+as|pretend\s+to\s+be|"
    r"you\s+are\s+(?:no\s+longer|an?\s+unrestricted))\b[^.\n]{0,40}?"
    r"\b(?:dan|do\s+anything\s+now|jailbroken|unrestricted|developer\s+mode|"
    r"no\s+restrictions|without\s+(?:any\s+)?(?:restrictions|filter|guardrails))\b",
    re.IGNORECASE,
)

# (B) Exfiltration: a transfer verb + a sensitive object + an external destination.
_TRANSFER_RE = re.compile(
    r"\b(?:send|export|exfiltrate|leak|upload|post|email|forward|transmit|"
    r"deliver|dump|copy|curl|fetch|ship)\b",
    re.IGNORECASE,
)
_SENSITIVE_OBJ_RE = re.compile(
    r"\b(?:customer|user|client)?\s*(?:e-?mail(?:\s+address(?:es)?)?|"
    r"api[\s_-]?key|api[\s_-]?keys|token|tokens|password|passwords|credential|"
    r"credentials|secret|secrets|private\s+key|ssn|social\s+security|"
    r"pii|personal\s+data|contents\s+of|records|rows|the\s+\w+\s+table)\b",
    re.IGNORECASE,
)
_DESTINATION_RE = re.compile(
    r"(?:https?://|ftp://|www\.)\S+"                       # a URL
    r"|\b[\w.+-]+@[\w-]+\.[\w.-]+\b"                       # an email address
    r"|\bto\s+(?:an?\s+)?(?:external|remote|third[\s-]party|attacker)\b",
    re.IGNORECASE,
)

# (C) Tool poisoning: an imperative to call/invoke a tool or run a command,
# directed at the reader (the agent), typically to do something out-of-band.
_TOOL_POISON_RE = re.compile(
    r"\b(?:call|invoke|use|run|execute|trigger)\b\s+(?:the\s+)?"
    r"(?:following\s+)?"
    r"(?:tool|function|command|"
    r"update_description|add_tags|get_entities|save_document|search|"
    r"add_structured_properties|add_owners|set_domains|remove_tags|"
    r"grep_documents|get_lineage)\b",
    re.IGNORECASE,
)
_TOOL_POISON_CTX_RE = re.compile(
    r"\b(?:whenever|when|every\s+time|each\s+time|as\s+soon\s+as)\b[^.\n]{0,60}?"
    r"\b(?:call|invoke|use|run|execute)\b",
    re.IGNORECASE,
)

# (D) Reveal-secret: an imperative to reveal/print/output a secret or the prompt.
_REVEAL_RE = re.compile(
    r"\b(?:reveal|print|show|output|display|disclose|repeat|dump|expose|tell\s+me)\b"
    r"[^.\n]{0,40}?\b(?:system\s+prompt|your\s+(?:prompt|instructions|"
    r"system\s+prompt|configuration)|api[\s_-]?keys?|passwords?|"
    r"credentials?|secrets?|"
    # `tokens?` bare flags "Total output tokens generated" — an LLM-cost column,
    # now ubiquitous in warehouses, and a homonym of the auth token this rule
    # means. Measured over the 38,031-description false-positive study: the bare
    # plural added exactly one false positive and zero true positives. So the
    # plural must be credential-qualified, while the bare singular stays exactly
    # as it always was — no recall is given up relative to the shipped detector.
    r"(?:access|auth|bearer|refresh|session|api)[\s_-]?tokens?|token|"
    r"hidden\s+(?:instructions|rules))\b",
    re.IGNORECASE,
)

# Reader-directed cue: 2nd-person address or a bare leading imperative — evidence
# the text is talking TO the assistant, not describing data.
_READER_DIRECTED_RE = re.compile(
    r"\b(?:you|your|you're|yourself|assistant|as\s+an?\s+ai|language\s+model)\b",
    re.IGNORECASE,
)

# Injection-preamble cue: the "new instruction:" / "system:" framing an attacker
# uses to smuggle a fresh instruction block. Deliberately narrow — "Instructions
# for analysts:" (a legitimate doc heading) does NOT match, because the adjective
# 'new/updated/revised/additional' is required.
_INJECTION_PREAMBLE_RE = re.compile(
    r"\b(?:new|updated|revised|additional|urgent|important)\s+"
    r"(?:instruction|instructions|directive|directives|task|"
    r"system\s+prompt|rule|rules)\b\s*[:\-]?"
    r"|\bsystem\s*:\s*(?:override|ignore|you\s+are)",
    re.IGNORECASE,
)

# Negation guard: an affirmative reveal/exfil verb preceded closely by a negation
# ("must not expose", "never send", "do not reveal") is defensive prose, not injection.
_NEGATION_RE = re.compile(
    r"\b(?:not|never|don't|do\s+not|must\s+not|should\s+not|cannot|can't|"
    r"avoid|prevent|prohibit)\b",
    re.IGNORECASE,
)


def _negated(text: str, match_start: int) -> bool:
    """True if a negation word appears within ~24 chars before the match."""
    window = text[max(0, match_start - 24):match_start]
    return bool(_NEGATION_RE.search(window))


# --------------------------------------------------------------------------- #
# Detection result
# --------------------------------------------------------------------------- #

@dataclass
class Detection:
    """Outcome of scoring one free-text field.

    ``rule_fired`` quotes the matched injection span and is for LOCAL CLI display /
    debugging only — it must NEVER be written back to the graph, because a quoted
    imperative is still an imperative an LLM can obey. Everything Antigen writes to
    the graph (banner, forensic report) uses ``signals`` instead: fixed category
    labels that carry no payload text.
    """

    flagged: bool
    score: int
    categories: list[Category]
    rule_fired: str            # quotes payload spans — CLI/debug only, never persisted
    signals: list[str]         # SAFE labels (no payload text) — persisted to the graph
    hidden_unicode: bool
    matched_span: tuple[int, int] | None  # (start, end) in the ORIGINAL text
    matched_text: str | None
    prepass: UnicodePrepass

    @property
    def safe_summary(self) -> str:
        """A graph-safe description of why the field flagged (no payload text)."""
        parts = list(self.signals)
        if self.hidden_unicode:
            parts.append("zero-width-unicode-evasion")
        return ", ".join(parts) if parts else "no-signal"

    def as_dict(self) -> dict:
        return {
            "flagged": self.flagged,
            "score": self.score,
            "categories": [c.value for c in self.categories],
            "signals": self.signals,
            "hidden_unicode": self.hidden_unicode,
            "matched_span": list(self.matched_span) if self.matched_span else None,
            "zero_width_count": self.prepass.zero_width_count,
            "bidi_override_count": self.prepass.bidi_override_count,
        }


# Score threshold: a field flags at score >= 2, i.e. one strong (A)-cue plus one
# (B)-object, OR one self-contained strong signal (persona jailbreak / secret
# reveal / exfil-with-destination) that is worth 2 on its own.
FLAG_THRESHOLD = 2


def detect(text: str | None) -> Detection:
    """Score a single free-text field for prompt injection.

    Deterministic, stdlib-only. Returns a :class:`Detection`; ``flagged`` is the
    headline boolean, ``categories`` explains why, and ``matched_span`` (in the
    *original* text coordinates, best-effort) lets the cure excise the payload.
    """
    if not text:
        return Detection(False, 0, [], "empty", [], False, None, None,
                         UnicodePrepass("", False, 0, 0, []))

    prepass = unicode_prepass(text)
    # NFKC folds compatibility/fullwidth homoglyph variants onto their ASCII form,
    # catching a subset of homoglyph evasion (full TR39 confusables = future work).
    norm = unicodedata.normalize("NFKC", prepass.cleaned)

    score = 0
    categories: list[Category] = []
    reasons: list[str] = []       # quotes payload spans — CLI/debug only
    signals: list[str] = []       # safe labels — persisted to the graph
    reader_directed = bool(_READER_DIRECTED_RE.search(norm))

    #: Match objects for every rule that CONTRIBUTED SCORE, accumulated as we go and
    #: handed to `_locate_span` below. This is a list built by the scoring branches
    #: themselves rather than a hand-picked tuple assembled afterwards, and that is
    #: the whole point: the previous version passed a fixed
    #: `[m_override, m_persona, m_reveal, m_tool]`, so any hit that flagged on a rule
    #: outside those four got `matched_span is None` and `--excise-span` declined
    #: without ever attempting a cut.
    #:
    #: That was not an edge case. Measured against this project's own
    #: `docs/false-positive-study.md`, **23 of the 24 real flagged descriptions score 2
    #: on `data-exfiltration` alone** — a rule whose matches were not in that tuple —
    #: so span excision fired on 1 of 24 and whole-field quarantine destroyed ~42 k
    #: characters of hand-written documentation. The demo corpus hid it completely,
    #: because 11 of its 15 loci happen to trip override/persona/tool/reveal.
    #:
    #: Invariant, and it is now structural: **a rule that can add score must append
    #: its match here.** Every scoring branch below does. `tests/test_containment.py::
    #: test_every_scoring_rule_can_yield_a_span` re-derives that over the whole rule
    #: set rather than trusting this comment.
    span_matches: list[re.Match] = []

    # --- injection preamble ("new instruction:", "system: override") ------
    m_preamble = _INJECTION_PREAMBLE_RE.search(norm)
    if m_preamble:
        score += 1
        reasons.append(f"injection-preamble ({m_preamble.group(0).strip()!r})")
        signals.append("injection-preamble")
        span_matches.append(m_preamble)

    # --- (A) instruction override -----------------------------------------
    m_override = _OVERRIDE_RE.search(norm)
    if m_override:
        score += 2
        categories.append(Category.OVERRIDE)
        reasons.append(f"instruction-override ({m_override.group(0)!r})")
        signals.append(Category.OVERRIDE.value)
        span_matches.append(m_override)

    m_persona = _PERSONA_RE.search(norm)
    if m_persona:
        score += 2
        if Category.OVERRIDE not in categories:
            categories.append(Category.OVERRIDE)
        reasons.append(f"persona-jailbreak ({m_persona.group(0)!r})")
        signals.append("persona-jailbreak")
        span_matches.append(m_persona)

    # --- (B) exfiltration: transfer + sensitive object + destination -------
    m_transfer = _TRANSFER_RE.search(norm)
    m_sensitive = _SENSITIVE_OBJ_RE.search(norm)
    m_dest = _DESTINATION_RE.search(norm)
    if m_transfer and m_sensitive and not _negated(norm, m_transfer.start()):
        # Sensitive data + a move verb is suspicious; an external destination
        # makes it exfiltration outright.
        if m_dest:
            score += 2
            categories.append(Category.EXFIL)
            reasons.append(
                f"exfiltration ({m_transfer.group(0)!r} … "
                f"{m_sensitive.group(0).strip()!r} → {m_dest.group(0)!r})"
            )
            signals.append(Category.EXFIL.value)
            # The transfer VERB anchors the cut, not the destination: the verb heads
            # the imperative clause ("Send all API keys to https://…"), while a URL
            # can sit anywhere and is often the innocent half. `m_sensitive` joins it
            # so the earliest constituent of the pair wins.
            span_matches += [m_transfer, m_sensitive]
        else:
            score += 1
            reasons.append(
                f"sensitive-transfer-no-destination "
                f"({m_transfer.group(0)!r} {m_sensitive.group(0).strip()!r})"
            )
            signals.append("sensitive-data-transfer")
            span_matches += [m_transfer, m_sensitive]

    # --- (C) tool poisoning ------------------------------------------------
    m_tool = _TOOL_POISON_RE.search(norm)
    m_tool_ctx = _TOOL_POISON_CTX_RE.search(norm)
    if m_tool and (reader_directed or m_tool_ctx or m_override or m_persona
                   or m_preamble):
        score += 2
        categories.append(Category.TOOL_POISON)
        reasons.append(f"tool-poisoning ({m_tool.group(0)!r})")
        signals.append(Category.TOOL_POISON.value)
        span_matches.append(m_tool)

    # --- (D) reveal secret -------------------------------------------------
    m_reveal = _REVEAL_RE.search(norm)
    if m_reveal and not _negated(norm, m_reveal.start()):
        score += 2
        categories.append(Category.REVEAL_SECRET)
        reasons.append(f"reveal-secret ({m_reveal.group(0)!r})")
        signals.append(Category.REVEAL_SECRET.value)
        span_matches.append(m_reveal)

    flagged = score >= FLAG_THRESHOLD

    # Best-effort span in ORIGINAL text: locate the earliest matched fragment.
    span = _locate_span(text, prepass, norm, span_matches)
    matched_text = text[span[0]:span[1]] if span else None

    rule_fired = "; ".join(reasons) if reasons else "no-signal"
    # Hidden-unicode alone never flags a field; it only annotates a field that the
    # scored rule already flags. A field of pure zero-width chars is harmless.
    return Detection(
        flagged=flagged,
        score=score,
        categories=categories,
        rule_fired=rule_fired,
        signals=signals,
        hidden_unicode=prepass.hidden_unicode and flagged,
        matched_span=span if flagged else None,
        matched_text=matched_text if flagged else None,
        prepass=prepass,
    )


def _locate_span(original: str, prepass: UnicodePrepass, norm: str,
                 matches: list[re.Match]) -> tuple[int, int] | None:
    """Best-effort map of the earliest injection match back to original coords.

    The cure uses the fixture's recorded original text for exact excision on the
    corpus; this span is the out-of-corpus / display fallback. Because the pre-pass
    stripped Cf chars, we anchor on the first matched fragment's leading token and
    search for it in the original (tolerating interleaved zero-width characters).
    """
    live = [m for m in matches if m]
    if not live:
        return None
    first = min(live, key=lambda m: m.start())
    fragment = norm[first.start():first.end()]
    # Try a direct find first.
    idx = original.lower().find(fragment.lower())
    if idx >= 0:
        return (idx, idx + len(fragment))
    # Fall back: anchor on the first alphabetic token, allowing Cf chars between
    # characters (handles zero-width-split payloads).
    token = re.search(r"[A-Za-z]{3,}", fragment)
    if token:
        chars = list(token.group(0))
        pattern = "".join(re.escape(c) + r"[​‌‍﻿⁠]*"
                          for c in chars)
        m = re.search(pattern, original, re.IGNORECASE)
        if m:
            # Extend to end of the sentence/line for a usable span.
            end = original.find("\n", m.start())
            end = len(original) if end < 0 else end
            return (m.start(), end)
    return (0, len(original))


# --------------------------------------------------------------------------- #
# Surface-completeness helpers (used by verify.py Part A)
# --------------------------------------------------------------------------- #

def encodings_of(payload: str) -> list[str]:
    """Return the payload plus its common recoverable encodings.

    verify.py asserts NONE of these strings survive on any agent-readable surface
    after the cure — proving the post-cure 0/12 is structural, not luck. If an
    attacker's payload could be base64/hex-decoded back by the LLM, leaving the
    encoded form on the graph would not be a real cure.
    """
    variants = {payload, payload.strip()}
    raw = payload.encode("utf-8", errors="ignore")
    variants.add(base64.b64encode(raw).decode("ascii"))
    variants.add(base64.b32encode(raw).decode("ascii"))
    variants.add(base64.b16encode(raw).decode("ascii"))  # hex, uppercase
    variants.add(raw.hex())                               # hex, lowercase
    variants.add(base64.urlsafe_b64encode(raw).decode("ascii"))
    return [v for v in variants if v]

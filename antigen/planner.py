"""antigen --dry-run — run the real engine, intercept every write.

A preview is only trustworthy if it is produced by the code that would do the work.
:class:`PlanningGateway` therefore wraps a real gateway, forwards every READ
untouched, and *records* each MUTATION as a :class:`PlannedMutation` instead of
executing it. `scan`, `cure`, `certify` and `blast_radius` are handed the wrapper and
never learn the difference, so the printed plan cannot drift from the behaviour.

Why this matters: `cure` writes 4 mutations per hit and `certify` writes 2 per *clean*
entity — on a 1k-entity catalog that is ~2,000 writes into a live production graph.
Before this module the only approval gate in the project was English prose in
`antigen-scan/SKILL.md` addressed to an LLM, which is a suggestion, not a control.

One caveat, stated in the printed plan rather than hidden: because nothing is written,
a read that a live run performs AFTER its own write (`cure` re-reads the cured entity
to hash it) sees pre-cure state here. That changes the *hash values* a live run would
stamp; it never changes the set of mutations or the before/after text shown.
"""

from __future__ import annotations

from dataclasses import dataclass

from .gateway import Document, Entity, Gateway

#: Free text is elided in the plan so a 2 kB description cannot bury the diff.
_ELIDE = 96
#: Longer shared prefixes are collapsed. An injection is usually APPENDED to
#: legitimate documentation, so a plain head-truncation of both sides would show two
#: identical lines and hide the only part an approver needs to look at.
_SHARED = 24


def _clip(text: str) -> str:
    return text if len(text) <= _ELIDE else text[: _ELIDE - 1] + "…"


def _short(text: str) -> str:
    collapsed = " ".join((text or "").split())
    return _clip(collapsed) if collapsed else "(empty)"


def _diff_pair(before: str, after: str) -> tuple[str, str]:
    """Render before/after with any long identical prefix collapsed."""
    b = " ".join((before or "").split())
    a = " ".join((after or "").split())
    shared = 0
    for x, y in zip(b, a, strict=False):   # deliberately stops at the shorter side
        if x != y:
            break
        shared += 1
    if shared <= _SHARED:
        return _short(b), _short(a)
    head = f"…{shared} identical chars…"
    return head + _clip(b[shared:]), head + _clip(a[shared:])


@dataclass
class PlannedMutation:
    """One write a live run would perform: which tool, where, and what changes."""

    tool: str
    urn: str
    field_path: str | None
    before: str
    after: str

    def render(self) -> str:
        loc = f" ::{self.field_path}" if self.field_path else ""
        before, after = _diff_pair(self.before, self.after)
        return (f"  {self.tool}  {self.urn}{loc}\n"
                f"      before: {before}\n"
                f"      after:  {after}")


class PlanningGateway:
    """Gateway decorator: READs pass through, MUTATIONs are recorded and dropped."""

    def __init__(self, inner: Gateway) -> None:
        self._inner = inner
        self.planned: list[PlannedMutation] = []
        # Entities the sweep already read. `before` values come from here, so a dry
        # run costs exactly the same reads as a live one — no extra round-trips.
        self._seen: dict[str, Entity] = {}

    # -- READ: straight through (and cached) ------------------------------ #
    def search_all(self) -> list[str]:
        return self._inner.search_all()

    def get_entities(self, urns: list[str]) -> list[Entity]:
        entities = self._inner.get_entities(urns)
        for ent in entities:
            self._seen[ent.urn] = ent
        return entities

    def get_entity(self, urn: str) -> Entity | None:
        ent = self._inner.get_entity(urn)
        if ent is not None:
            self._seen[ent.urn] = ent
        return ent

    def grep_documents(self, pattern: str) -> list[Document]:
        return self._inner.grep_documents(pattern)

    def get_lineage(self, urn: str, direction: str = "downstream",
                    hops: int = 2) -> list[str]:
        return self._inner.get_lineage(urn, direction=direction, hops=hops)

    def get_document(self, parent: str, title: str) -> Document | None:
        return self._inner.get_document(parent, title)

    def degradations(self) -> list[str]:
        """Forward the wrapped gateway's degraded-read log (see `scan`)."""
        return list(getattr(self._inner, "degradations", list)())

    # -- MUTATION: recorded, never executed ------------------------------- #
    def _before_description(self, urn: str, field_path: str | None) -> str:
        ent = self._seen.get(urn)
        if ent is None:
            return "(not read in this pass)"
        if field_path is None:
            return ent.description
        col = ent.columns.get(field_path)
        return col.description if col is not None else "(column not read)"

    def update_description(self, urn: str, description: str,
                           field_path: str | None = None) -> None:
        self.planned.append(PlannedMutation(
            "update_description", urn, field_path,
            self._before_description(urn, field_path), description))

    def add_tags(self, urn: str, tags: list[str],
                 field_path: str | None = None) -> None:
        ent = self._seen.get(urn)
        current = list(ent.tags) if ent is not None else []
        self.planned.append(PlannedMutation(
            "add_tags", urn, field_path,
            ", ".join(current),
            ", ".join(current + [t for t in tags if t not in current])))

    def add_structured_properties(self, urn: str, properties: dict[str, str]) -> None:
        ent = self._seen.get(urn)
        current = ent.structured_properties if ent is not None else {}
        for key, value in properties.items():
            self.planned.append(PlannedMutation(
                "add_structured_properties", urn, key,
                current.get(key, "(unset)"), value))

    def save_document(self, title: str, content: str,
                      parent: str = "Antigen/Incidents",
                      urn: str | None = None) -> None:
        self.planned.append(PlannedMutation(
            "save_document", urn or f"(new document under {parent})", title,
            "(overwrite existing document)" if urn else "(no such document yet)",
            content))


def format_plan(planned: list[PlannedMutation], *, command: str) -> str:
    """Render the mutation plan an operator has to approve."""
    if not planned:
        return (f"DRY RUN — `antigen {command}` would write NOTHING "
                "(no hits, or nothing left to change).")
    by_tool: dict[str, int] = {}
    for m in planned:
        by_tool[m.tool] = by_tool.get(m.tool, 0) + 1
    breakdown = ", ".join(f"{n}× {t}" for t, n in sorted(by_tool.items()))
    return "\n".join([
        f"DRY RUN — `antigen {command}` would write {len(planned)} mutations "
        f"({breakdown}). Nothing was written.",
        *(m.render() for m in planned),
        "",
        f"Re-run with --apply to execute this plan: antigen {command} --apply",
        "(Tamper-evidence hashes are computed from post-write state, so a live run "
        "stamps values this preview cannot show. The mutation set is exact.)",
    ])

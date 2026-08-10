"""antigen --dry-run — run the real engine, intercept every write.

A preview is only trustworthy if it is produced by the code that would do the work.
:class:`PlanningGateway` therefore wraps a real gateway, forwards every READ
untouched, and *records* each MUTATION as a :class:`PlannedMutation` instead of
executing it. `scan`, `cure`, `certify` and `blast_radius` are handed the wrapper and
never learn the difference, so the printed plan cannot drift from the behaviour.

Why this matters: `cure` writes 4 tool calls per entity/column hit (2 for a KB-document
hit) and `certify` writes 2 per *clean* entity — on a 1k-entity catalog that is ~2,000
writes into a live production graph. Before this module the only approval gate in the
project was English prose in `antigen-scan/SKILL.md` addressed to an LLM, which is a
suggestion, not a control.

Counting, exactly, because `--max-mutations` is sized off it: a plan ROW is one aspect
value and a plan CALL is one tool invocation. `add_structured_properties` writes three
values (`cure`) or two (`certify`) in a single call, so the 12-payload corpus plans
**64 rows / 44 calls** and certifying its 28 clean entities plans **84 rows / 56
calls**. `BudgetedGateway` charges calls; `format_plan` prints both.

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


def elide(text: str) -> str:
    """One elision policy for every operator-facing preview in the project.

    Public because `cure`'s span-excision preview renders alongside the plan and has
    to clip the same way: two truncation rules on one screen is how an approver comes
    to trust a diff that is hiding something.
    """
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
        return elide(b), elide(a)
    head = f"…{shared} identical chars…"
    return head + _clip(b[shared:]), head + _clip(a[shared:])


@dataclass
class PlannedMutation:
    """One write a live run would perform: which tool, where, and what changes.

    ``call`` is the index of the TOOL CALL that produces this row. One
    `add_structured_properties` call writes several property values and is rendered as
    one row per value — genuinely what an approver needs to read — so rows and calls
    are not the same count, and `--max-mutations` charges CALLS. Carrying the index
    lets `format_plan` state both instead of leaving an operator to size the circuit
    breaker off a number that measures something else.
    """

    tool: str
    urn: str
    field_path: str | None
    before: str
    after: str
    call: int = 0
    #: One extra operator-facing line, rendered only when set. Used for the graph
    #: EDGES a `save_document` carries (`related_assets` / `related_documents`),
    #: which are neither a before nor an after but are part of what gets written.
    note: str = ""

    def render(self) -> str:
        loc = f" ::{self.field_path}" if self.field_path else ""
        before, after = _diff_pair(self.before, self.after)
        lines = [f"  {self.tool}  {self.urn}{loc}",
                 f"      before: {before}",
                 f"      after:  {after}"]
        if self.note:
            lines.append(f"      links:  {self.note}")
        return "\n".join(lines)


class PlanningGateway:
    """Gateway decorator: READs pass through, MUTATIONs are recorded and dropped."""

    def __init__(self, inner: Gateway) -> None:
        self._inner = inner
        self.planned: list[PlannedMutation] = []
        # Entities the sweep already read. `before` values come from here, so a dry
        # run costs exactly the same reads as a live one — no extra round-trips.
        self._seen: dict[str, Entity] = {}
        #: Tool calls recorded so far — the unit `BudgetedGateway` charges.
        self.calls = 0

    def _record(self, *mutations: PlannedMutation) -> None:
        """Attach the current tool-call index to every row that call produces."""
        self.calls += 1
        for m in mutations:
            m.call = self.calls
            self.planned.append(m)

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
        self._record(PlannedMutation(
            "update_description", urn, field_path,
            self._before_description(urn, field_path), description))

    def add_tags(self, urn: str, tags: list[str],
                 field_path: str | None = None) -> None:
        ent = self._seen.get(urn)
        current = list(ent.tags) if ent is not None else []
        self._record(PlannedMutation(
            "add_tags", urn, field_path,
            ", ".join(current),
            ", ".join(current + [t for t in tags if t not in current])))

    def add_structured_properties(self, urn: str, properties: dict[str, str]) -> None:
        ent = self._seen.get(urn)
        current = ent.structured_properties if ent is not None else {}
        self._record(*(PlannedMutation(
            "add_structured_properties", urn, key,
            current.get(key, "(unset)"), value)
            for key, value in properties.items()))

    def save_document(self, title: str, content: str,
                      parent: str = "Antigen/Incidents",
                      urn: str | None = None,
                      related_assets: list[str] | None = None,
                      related_documents: list[str] | None = None) -> str | None:
        # The links are part of the write, so the approver sees them: a `save_document`
        # that also creates an edge back to the poisoned asset changes what appears on
        # that asset's page, which is not visible anywhere in a before/after diff.
        links = [f"related_assets={list(related_assets)}"] if related_assets else []
        if related_documents:
            links.append(f"related_documents={list(related_documents)}")
        self._record(PlannedMutation(
            "save_document", urn or f"(new document under {parent})", title,
            "(overwrite existing document)" if urn else "(no such document yet)",
            content, note="  ".join(links)))
        # Nothing was written, so there is no URN to report. Returning the synthetic
        # one a live run would NOT use is exactly the fabrication this removed.
        return None


class MutationBudgetExceeded(RuntimeError):
    """Raised by :class:`BudgetedGateway` instead of performing write ``limit + 1``."""

    def __init__(self, limit: int, written: int, tool: str, urn: str) -> None:
        self.limit = limit
        self.written = written
        self.tool = tool
        self.urn = urn
        super().__init__(
            f"--max-mutations {limit} reached: refused `{tool}` on {urn}. "
            f"{written} mutations were already written and are NOT rolled back — "
            "Antigen has no transaction across DataHub aspects. The remaining loci are "
            "untouched and still poisoned. Re-run to continue (cure skips entities it "
            "already quarantined and stamped) or raise the cap after reviewing what "
            "landed."
        )


class BudgetedGateway:
    """Gateway decorator that caps how many mutations one run may perform.

    READs pass through; the Nth+1 mutation raises :exc:`MutationBudgetExceeded` INSTEAD
    of being executed, so the cap is a hard bound on writes, not a post-hoc count.

    What this is: a circuit breaker for an unattended `--apply` run. It charges one
    unit per TOOL CALL — `cure` spends 4 per entity/column hit and 2 per KB-document
    hit, `certify` 2 per clean entity — so a misconfigured
    `DATAHUB_GMS_URL` pointed at the wrong catalog, or one badly-tuned detector change,
    is otherwise unbounded. What this is NOT: incremental scanning, or any claim about
    operating at catalog scale. It makes an unattended run survivable — it does not
    make it cheap, and a run that trips the cap has already written up to `limit`
    aspect versions that a human now has to look at.
    """

    def __init__(self, inner: Gateway, limit: int) -> None:
        self._inner = inner
        self._limit = limit
        self.written = 0

    def _spend(self, tool: str, urn: str) -> None:
        if self.written >= self._limit:
            raise MutationBudgetExceeded(self._limit, self.written, tool, urn)
        self.written += 1

    # -- READ: straight through ------------------------------------------- #
    def search_all(self) -> list[str]:
        return self._inner.search_all()

    def get_entities(self, urns: list[str]) -> list[Entity]:
        return self._inner.get_entities(urns)

    def get_entity(self, urn: str) -> Entity | None:
        return self._inner.get_entity(urn)

    def grep_documents(self, pattern: str) -> list[Document]:
        return self._inner.grep_documents(pattern)

    def get_lineage(self, urn: str, direction: str = "downstream",
                    hops: int = 2) -> list[str]:
        return self._inner.get_lineage(urn, direction=direction, hops=hops)

    def get_document(self, parent: str, title: str) -> Document | None:
        return self._inner.get_document(parent, title)

    def degradations(self) -> list[str]:
        return list(getattr(self._inner, "degradations", list)())

    # -- MUTATION: counted, then forwarded -------------------------------- #
    def update_description(self, urn: str, description: str,
                           field_path: str | None = None) -> None:
        self._spend("update_description", urn)
        self._inner.update_description(urn, description, field_path=field_path)

    def add_tags(self, urn: str, tags: list[str],
                 field_path: str | None = None) -> None:
        self._spend("add_tags", urn)
        self._inner.add_tags(urn, tags, field_path=field_path)

    def add_structured_properties(self, urn: str, properties: dict[str, str]) -> None:
        self._spend("add_structured_properties", urn)
        self._inner.add_structured_properties(urn, properties)

    def save_document(self, title: str, content: str,
                      parent: str = "Antigen/Incidents",
                      urn: str | None = None,
                      related_assets: list[str] | None = None,
                      related_documents: list[str] | None = None) -> str | None:
        self._spend("save_document", urn or f"(new document `{title}`)")
        return self._inner.save_document(title, content, parent=parent, urn=urn,
                                         related_assets=related_assets,
                                         related_documents=related_documents)


def format_plan(planned: list[PlannedMutation], *, command: str) -> str:
    """Render the mutation plan an operator has to approve."""
    if not planned:
        return (f"DRY RUN — `antigen {command}` would write NOTHING "
                "(no hits, or nothing left to change).")
    by_tool: dict[str, int] = {}
    for m in planned:
        by_tool[m.tool] = by_tool.get(m.tool, 0) + 1
    breakdown = ", ".join(f"{n}× {t}" for t, n in sorted(by_tool.items()))
    # The rows above are aspect VALUES; `--max-mutations` charges tool CALLS, and one
    # `add_structured_properties` call carries three of them. Sizing the breaker off
    # the headline count over-provisions it by ~45% on a `cure` plan, so the plan says
    # both numbers rather than leaving an operator to discover the difference at
    # exit 3 with a half-remediated catalog.
    calls = len({m.call for m in planned})
    return "\n".join([
        f"DRY RUN — `antigen {command}` would write {len(planned)} mutations "
        f"({breakdown}). Nothing was written.",
        *(m.render() for m in planned),
        "",
        f"Re-run with --apply to execute this plan: antigen {command} --apply",
        "(Tamper-evidence hashes are computed from post-write state, so a live run "
        "stamps values this preview cannot show. The mutation set is exact.)",
        f"({len(planned)} rows = {calls} tool calls; one add_structured_properties "
        f"call writes several values. --max-mutations counts CALLS, so "
        f"--max-mutations {calls} is the exact cap for this plan.)",
    ])

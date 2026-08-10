"""verify.py Part A as an integration test, plus corpus/near-miss regression guards.

Run: `python tests/test_verify.py`  or  `python -m pytest tests/test_verify.py -v`
"""

from __future__ import annotations

import contextlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import verify  # noqa: E402
from antigen.detect import detect  # noqa: E402
from antigen.nearmiss import NEAR_MISS  # noqa: E402


def test_part_a_gate_passes_offline():
    report = verify.part_a(live=False, verbose=False)
    assert report["pass"] is True
    assert report["held_out"] == 3
    # Part A is the <30s hard gate; offline it is milliseconds.
    assert report["elapsed_s"] < 30


def test_part_a_detects_tampering_regression():
    # If the cure ever left a payload on a readable surface, part_a must raise.
    # (Sanity: the real run passes, so no Failure is raised.)
    try:
        verify.part_a(live=False, verbose=False)
    except verify.Failure as f:  # pragma: no cover
        raise AssertionError(f"Part A regressed: {f}") from f


def test_near_miss_still_zero_fp():
    fp = [n.id for n in NEAR_MISS if detect(n.text).flagged]
    assert not fp, f"near-miss regressed to false positives: {fp}"


# --------------------------------------------------------------------------- #
# THE EXIT TAXONOMY at the entry points `cli.main` does not own
# --------------------------------------------------------------------------- #
# Exit 1 means ONE thing across this project: a working sweep found injections. It is
# what the shipped adopter CI template
# (`examples/ci/metadata-injection-scan.yml`) reads as "Antigen found prompt
# injections in catalog metadata". An infrastructure failure establishes nothing and
# must be exit 2. That was fixed in `cli.main` and missed in these three.


@contextlib.contextmanager
def _sdk_absent():
    """Impose "the live extras are not installed" instead of inheriting it.

    Both tests below say `without_the_sdk` in their names but used to prove it only
    by being run on a machine that happened to lack `acryl-datahub`. Once a reader
    follows the README's live-setup section the premise silently inverts and the
    calls go THROUGH: `verify.main(["--live", ...])` builds a real `SdkGateway`, and
    `seed_catalog.main([])` writes thirteen datasets into whatever catalog
    `$DATAHUB_GMS_URL` names and then waits up to 120 s for them to index. Both still
    returned 2 — so the assertions stayed green — but only because something further
    down happened to raise, which is luck, not a test. With no GMS listening they
    also spent 28 s each retrying, which is most of the suite's runtime in that
    configuration.

    Patched by hand rather than with `monkeypatch`, for the reason given on
    `test_verify_still_exits_1_on_a_real_finding`: `./run.sh` executes this module
    directly, where pytest fixtures do not exist.
    """
    import builtins

    real_import = builtins.__import__

    def blocked(name, *a, **k):
        if name.split(".")[0] in ("datahub", "datahub_agent_context"):
            raise ImportError("live extras not installed")
        return real_import(name, *a, **k)

    builtins.__import__ = blocked
    try:
        yield
    finally:
        builtins.__import__ = real_import


def test_verify_live_without_the_sdk_exits_2_not_1():
    """`verify.py --live` with no DataHub extras used to exit 1 with a traceback."""
    import io
    from contextlib import redirect_stderr

    err = io.StringIO()
    with redirect_stderr(err), _sdk_absent():
        rc = verify.main(["--live", "--no-hijack", "--quiet"])
    assert rc == 2, "a missing live dependency is not a finding"
    assert "COULD NOT RUN" in err.getvalue()
    assert "nothing about the catalog was determined" in err.getvalue()


def test_verify_offline_still_passes_and_exits_0():
    """The taxonomy change must not disturb the reproducible proof itself."""
    import io
    from contextlib import redirect_stdout

    out = io.StringIO()
    with redirect_stdout(out):
        rc = verify.main(["--no-hijack", "--quiet"])
    assert rc == 0 and "graph-state PASS" in out.getvalue()


def test_verify_still_exits_1_on_a_real_finding():
    """Exit 1 must keep meaning what it means — the fix must not swallow findings.

    Patched by hand rather than with the `monkeypatch` fixture: `./run.sh` executes
    this module directly (`python tests/test_verify.py`), where pytest fixtures do
    not exist and a fixture argument is a TypeError.
    """
    import io
    from contextlib import redirect_stderr

    def boom(**kw):
        raise verify.Failure("payload survived on a readable surface")

    original = verify.part_a
    verify.part_a = boom
    try:
        err = io.StringIO()
        with redirect_stderr(err):
            rc = verify.main(["--no-hijack", "--quiet"])
    finally:
        verify.part_a = original
    assert rc == 1 and "FAIL" in err.getvalue()


def test_seed_catalog_without_the_sdk_exits_2_not_1():
    import io
    from contextlib import redirect_stderr, redirect_stdout

    import seed_catalog

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err), _sdk_absent():
        rc = seed_catalog.main([])
    assert rc == 2 and "REFUSED" in err.getvalue()


# --------------------------------------------------------------------------- #
# `./run.sh live` must be re-runnable
# --------------------------------------------------------------------------- #

class _MintingGateway:
    """A double that mints a NEW document URN per save, exactly like a live GMS.

    The in-memory double keys documents on (parent, title) and overwrites, which is
    precisely why the duplication bug below never showed up offline.
    """

    def __init__(self):
        self.docs = {}          # urn -> (parent, title, content)
        self._n = 0
        self.entities = {}

    def search_all(self):
        return list(self.entities)

    def update_description(self, urn, description, field_path=None):
        self.entities[urn] = description

    def save_document(self, title, content, parent="Shared", urn=None,
                      related_assets=None, related_documents=None):
        if urn is None:
            self._n += 1
            urn = f"urn:li:document:shared-{self._n:04d}"   # a fresh URN, every time
        self.docs[urn] = (parent, title, content)

    def get_document(self, parent, title):
        from antigen.gateway import Document
        for urn, (p, t, c) in self.docs.items():
            if (p, t) == (parent, title):
                return Document(urn=urn, title=t, content=c, parent=p)
        return None


def test_seeding_the_corpus_twice_does_not_duplicate_the_kb_documents():
    """The defect: `seed_corpus` saved KB documents with no `urn`, so a live GMS
    minted a second copy each run — `./run.sh live` reported 14/12, then 16/12.

    Runs in a scratch directory because `plant()` writes the locus map into the CWD,
    and chdir'd by hand so `./run.sh`'s direct `python tests/test_verify.py` works.
    """
    import tempfile

    import seed_corpus
    from antigen.corpus import HELD_OUT, PAYLOADS, Locus

    expected_docs = sum(1 for p in PAYLOADS if p.locus is Locus.KB_DOCUMENT)
    assert expected_docs == 2, "precondition: the corpus plants 2 KB documents"

    gw = _MintingGateway()
    for urn in ({p.urn for p in PAYLOADS if p.locus is not Locus.KB_DOCUMENT}
                | {h.urn for h in HELD_OUT}):
        gw.entities[urn] = ""

    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as scratch:
        os.chdir(scratch)
        try:
            for run_no in (1, 2, 3):
                seed_corpus.plant(gw, verbose=False)
                assert len(gw.docs) == expected_docs, (
                    f"run {run_no} duplicated the KB documents "
                    f"({len(gw.docs)} documents for {expected_docs} payloads)")
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {t.__name__}\n      {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

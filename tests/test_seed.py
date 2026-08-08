"""Seed helpers — fixture alignment between the corpus and a live graph.

The corpus addresses KB documents by their intended URN, but a live DataHub mints
its own on `save_document`. These tests pin the re-keying that keeps document
payloads curable on the live path.
"""

# --------------------------------------------------------------------------- #
# align_document_fixtures — live GMS mints its own document URNs
# --------------------------------------------------------------------------- #

def test_align_document_fixtures_rekeys_docs_onto_live_urns():
    """A live `save_document` assigns `urn:li:document:shared-<uuid>`, not the
    corpus's intended `urn:li:document:<parent>/<title>`. Keyed by the intended
    URN, a doc fixture never matches a live hit and the payload goes uncured
    while every entity payload is fixed."""
    from types import SimpleNamespace

    from antigen.scan import Locus
    from antigen.seed import align_document_fixtures, corpus_fixtures

    fixtures = corpus_fixtures()
    doc_keys = [k for k in fixtures if k[0].startswith("urn:li:document:")]
    assert doc_keys, "corpus should carry KB-document payloads"
    intended_urn = doc_keys[0][0]
    title = intended_urn.rsplit("/", 1)[-1]
    live_urn = "urn:li:document:shared-11111111-2222-3333-4444-555555555555"

    hit = SimpleNamespace(urn=live_urn, locus=Locus.DOCUMENT, doc_title=title,
                          key=(live_urn, ""))
    report = SimpleNamespace(hits=[hit])

    aligned = align_document_fixtures(fixtures, report)
    assert (live_urn, "") in aligned, "fixture must follow the live URN"
    assert doc_keys[0] not in aligned, "stale intended-URN key must be dropped"
    assert aligned[(live_urn, "")].payload_id == fixtures[doc_keys[0]].payload_id


def test_align_document_fixtures_ignores_unknown_and_matching_titles():
    from types import SimpleNamespace

    from antigen.seed import align_document_fixtures, corpus_fixtures

    fixtures = corpus_fixtures()
    unknown = SimpleNamespace(doc_title="not-in-corpus", key=("urn:x", ""))
    untitled = SimpleNamespace(doc_title=None, key=("urn:y", ""))
    assert align_document_fixtures(
        fixtures, SimpleNamespace(hits=[unknown, untitled])) == fixtures


def test_align_document_fixtures_noop_without_document_fixtures():
    from types import SimpleNamespace

    from antigen.seed import Fixture, align_document_fixtures

    entity_only = {("urn:li:dataset:(x,y,PROD)", ""): Fixture("orig", "pay", "P01")}
    assert align_document_fixtures(
        entity_only, SimpleNamespace(hits=[])) == entity_only

"""Gateway coverage — response parsers, the live SdkGateway, and register_properties.

The real DataHub SDK isn't installed offline, so the SDK/LangChain imports are faked
via `sys.modules` injection and the tool objects are `FakeTool`s. This exercises the
production argument-marshalling and response-parsing code (the code that would run
against a live GMS) without a network or Docker. Run under pytest.
"""

from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from antigen.gateway import (  # noqa: E402
    SdkGateway,
    _as_list,
    _extract_urns,
    _get,
    _parse_document,
    _parse_entity,
)

# --------------------------------------------------------------------------- #
# Pure response-parsing helpers
# --------------------------------------------------------------------------- #

def test_as_list_all_shapes():
    assert _as_list(None) == []
    assert _as_list([1, 2]) == [1, 2]
    assert _as_list({"entities": [1]}) == [1]
    assert _as_list({"results": ["a"]}) == ["a"]
    assert _as_list({"x": 1}) == [{"x": 1}]      # dict with no known list key → wrapped
    assert _as_list("scalar") == ["scalar"]


def test_get_dict_attr_default():
    assert _get({"a": 1}, "a") == 1
    ns = types.SimpleNamespace(b=2)
    assert _get(ns, "b") == 2
    assert _get({}, "missing", default="d") == "d"


def test_extract_urns_str_and_obj():
    raw = ["urn:1", {"urn": "urn:2"}, {"entity_urn": "urn:3"}, {"nope": 1}]
    assert _extract_urns(raw) == ["urn:1", "urn:2", "urn:3"]


def test_parse_entity_dict_and_object():
    ent = _parse_entity({
        "urn": "urn:1", "description": "d", "tags": ["t"],
        "structured_properties": {"p": "v"},
        "columns": [{"field_path": "c1", "description": "cd", "tags": ["ct"]},
                    {"no_path": True}],  # skipped (no field_path)
    })
    assert ent.urn == "urn:1" and ent.description == "d" and ent.tags == ["t"]
    assert ent.structured_properties == {"p": "v"}
    assert "c1" in ent.columns and ent.columns["c1"].description == "cd"

    obj = types.SimpleNamespace(urn="urn:2", editableDescription="ed", columns=[])
    ent2 = _parse_entity(obj)
    assert ent2.urn == "urn:2" and ent2.description == "ed"


def test_parse_document():
    d = _parse_document({"urn": "urn:d", "title": "T", "body": "b"})
    assert d.urn == "urn:d" and d.title == "T" and d.content == "b" and d.parent == "Shared"


def test_gateway_protocol_default_get_entity():
    # The Gateway Protocol provides a default get_entity() that concrete gateways
    # override; call the default directly against a concrete instance to cover it.
    from antigen._testkit import InMemoryGateway
    from antigen.gateway import Entity, Gateway
    im = InMemoryGateway()
    im.add_entity(Entity(urn="urn:z", description="d"))
    assert Gateway.get_entity(im, "urn:z").urn == "urn:z"
    assert Gateway.get_entity(im, "missing") is None


# --------------------------------------------------------------------------- #
# SdkGateway methods, driven by fake LangChain tools (no __init__)
# --------------------------------------------------------------------------- #

class FakeTool:
    def __init__(self, name, responder):
        self.name = name
        self.responder = responder
        self.calls = []

    def invoke(self, kwargs):
        self.calls.append(kwargs)
        return self.responder(kwargs)


def _sdk_with_tools(tools):
    g = object.__new__(SdkGateway)
    g._client = object()
    g._tools = {t.name: t for t in tools}
    return g


def test_sdkgateway_read_and_mutation_methods():
    def search_resp(kw):
        if kw["start"] == 0:
            return [f"urn:{i}" for i in range(500)]   # full page → loop continues
        if kw["start"] == 500:
            return ["urn:a", "urn:b"]                  # partial page → break
        return []

    tools = [
        FakeTool("search", search_resp),
        FakeTool("get_entities", lambda kw: {"entities": [
            {"urn": "urn:1", "description": "d",
             "columns": [{"field_path": "c1", "description": "cd"}]}]}),
        FakeTool("grep_documents", lambda kw: [
            {"urn": "urn:d", "title": "T", "content": "body", "parent": "Shared"}]),
        FakeTool("get_lineage", lambda kw: ["urn:down1", "urn:down2"]),
        FakeTool("update_description", lambda kw: None),
        FakeTool("add_tags", lambda kw: None),
        FakeTool("add_structured_properties", lambda kw: None),
        FakeTool("save_document", lambda kw: None),
    ]
    g = _sdk_with_tools(tools)

    assert len(g.search_all()) == 502                  # 500 + 2, pagination worked
    assert g.get_entities([]) == []                    # early return
    ents = g.get_entities(["urn:1"])
    assert ents[0].urn == "urn:1" and "c1" in ents[0].columns
    docs = g.grep_documents("x")
    assert docs[0].title == "T"
    assert g.get_lineage("u") == ["urn:down1", "urn:down2"]

    g.update_description("u", "text")                  # no field_path
    g.update_description("u", "text", field_path="c1")  # column branch
    g.add_tags("u", ["a"])
    g.add_tags("u", ["a"], field_path="c1")
    g.add_structured_properties("u", {"p": "v"})
    g.save_document("title", "content")
    # column-branch kwargs carried sub_resource
    assert any("sub_resource" in c for c in g._tools["update_description"].calls)

    assert g.get_entity("urn:1").urn == "urn:1"
    assert g.get_document("Shared", "T").title == "T"
    assert g.get_document("Shared", "missing") is None


def test_sdkgateway_search_all_empty_and_get_entity_none():
    g = _sdk_with_tools([
        FakeTool("search", lambda kw: []),             # empty first page → break
        FakeTool("get_entities", lambda kw: []),       # → get_entity None branch
    ])
    assert g.search_all() == []
    assert g.get_entity("nope") is None


# --------------------------------------------------------------------------- #
# SdkGateway.__init__ via injected fake SDK modules (success + missing-tools)
# --------------------------------------------------------------------------- #

def _ensure_pkg(monkeypatch, dotted):
    parts = dotted.split(".")
    for i in range(1, len(parts) + 1):
        sub = ".".join(parts[:i])
        if sub not in sys.modules:
            m = types.ModuleType(sub)
            monkeypatch.setitem(sys.modules, sub, m)
            if i > 1:
                setattr(sys.modules[".".join(parts[:i - 1])], parts[i - 1], m)
    return sys.modules[dotted]


def _install_fake_sdk(monkeypatch, tool_names):
    main_client = _ensure_pkg(monkeypatch, "datahub.sdk.main_client")
    main_client.DataHubClient = types.SimpleNamespace(from_env=lambda: object())
    lc = _ensure_pkg(monkeypatch, "datahub_agent_context.langchain_tools")
    lc.build_langchain_tools = lambda client, include_mutations=False: [
        FakeTool(n, lambda kw: None) for n in tool_names
    ]
    return lc


ALL_TOOLS = ["search", "get_entities", "grep_documents", "get_lineage",
             "update_description", "add_tags", "add_structured_properties",
             "save_document"]


def test_sdkgateway_init_success_and_provided_client(monkeypatch):
    _install_fake_sdk(monkeypatch, ALL_TOOLS)
    g = SdkGateway()                                    # client=None → from_env
    assert set(SdkGateway._required_tools()).issubset(g._tools)
    g2 = SdkGateway(client="my-client")                 # provided client branch
    assert g2._client == "my-client"


def test_sdkgateway_init_missing_tools_raises(monkeypatch):
    _install_fake_sdk(monkeypatch, ["search"])          # missing the other 7
    try:
        SdkGateway()
        raise AssertionError("expected RuntimeError for missing tools")
    except RuntimeError as e:
        assert "missing required tools" in str(e)


# --------------------------------------------------------------------------- #
# register_properties via injected fake SDK modules
# --------------------------------------------------------------------------- #

def test_register_properties(monkeypatch):
    from antigen.register_properties import PROPERTY_DEFINITIONS, register_properties

    assert len(PROPERTY_DEFINITIONS) == 3
    emitted = []

    mce = _ensure_pkg(monkeypatch, "datahub.emitter.mce_builder")
    mce.make_data_platform_urn = lambda p: f"urn:li:dataPlatform:{p}"
    mcp_mod = _ensure_pkg(monkeypatch, "datahub.emitter.mcp")
    mcp_mod.MetadataChangeProposalWrapper = lambda entityUrn, aspect: ("mcp", entityUrn)
    client_mod = _ensure_pkg(monkeypatch, "datahub.ingestion.graph.client")
    client_mod.DatahubClientConfig = lambda **kw: kw

    class FakeGraph:
        def __init__(self, config):
            self.config = config

        def emit_mcp(self, mcp):
            emitted.append(mcp)

    client_mod.DataHubGraph = FakeGraph
    schema = _ensure_pkg(monkeypatch, "datahub.metadata.schema_classes")
    schema.PropertyValueClass = object
    schema.StructuredPropertyDefinitionClass = lambda **kw: kw

    monkeypatch.setenv("DATAHUB_GMS_URL", "http://localhost:8080")
    urns = register_properties()
    assert len(urns) == 3
    assert all(u.startswith("urn:li:structuredProperty:antigen.") for u in urns)
    assert len(emitted) == 3

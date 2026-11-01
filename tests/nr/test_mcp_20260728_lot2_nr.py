"""NR MCP 2026-07-28 lot 2 : trace context, identite declaree initialize, mode dual."""
from app import forge_mcp_protocole as P

TP = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"


def _b(meta=None, **kw):
    return {"method": "tools/call", "params": {"_meta": meta or {}, **kw}}


def test_trace_meta_prioritaire():
    h = {"traceparent": "00-" + "c" * 32 + "-" + "d" * 16 + "-00"}
    r = P.trace_depuis_meta(_b({"traceparent": TP}), h)
    assert r["traceparent"] == TP


def test_trace_en_tete_sinon():
    assert P.trace_depuis_meta(_b(), {"Traceparent": TP})["traceparent"] == TP


def test_trace_invalide_none():
    for bad in ("", "x", "00-" + "0" * 32 + "-" + "b" * 16 + "-01",
                "00-" + "a" * 32 + "-" + "0" * 16 + "-01", "01-" + "a" * 32 + "-" + "b" * 16 + "-01",
                "00-" + "A" * 32 + "-" + "b" * 16 + "-01", 42):
        assert P.trace_depuis_meta(_b({"traceparent": bad}), {}) is None
    assert P.trace_depuis_meta(None, None) is None
    assert P.trace_depuis_meta("zz", {"traceparent": object()}) is None


def test_tracestate_baggage():
    r = P.trace_depuis_meta(_b({"traceparent": TP, "tracestate": "a=1,b=2",
                                "baggage": "k=v;prop=1, x=y,sansegal, z=w"}), {})
    assert r["tracestate"] == "a=1,b=2"
    assert r["baggage"] == {"k": "v", "x": "y", "z": "w"}


def _init(ver, name="claude-code"):
    return {"method": "initialize", "params": {"protocolVersion": ver, "clientInfo": {"name": name}}}


def test_declared_initialize():
    assert P.declared_depuis_initialize(_init("2025-11-25"), "D") == "CLAUDE-CODE"
    assert P.declared_depuis_initialize({"method": "initialize", "params": {}}, "D") == "D"
    assert P.declared_depuis_initialize(None, "D") == "D"
    assert P.declared_depuis_initialize({"method": "tools/call", "params": {"clientInfo": {"name": "x"}}}, "D") == "D"


def test_dual_a_initialize_2025_sans_entetes():
    assert P.valider_requete({}, _init("2025-11-25")) is None


def test_dual_b_version_inconnue_negociee():
    assert P.valider_requete({}, _init("2025-01-01")) is None
    v, warn = P.negocier_version("2025-01-01")
    assert v in P.VERSIONS_SUPPORTEES and warn


def test_dual_c_mcp_name_mismatch():
    h = {"Mcp-Protocol-Version": "2026-07-28", "Mcp-Method": "prompts/get", "Mcp-Name": "autre"}
    r = P.valider_requete(h, {"method": "prompts/get", "params": {"name": "p"}})
    assert r and r[1] == -32020
    h = {"Mcp-Protocol-Version": "2026-07-28", "Mcp-Method": "resources/read", "Mcp-Name": "file:///b"}
    r = P.valider_requete(h, {"method": "resources/read", "params": {"uri": "file:///a"}})
    assert r and r[1] == -32020


def test_dual_d_meta_2026_sans_header():
    b = _b({P.META_NS + "protocolVersion": "2026-07-28"})
    r = P.valider_requete({}, b)
    assert r and r[1] == -32020

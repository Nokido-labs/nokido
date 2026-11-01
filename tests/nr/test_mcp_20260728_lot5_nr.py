"""NR MCP 2026-07-28 lot 5 : sentinel Base64 de Mcp-Name (streamable-http, Value Encoding)
et en-tetes Mcp-Param-{Name} (Server Behavior for Custom Headers). Mode dual preserve."""
import base64

from app import forge_mcp_protocole as P

V = "2026-07-28"


def _b64(s):
    return "=?base64?" + base64.b64encode(s.encode("utf-8")).decode() + "?="


def _h(name, **extra):
    h = {"Mcp-Protocol-Version": V, "Mcp-Method": "tools/call", "Mcp-Name": name}
    h.update(extra)
    return h


def _body(name="outil", args=None):
    return {"method": "tools/call", "params": {"name": name, "arguments": args or {}}}


SCHEMA = {"type": "object", "properties": {
    "region": {"type": "string", "x-mcp-header": "Region"},
    "n": {"type": "integer", "x-mcp-header": "N"},
    "ok": {"type": "boolean", "x-mcp-header": "Ok"},
    "q": {"type": "string"}}}


# --- (a) sentinel Base64 de Mcp-Name ---
def test_a_sentinel_valide_egal_au_corps_passe():
    assert P.valider_requete(_h(_b64("café")), _body("café")) is None


def test_a_sentinel_valide_different_du_corps_32020():
    r = P.valider_requete(_h(_b64("autre")), _body("outil"))
    assert r and r[0] == 400 and r[1] == -32020


def test_a_sentinel_base64_invalide_32020():
    for bad in ("=?base64?%%%?=", "=?base64?abc", "=?BASE64?Zm9v?="):
        r = P.valider_requete(_h(bad), _body("outil"))
        assert r and r[1] == -32020, bad


def test_a_sentinel_sur_uri():
    h = {"Mcp-Protocol-Version": V, "Mcp-Method": "resources/read", "Mcp-Name": _b64("file:///é")}
    assert P.valider_requete(h, {"method": "resources/read", "params": {"uri": "file:///é"}}) is None


def test_a_client_2025_jamais_rejete():
    assert P.valider_requete({"Mcp-Name": "=?base64?%%%?="}, _body("outil")) is None


# --- (b) Mcp-Param-* ---
def test_b_param_conforme():
    h = _h("outil", **{"Mcp-Param-Region": "us-west1", "mcp-param-n": "42", "Mcp-Param-Ok": "true"})
    b = _body(args={"region": "us-west1", "n": 42, "ok": True})
    assert P.valider_requete(h, b, schema_outil=SCHEMA) is None


def test_b_param_different_32020():
    h = _h("outil", **{"Mcp-Param-Region": "eu"})
    r = P.valider_requete(h, _body(args={"region": "us"}), schema_outil=SCHEMA)
    assert r and r[0] == 400 and r[1] == -32020


def test_b_param_absent_alors_que_valeur_dans_corps_rejete():
    r = P.valider_requete(_h("outil"), _body(args={"region": "us"}), schema_outil=SCHEMA)
    assert r and r[1] == -32020


def test_b_valeur_absente_ou_null_pas_d_entete_attendu():
    assert P.valider_requete(_h("outil"), _body(args={}), schema_outil=SCHEMA) is None
    assert P.valider_requete(_h("outil"), _body(args={"region": None}), schema_outil=SCHEMA) is None


def test_b_param_base64():
    h = _h("outil", **{"Mcp-Param-Region": _b64("café")})
    assert P.valider_requete(h, _body(args={"region": "café"}), schema_outil=SCHEMA) is None
    h = _h("outil", **{"Mcp-Param-Region": _b64("x")})
    assert P.valider_requete(h, _body(args={"region": "café"}), schema_outil=SCHEMA)[1] == -32020


def test_b_param_caracteres_invalides_32020():
    h = _h("outil", **{"Mcp-Param-Region": "a\x01b"})
    r = P.valider_requete(h, _body(args={"region": "a\x01b"}), schema_outil=SCHEMA)
    assert r and r[1] == -32020


def test_b_entete_param_non_reconnu_ignore():
    h = _h("outil", **{"Mcp-Param-Inconnu": "z"})
    assert P.valider_requete(h, _body(), schema_outil=SCHEMA) is None
    assert P.valider_requete(h, _body()) is None


# --- (c) balayage : exigences serveur absentes ---
def test_c1_32022_porte_supported_et_requested():
    # versioning.md : l'erreur MUST lister les versions supportees (data.supported / data.requested)
    h = {"Mcp-Protocol-Version": "2027-01-01"}
    r = P.valider_requete(h, {"method": "tools/list", "params": {}})
    assert r[1] == -32022
    assert r[3] == {"supported": list(P.VERSIONS_SUPPORTEES), "requested": "2027-01-01"}


def test_c2_tools_list_2026_resultType_complete():
    # caching.md : les indices de cache vont sur des resultats resultType "complete"
    assert P.habiller_tools_list([], True)["resultType"] == "complete"
    assert "resultType" not in P.habiller_tools_list([], False)


def test_c3_hub_transmet_data_32022():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "tools" / "nokido_hub.py").read_text(
        encoding="utf-8", errors="replace")
    assert "_refus26[3]" in src


def test_b_sans_schema_ou_2025_inchange():
    assert P.valider_requete({"Mcp-Param-Region": "x"}, _body(args={"region": "y"}), schema_outil=SCHEMA) is None

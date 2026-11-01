"""NR - MCP 2026-07-28 lot 1 ADDITIF (decision owner 24/10).

Sources (docs ingerees, mcp_docs:modelcontextprotocol.io/...) :
  - specification/2026-07-28/basic/transports/streamable-http.md : MCP-Protocol-Version,
    Mcp-Method, Mcp-Name ; 400 si absent / different du corps.
  - specification/2026-07-28/basic/index.md : -32020 HeaderMismatch, -32022 UnsupportedProtocolVersion.
  - specification/2026-07-28/server/discover.md + utilities/caching.md : ttlMs, cacheScope.
Contrat : un client 2025-11-25 ne voit RIEN changer ; la validation stricte ne vaut que si la
requete annonce 2026-07-28 ; clientInfo alimente `declared`, jamais `principal`.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "app"))

import forge_mcp_protocole as mp  # noqa: E402

V26 = "2026-07-28"
META = "io.modelcontextprotocol/"


def _corps(method="tools/call", name="run", version=V26, client="Claude-Code"):
    meta = {META + "protocolVersion": version,
            META + "clientInfo": {"name": client, "version": "1"}}
    p = {"_meta": meta}
    if name is not None:
        p["name"] = name
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": p}


def _ent(method="tools/call", name="run", version=V26):
    h = {"MCP-Protocol-Version": version, "Mcp-Method": method}
    if name is not None:
        h["Mcp-Name"] = name
    return h


def test_client_2025_inchange():
    corps = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "run"}}
    assert mp.valider_requete({}, corps) is None
    assert mp.valider_requete({"MCP-Protocol-Version": "2025-11-25", "Mcp-Method": "autre"}, corps) is None
    assert mp.annonce_2026({"mcp-protocol-version": "2025-11-25"}, corps) is False


def test_2026_conforme_passe():
    assert mp.valider_requete(_ent(), _corps()) is None


def test_entete_methode_different_du_corps_400_32020():
    r = mp.valider_requete(_ent(method="tools/list"), _corps())
    assert r and r[0] == 400 and r[1] == -32020


def test_entete_nom_different_ou_casse_32020():
    assert mp.valider_requete(_ent(name="Run"), _corps())[1] == -32020  # casse significative
    assert mp.valider_requete(_ent(name="autre"), _corps())[1] == -32020


def test_entete_absent_en_2026_32020():
    h = _ent()
    del h["Mcp-Method"]
    assert mp.valider_requete(h, _corps())[1] == -32020


def test_version_entete_differente_de_meta_32020():
    h = _ent()
    h["MCP-Protocol-Version"] = "2025-11-25"
    assert mp.valider_requete(h, _corps())[1] == -32020


def test_version_inconnue_32022():
    r = mp.valider_requete(_ent(version="2027-01-01"), _corps(version="2027-01-01"))
    assert r and r[0] == 400 and r[1] == -32022


def test_noms_d_entetes_insensibles_a_la_casse():
    h = {k.lower(): v for k, v in _ent().items()}
    assert mp.valider_requete(h, _corps()) is None


def test_clientinfo_alimente_declared_pas_principal():
    assert mp.declared_depuis_meta(_corps(client="Vibe"), "LAFORGE-X") == "VIBE"
    assert mp.declared_depuis_meta({"params": {}}, "LAFORGE-X") == "LAFORGE-X"
    # seulement si 2026 annonce : un _meta isole sans version ne change rien
    assert mp.declared_depuis_meta(
        {"params": {"_meta": {META + "clientInfo": {"name": "zz"}}}}, "H") == "H"


def test_tools_list_ttl_scope_et_ordre_deterministe_en_2026():
    outils = [{"name": "b"}, {"name": "a"}]
    res = mp.habiller_tools_list(outils, annonce_2026=True)
    assert [t["name"] for t in res["tools"]] == ["a", "b"]
    assert isinstance(res["ttlMs"], int) and res["ttlMs"] >= 0
    assert res["cacheScope"] in ("public", "private")
    ancien = mp.habiller_tools_list(outils, annonce_2026=False)
    assert ancien == {"tools": outils}


def test_discover():
    r = mp.resultat_discover({"tools": {}}, "Nokido-Hub", "18.3")
    assert V26 in r["supportedVersions"] and r["capabilities"] == {"tools": {}}
    assert r["_meta"][META + "serverInfo"] == {"name": "Nokido-Hub", "version": "18.3"}
    assert "ttlMs" in r and r["cacheScope"] in ("public", "private")


def test_hub_branche_le_module():
    src = (RACINE / "tools" / "nokido_hub.py").read_text(encoding="utf-8", errors="replace")
    assert "valider_requete" in src and 'method == "server/discover"' in src
    assert "habiller_tools_list" in src and "declared_depuis_meta" in src
    i = src.find("principal = (auth_agent")
    assert "declared_depuis_meta" not in src[i:i + 200]  # jamais principal
    assert 'method == "initialize"' in src

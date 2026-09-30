"""NR -- 2b-5 : le pont stdio (Claude Desktop et clients stdio) presente l'identite PROPRE (2026-09-28).

Mesure du 2026-09-28 (journal de recensement + lecture de code) : `mcp_stdio_bridge`,
sous le compte de l'owner, lisait le jeton MAITRE. Pire : pour tout client autre que
BRIDGE, le « jeton propre » etait `get_secret("FORGE_MCP_TOKEN") or "" or
_token_de_l_agent(...)` -- le MAITRE d'abord, alors que le commentaire juste au-dessus
exigeait « on ne retombe JAMAIS » sur un jeton emprunte. Et BRIDGE ne prenait son propre
jeton que s'il figurait EN CLAIR dans Nokido.env.

Ce que ce NR verrouille (fonction pure `_choisir_jeton`, extraite de la source : le
module n'est pas importe, il demarre un pont a l'import) :
  - chaque identite prend SON jeton au guichet (`FORGE_TOKEN_<AGENT>`), EN PREMIER ;
  - sans jeton propre, le maitre reste servi en TRANSITION jusqu'a 2b-6 (modes dev et
    clients de debug en vivent encore -- consigne owner du 2026-09-28), et la provenance
    le dit ;
  - ni l'un ni l'autre : aucun jeton (401 lisible).
"""
import ast
import textwrap
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = (ROOT / "tools" / "mcp_stdio_bridge.py").read_text(encoding="utf-8")
MAITRE = "maitre-nr-2b5-" + "m" * 32
PROPRE_BRIDGE = "propre-bridge-nr-2b5-" + "b" * 24
PROPRE_CLAUDE = "propre-claude-nr-2b5-" + "c" * 24


def _choisir():
    for noeud in ast.parse(SRC).body:
        if isinstance(noeud, ast.FunctionDef) and noeud.name == "_choisir_jeton":
            module = compile(textwrap.dedent(ast.get_source_segment(SRC, noeud)),
                             "mcp_stdio_bridge.py::_choisir_jeton", "exec")
            code = next(c for c in module.co_consts
                        if isinstance(c, types.CodeType) and c.co_name == "_choisir_jeton")
            return types.FunctionType(code, {"__builtins__": __builtins__}, "_choisir_jeton")
    raise AssertionError("_choisir_jeton introuvable dans mcp_stdio_bridge.py")


def _guichet(store):
    return lambda nom: store.get(nom, "")


def test_bridge_prend_son_jeton_propre():
    jeton, prov = _choisir()("BRIDGE", _guichet({"FORGE_TOKEN_BRIDGE": PROPRE_BRIDGE,
                                                  "FORGE_MCP_TOKEN": MAITRE}))
    ok = jeton == PROPRE_BRIDGE and prov == "propre"
    assert ok


def test_un_client_prend_son_jeton_et_jamais_le_maitre():
    jeton, prov = _choisir()("CLAUDE", _guichet({"FORGE_TOKEN_CLAUDE": PROPRE_CLAUDE,
                                                  "FORGE_MCP_TOKEN": MAITRE}))
    ok = jeton == PROPRE_CLAUDE and prov == "propre"
    assert ok, "le client stdio presente le maitre au lieu de son jeton propre"


def test_un_client_sans_jeton_propre_garde_le_maitre_en_transition_dite():
    jeton, prov = _choisir()("CLAUDE", _guichet({"FORGE_MCP_TOKEN": MAITRE}))
    ok = jeton == MAITRE and prov == "maitre_transition"
    assert ok, "un client de debug sans jeton propre perdrait l'acces (mode dev casse)"


def test_ni_jeton_propre_ni_maitre_aucun_jeton():
    jeton, prov = _choisir()("CLAUDE", _guichet({}))
    ok = jeton == "" and prov == "absent"
    assert ok


def test_bridge_sans_jeton_propre_transition_maitre_dite():
    jeton, prov = _choisir()("BRIDGE", _guichet({"FORGE_MCP_TOKEN": MAITRE}))
    ok = jeton == MAITRE and prov == "maitre_transition"
    assert ok


def test_le_maitre_n_est_plus_lu_d_abord_au_niveau_du_module():
    assert 'get_secret("FORGE_MCP_TOKEN") or "" or _token_de_l_agent' not in SRC

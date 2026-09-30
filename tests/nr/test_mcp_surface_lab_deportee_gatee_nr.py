"""NR — la surface MCP presentee au client ne declare aucune capacite du lab deporte par defaut.

Le catalogue d'outils MCP (list_tools) est envoye au client LLM : c'est la surface la plus
directe. Une capacite deportee vers le lab borne ne doit PAS y figurer par defaut, sinon sa
description devient du contexte presente au client. Invariant mesure sur le REGISTRE reel
(pas sur le texte du fichier) :

- interrupteur du lab ABSENT (defaut) : la capacite deportee n'est PAS dans le catalogue ;
- interrupteur PRESENT : elle est enregistree (gel, pas suppression -- la capacite reste
  disponible quand le lab isole est explicitement active).

Garde de regression : re-decorer la fonction @mcp.tool() la re-exposerait par defaut et ce
test echouerait. Hermetique : import du module, aucun reseau, aucune DB.
"""
import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_LAB_FLAG = "NOKIDO_REDTEAM_INTENTS_JSON"
_TOOL_DEPORTE = "cyber_ai_task"


def _catalogue(lab_actif):
    prev = os.environ.get(_LAB_FLAG)
    if lab_actif:
        os.environ[_LAB_FLAG] = str(ROOT / "sandbox" / "_inexistant_lab_pour_test.json")
    else:
        os.environ.pop(_LAB_FLAG, None)
    try:
        for m in list(sys.modules):
            if m.endswith("mcp_server_tools"):
                del sys.modules[m]
        M = importlib.import_module("nokido_agent.app.mcp_server_tools")
        mcp = M.mcp
        for attr in ("_tool_manager", "tool_manager"):
            tm = getattr(mcp, attr, None)
            if tm is not None:
                d = getattr(tm, "_tools", None) or getattr(tm, "tools", None)
                if isinstance(d, dict):
                    return set(d.keys())
        d = getattr(mcp, "_tools", None)
        assert isinstance(d, dict), "API FastMCP inattendue : registre d'outils introuvable"
        return set(d.keys())
    finally:
        if prev is None:
            os.environ.pop(_LAB_FLAG, None)
        else:
            os.environ[_LAB_FLAG] = prev
        for m in list(sys.modules):
            if m.endswith("mcp_server_tools"):
                del sys.modules[m]


def test_capacite_deportee_absente_du_catalogue_par_defaut():
    assert _TOOL_DEPORTE not in _catalogue(lab_actif=False)


def test_capacite_deportee_gelee_pas_supprimee():
    # gel, pas suppression : le lab explicitement active la re-expose.
    assert _TOOL_DEPORTE in _catalogue(lab_actif=True)


# --- Surface dispatch (@commandes) : meme invariant que le catalogue MCP ---
def _registry(lab_actif):
    prev = os.environ.get(_LAB_FLAG)
    if lab_actif:
        os.environ[_LAB_FLAG] = str(ROOT / "sandbox" / "_inexistant_lab_pour_test.json")
    else:
        os.environ.pop(_LAB_FLAG, None)
    try:
        for m in list(sys.modules):
            if m.endswith("forge_dispatch"):
                del sys.modules[m]
        D = importlib.import_module("nokido_agent.app.forge_dispatch")
        return dict(D.REGISTRY)
    finally:
        if prev is None:
            os.environ.pop(_LAB_FLAG, None)
        else:
            os.environ[_LAB_FLAG] = prev
        for m in list(sys.modules):
            if m.endswith("forge_dispatch"):
                del sys.modules[m]


_CMD_DEPORTEES = ("@cai", "@exegol")


def test_dispatch_sans_commande_deportee_par_defaut():
    reg = _registry(lab_actif=False)
    assert not [c for c in _CMD_DEPORTEES if c in reg]
    assert len(reg) >= 26  # invariant check_registry preserve


def test_dispatch_commandes_deportees_gelees_pas_supprimees():
    reg = _registry(lab_actif=True)
    assert all(c in reg for c in _CMD_DEPORTEES)


# --- Deportation PHYSIQUE des corps offensifs hors du coeur (2026-09-27) ---
# Les corps vivent desormais dans le depot prive laforge-redteam
# (redteam/laforge_redteam/), plus dans le coeur Nokido. Gel = DEPLACEMENT, pas
# suppression : le fichier n'est plus ICI, il n'est pas detruit. Le rewire des
# importeurs (bootstrap, cyber_ai_task) charge depuis ce home SOUS le flag ; home
# absent du checkout (depot separe) -> import inerte, jamais un crash.
_CORPS_DEPORTES = (
    "app/forge_cai_bridge.py",
    "app/forge_sanitizer_analyst.py",
    "tools/nokido_pipeline.py",
)


def test_corps_offensifs_absents_du_coeur():
    presents = [f for f in _CORPS_DEPORTES if (ROOT / f).is_file()]
    assert not presents, f"corps offensifs encore dans le coeur (deportation incomplete) : {presents}"


def test_passerelle_deportee_echoue_gracieusement_si_home_absent():
    """Home redteam absent (cas checkout CI : depot separe non present) -> la passerelle
    rend une erreur JSON gracieuse (ok=False), jamais une exception non rattrapee qui
    casserait l'appelant. Deterministe : on pointe le home vers un chemin inexistant et
    on retire un eventuel home reel de sys.path -> l'import du corps deporte echoue a coup sur."""
    import asyncio
    import json as _json

    prev_flag = os.environ.get(_LAB_FLAG)
    prev_dir = os.environ.get("LAFORGE_REDTEAM_DIR")
    os.environ[_LAB_FLAG] = str(ROOT / "sandbox" / "_inexistant_lab_pour_test.json")
    os.environ["LAFORGE_REDTEAM_DIR"] = str(ROOT / "sandbox" / "_home_redteam_inexistant_pour_test")
    _real_home = str(ROOT.parent / "redteam" / "laforge_redteam")
    _saved_path = list(sys.path)
    try:
        sys.path[:] = [p for p in sys.path if p != _real_home]
        for m in list(sys.modules):
            if m.endswith("mcp_server_tools") or m == "forge_cai_bridge":
                del sys.modules[m]
        M = importlib.import_module("nokido_agent.app.mcp_server_tools")
        out = asyncio.run(M.cyber_ai_task("ping"))
        data = _json.loads(out)
        assert data.get("ok") is False, f"attendu echec gracieux, obtenu : {out[:200]}"
    finally:
        sys.path[:] = _saved_path
        if prev_flag is None:
            os.environ.pop(_LAB_FLAG, None)
        else:
            os.environ[_LAB_FLAG] = prev_flag
        if prev_dir is None:
            os.environ.pop("LAFORGE_REDTEAM_DIR", None)
        else:
            os.environ["LAFORGE_REDTEAM_DIR"] = prev_dir
        for m in list(sys.modules):
            if m.endswith("mcp_server_tools"):
                del sys.modules[m]

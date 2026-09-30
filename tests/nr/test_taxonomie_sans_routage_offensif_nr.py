"""NR — les taxonomies/routages du cœur ne DÉCLARENT plus de capacité offensive par défaut.

Distinction tenue (constitution + audit) : on retire le ROUTAGE/la DÉCLARATION offensive, on
GARDE le vocabulaire de DÉTECTION défensive (listes de mots-clefs qui classent un texte comme
sécurité). Invariants mesurés sur les objets réels importés :

- forge_silo_engine : plus de domaine 'exploit' (l'enum SiloDomain ne le porte plus ; les
  mappings DOMAIN_TO_USE_CASE / DOMAIN_TO_AGENT_PROVIDER n'ont plus la clé morte) ;
- forge_configurator : la catégorie de tâche 'security_pentest' est renommée 'security_audit' ;
- skilltree : le sous-arbre déporté (securite_pentest) n'est PAS dans l'arbre par défaut, mais
  le lab explicitement actif le re-fusionne (gel, pas suppression).

Hermétique : imports directs, aucun réseau, aucune DB.
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


def _fresh(mod, lab_actif):
    prev = os.environ.get(_LAB_FLAG)
    if lab_actif:
        os.environ[_LAB_FLAG] = str(ROOT / "sandbox" / "_inexistant_lab_pour_test.json")
    else:
        os.environ.pop(_LAB_FLAG, None)
    try:
        for m in list(sys.modules):
            if m.endswith(mod):
                del sys.modules[m]
        return importlib.import_module("nokido_agent.app." + mod)
    finally:
        if prev is None:
            os.environ.pop(_LAB_FLAG, None)
        else:
            os.environ[_LAB_FLAG] = prev
        for m in list(sys.modules):
            if m.endswith(mod):
                del sys.modules[m]


def test_silo_sans_domaine_exploit():
    S = _fresh("forge_silo_engine", lab_actif=False)
    assert not hasattr(S.SiloDomain, "EXPLOIT")
    assert "exploit" not in S.DOMAIN_TO_USE_CASE
    assert "exploit" not in S.DOMAIN_TO_AGENT_PROVIDER


def test_configurator_categorie_renommee():
    C = _fresh("forge_configurator", lab_actif=False)
    task_types = None
    for name in dir(C):
        v = getattr(C, name)
        if isinstance(v, dict) and "security_audit" in v and "refactor" in v:
            task_types = set(v.keys())
            break
    assert task_types is not None, "table task_types introuvable"
    assert "security_pentest" not in task_types
    assert "security_audit" in task_types


def test_skilltree_sous_arbre_deporte_gate_par_defaut():
    T = _fresh("skilltree", lab_actif=False)
    assert "securite_pentest" not in T.SKILL_TREE
    assert "securite_pentest" not in T.SKILL_TREE.get("securite", {}).get("children", [])


def test_skilltree_sous_arbre_deporte_gele_pas_supprime():
    T = _fresh("skilltree", lab_actif=True)
    assert "securite_pentest" in T.SKILL_TREE


# --- Surface UI (manifeste, atlas d'architecture) : capacité déportée gate par défaut ---
def _fresh_tool(mod, lab_actif):
    prev = os.environ.get(_LAB_FLAG)
    if lab_actif:
        os.environ[_LAB_FLAG] = str(ROOT / "sandbox" / "_inexistant_lab_pour_test.json")
    else:
        os.environ.pop(_LAB_FLAG, None)
    try:
        for m in list(sys.modules):
            if m.split(".")[-1] == mod:
                del sys.modules[m]
        return importlib.import_module(mod)
    finally:
        if prev is None:
            os.environ.pop(_LAB_FLAG, None)
        else:
            os.environ[_LAB_FLAG] = prev
        for m in list(sys.modules):
            if m.split(".")[-1] == mod:
                del sys.modules[m]


def test_ui_manifest_sans_surface_deportee_par_defaut():
    assert "redteam" not in _fresh_tool("forge_ui_manifest", lab_actif=False).SURFACES
    assert "redteam" in _fresh_tool("forge_ui_manifest", lab_actif=True).SURFACES


def test_arch_schema_famille_deportee_vide_par_defaut():
    off = dict(_fresh_tool("forge_arch_schema", lab_actif=False).DOMAINS).get("Redteam", [])
    on = dict(_fresh_tool("forge_arch_schema", lab_actif=True).DOMAINS).get("Redteam", [])
    assert off == []
    assert len(on) > 0

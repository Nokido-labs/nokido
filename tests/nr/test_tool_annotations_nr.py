"""NR -- annotations de comportement des tools MCP (`forge_tool_annotations`).

Ce que ces tests protegent, dans l'ordre d'importance :

1. le CABLAGE : une table d'annotations que `_all_tools` n'appelle pas est une
   dette de cablage, pas une signaletique. C'est le defaut le plus courant du
   corps (un garde branche sur un signal que personne n'emet), et il est
   invisible a la relecture -- donc il se teste.
2. la COUVERTURE mesuree contre le catalogue REEL, extrait par AST : une table
   qui derive du catalogue se lit comme complete.
3. la CONFORMITE a la spec : `destructiveHint` et `idempotentHint` n'ont de sens
   que si `readOnlyHint` est faux.
4. les TROIS ETATS : un tool inconnu rend None, jamais un dict vide -- un dict
   vide se lirait comme une innocuite mesuree.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_tool_annotations as fta  # noqa: E402

REGISTRY = ROOT / "app" / "forge_mcp_registry.py"


def _noms_du_catalogue() -> list:
    """Noms declares dans le catalogue, lus par AST -- sans importer le hub.

    L'import reel tirerait torch, le RAG et le reseau ; l'AST donne la meme
    liste et reste hermetique.
    """
    tree = ast.parse(REGISTRY.read_text(encoding="utf-8"))
    noms = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "_raw_tool_catalog", "_forge_dynamic_catalog"
        ):
            for d in ast.walk(node):
                if isinstance(d, ast.Dict):
                    for k, v in zip(d.keys, d.values):
                        if (isinstance(k, ast.Constant) and k.value == "name"
                                and isinstance(v, ast.Constant)
                                and isinstance(v.value, str)):
                            noms.append(v.value)
    return noms


# --------------------------------------------------------------------------
# 1. CABLAGE -- le test qui compte
# --------------------------------------------------------------------------

def test_all_tools_appelle_bien_l_injection():
    """`_all_tools` doit APPELER `_inject_annotations`.

    Sans cette assertion, la table peut etre parfaite et le catalogue sortir nu :
    c'est exactement le motif du garde qu'aucun emetteur n'alimente. On le
    verifie par AST plutot que par import, pour rester hermetique.
    """
    tree = ast.parse(REGISTRY.read_text(encoding="utf-8"))
    cible = [n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name == "_all_tools"]
    assert cible, "_all_tools introuvable : le catalogue a change de point d'entree"
    appels = {
        n.func.attr for n in ast.walk(cible[0])
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert "_inject_annotations" in appels, (
        "_all_tools n'appelle pas _inject_annotations : la table existe mais "
        "n'atteint jamais tools/list"
    )


def test_l_injection_est_definie():
    tree = ast.parse(REGISTRY.read_text(encoding="utf-8"))
    noms = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_inject_annotations" in noms


# --------------------------------------------------------------------------
# 2. COUVERTURE contre le catalogue reel
# --------------------------------------------------------------------------

def test_catalogue_non_vide():
    """Garde-fou de l'instrument : un extracteur muet rendrait tout le reste vert."""
    assert len(_noms_du_catalogue()) >= 40


def test_aucun_tool_du_catalogue_sans_annotation():
    c = fta.couverture(_noms_du_catalogue())
    assert c["manquants"] == [], (
        "tools exposes sans dire ce qu'ils font : %s" % c["manquants"])


def test_aucune_annotation_orpheline():
    """Une annotation qui survit a son tool = table qui derive du reel."""
    c = fta.couverture(_noms_du_catalogue())
    assert c["orphelins"] == [], (
        "annotations sans tool correspondant (renomme ou retire ?) : %s"
        % c["orphelins"])


def test_taux_none_si_catalogue_vide():
    """`0.0` se lirait « 0 % annote » ; l'absence de mesure doit se voir."""
    assert fta.couverture([])["taux"] is None


def test_couverture_signale_les_deux_ecarts():
    c = fta.couverture(["read", "tool_qui_nexiste_pas"])
    assert c["manquants"] == ["tool_qui_nexiste_pas"]
    assert "run" in c["orphelins"]


# --------------------------------------------------------------------------
# 3. CONFORMITE a la spec MCP
# --------------------------------------------------------------------------

def test_lecture_seule_sans_hints_sans_objet():
    """La spec dit destructive/idempotent sans objet quand readOnly est vrai."""
    for nom, a in fta.ANNOTATIONS.items():
        if a.get("readOnlyHint"):
            assert "destructiveHint" not in a, nom
            assert "idempotentHint" not in a, nom


def test_ecriture_declare_toujours_les_deux_hints():
    for nom, a in fta.ANNOTATIONS.items():
        if not a.get("readOnlyHint"):
            assert "destructiveHint" in a, nom
            assert "idempotentHint" in a, nom


def test_openworld_toujours_declare():
    for nom, a in fta.ANNOTATIONS.items():
        assert isinstance(a.get("openWorldHint"), bool), nom


def test_tous_les_hints_sont_booleens():
    for nom, a in fta.ANNOTATIONS.items():
        for k, v in a.items():
            assert isinstance(v, bool), "%s.%s = %r" % (nom, k, v)


def test_chaque_tool_porte_une_raison():
    """Une classification sans motif ne se reverifie pas."""
    for nom in fta.ANNOTATIONS:
        assert fta.raison(nom).strip(), nom


def test_les_tools_a_effet_systeme_sont_destructeurs():
    """Ancrage explicite : ceux-la ne doivent JAMAIS glisser en lecture seule."""
    for nom in ("run", "write", "governed_edit", "secret", "docker_action",
                "nokido_ensure_service", "oracle_python_repl",
                "manage_forge_lifecycle", "trigger_autonomous_evolution"):
        a = fta.ANNOTATIONS[nom]
        assert a["readOnlyHint"] is False, nom
        assert a["destructiveHint"] is True, nom


def test_les_lectures_pures_ne_sont_pas_destructrices():
    for nom in ("read", "read_function_body", "get_file_skeleton",
                "forge_deep_explore", "introspect", "web_search"):
        assert fta.ANNOTATIONS[nom]["readOnlyHint"] is True, nom


# --------------------------------------------------------------------------
# 4. TROIS ETATS et non-ecrasement
# --------------------------------------------------------------------------

def test_tool_inconnu_rend_none_pas_dict_vide():
    assert fta.annotation_de("tool_inexistant") is None


def test_annotation_de_rend_une_copie():
    a = fta.annotation_de("read")
    a["readOnlyHint"] = False
    assert fta.ANNOTATIONS["read"]["readOnlyHint"] is True


def test_annoter_injecte():
    out = fta.annoter([{"name": "run", "inputSchema": {}}])
    assert out[0]["annotations"]["destructiveHint"] is True


def test_annoter_n_ecrase_pas_une_annotation_declaree():
    """La table est un defaut, pas une autorite."""
    perso = {"readOnlyHint": True, "openWorldHint": False}
    out = fta.annoter([{"name": "run", "annotations": perso}])
    assert out[0]["annotations"] == perso


def test_annoter_n_invente_rien_pour_un_inconnu():
    out = fta.annoter([{"name": "tool_inexistant"}])
    assert "annotations" not in out[0]


def test_annoter_ne_mute_pas_l_entree():
    src = [{"name": "run"}]
    fta.annoter(src)
    assert "annotations" not in src[0]


def test_annoter_tolere_une_entree_sans_nom():
    out = fta.annoter([{"inputSchema": {}}, {"name": "read"}])
    assert len(out) == 2
    assert out[1]["annotations"]["readOnlyHint"] is True


# --------------------------------------------------------------------------
# 5. CONTRADICTION avec le ring -- l'apport verifiable
# --------------------------------------------------------------------------

def test_ring_absent_ressort_en_inconnu_pas_en_conforme():
    """Sans ce troisieme etat, une table de rings incomplete se lirait
    comme une absence de contradiction."""
    inc = fta.incoherences({})
    assert inc, "aucun verdict rendu alors qu'aucun ring n'est connu"
    assert all(i["type"] == "ring_inconnu" for i in inc)
    assert len(inc) == len(fta.ANNOTATIONS)


def test_lecture_seule_mais_privilegiee_est_detectee():
    rings = {n: 3 for n in fta.ANNOTATIONS}
    rings["read"] = 0
    types = {(i["tool"], i["type"]) for i in fta.incoherences(rings)}
    assert ("read", "lecture_seule_mais_privilegiee") in types


def test_destructeur_ouvert_a_tous_est_detecte():
    rings = {n: 3 for n in fta.ANNOTATIONS}
    rings["run"] = 4
    types = {(i["tool"], i["type"]) for i in fta.incoherences(rings)}
    assert ("run", "destructeur_mais_ouvert_a_tous") in types


def test_aucune_incoherence_sur_un_cablage_sain():
    rings = {n: 3 for n in fta.ANNOTATIONS}
    assert fta.incoherences(rings) == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

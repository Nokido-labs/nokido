"""NR -- repli lexical du scope par role (`forge_tool_scope`).

Pourquoi ce repli existe, mesure du 2026-09-02 : le scope par role etait muet
pour TOUS les agents, y compris les quatre porteurs de specialites, parce que
son routeur semantique depend d'un embedder HS. Un perimetre system-owned qui
s'eteint precisement quand le corps est degrade ne protege rien.

Le piege paye en l'ecrivant, et que ces tests verrouillent : l'embedder mort ne
LEVE PAS, il rend « aucun groupe ». Un repli branche sur le seul `except` reste
donc inatteignable -- `_route_lexicale` tranchait juste en isolation pendant que
`expected_scope_for` rendait None. Une panne qui se manifeste par une VALEUR ne
se rattrape pas par une exception.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_tool_scope as ts  # noqa: E402


@pytest.fixture(autouse=True)
def _propre():
    ts._reset()
    yield
    ts._reset()


# --------------------------------------------------------------------------
# Routage lexical pur
# --------------------------------------------------------------------------

def test_mots_clefs_designent_un_groupe():
    assert ts._route_lexicale("architecture,securite,ADR,long-context") == "code_recon"


def test_accents_normalises():
    """« sécurité » et « securite » doivent router pareil."""
    assert (ts._route_lexicale("architecture,sécurité,ADR")
            == ts._route_lexicale("architecture,securite,ADR"))


def test_abstention_si_aucun_mot_connu():
    assert ts._route_lexicale("cuisine,jardinage,poterie") is None


def test_abstention_si_egalite_entre_groupes():
    """Un depart au hasard sur-contraindrait l'agent : on prefere le catalogue plein."""
    assert ts._route_lexicale("veille,orchestration") is None


def test_abstention_sur_entree_vide():
    assert ts._route_lexicale("") is None
    assert ts._route_lexicale(None) is None


def test_groupe_rendu_existe_toujours():
    for spec in ("architecture", "refactoring", "docker", "veille",
                 "orchestration", "messaging"):
        g = ts._route_lexicale(spec)
        if g is not None:
            assert g in ts.TOOL_GROUPS, "%s -> groupe inconnu %r" % (spec, g)


def test_lexiques_sans_recouvrement():
    """Un mot dans deux lexiques rendrait l'abstention systematique sur ce mot."""
    vus = {}
    for g, lex in ts._LEXIQUE_GROUPES.items():
        for mot in lex:
            assert mot not in vus, "%r partage par %s et %s" % (mot, vus.get(mot), g)
            vus[mot] = g


def test_normaliser_decoupe_les_separateurs():
    assert ts._normaliser("a,b;c/d e") == {"a", "b", "c", "d", "e"}


# --------------------------------------------------------------------------
# Le repli est ATTEINT quand le routeur rend « aucun groupe » (le vrai piege)
# --------------------------------------------------------------------------

class _RouteurMuet:
    """Routeur qui ne LEVE PAS et ne trouve rien -- le comportement reel d'un
    embedder HS, et celui qu'un `except` ne rattrape jamais."""

    def route(self, _spec):
        return None, 0.0


class _RouteurQuiLeve:
    def route(self, _spec):
        raise RuntimeError("embedder down")


def test_repli_atteint_quand_le_routeur_rend_aucun_groupe(monkeypatch):
    monkeypatch.setattr(ts, "_specialites_for", lambda a: "architecture,ADR")
    monkeypatch.setattr(ts, "_router", lambda embed_fn=None: _RouteurMuet())
    tools = ts.role_scope_for("AGENT_TEST")
    assert tools, "le repli n'a pas ete atteint : c'est le defaut d'origine"
    assert ts.methode_du_role("AGENT_TEST") == "lexical"


def test_repli_atteint_quand_le_routeur_leve(monkeypatch):
    monkeypatch.setattr(ts, "_specialites_for", lambda a: "architecture,ADR")
    monkeypatch.setattr(ts, "_router", lambda embed_fn=None: _RouteurQuiLeve())
    assert ts.role_scope_for("AGENT_TEST")
    assert ts.methode_du_role("AGENT_TEST") == "lexical"


def test_routage_semantique_prime_et_est_nomme(monkeypatch):
    class _RouteurSain:
        def route(self, _spec):
            return "edition_code", 0.9

    monkeypatch.setattr(ts, "_specialites_for", lambda a: "architecture,ADR")
    monkeypatch.setattr(ts, "_router", lambda embed_fn=None: _RouteurSain())
    tools = ts.role_scope_for("AGENT_TEST")
    assert "governed_edit" in tools  # groupe semantique, pas le lexical
    assert ts.methode_du_role("AGENT_TEST") == "semantique"


def test_pas_de_repli_quand_un_embedder_est_injecte(monkeypatch):
    """embed_fn fourni = test explicite : masquer l'echec par un repli
    rendrait l'assertion du test menteuse."""
    monkeypatch.setattr(ts, "_specialites_for", lambda a: "architecture,ADR")
    monkeypatch.setattr(ts, "_router", lambda embed_fn=None: _RouteurMuet())
    assert ts.role_scope_for("AGENT_TEST", embed_fn=lambda x: [0.0]) is None


def test_sans_specialites_aucun_scope(monkeypatch):
    monkeypatch.setattr(ts, "_specialites_for", lambda a: None)
    assert ts.role_scope_for("AGENT_TEST") is None


def test_specialites_illisibles_ne_contraignent_pas(monkeypatch):
    monkeypatch.setattr(ts, "_specialites_for", lambda a: "poterie,jardinage")
    monkeypatch.setattr(ts, "_router", lambda embed_fn=None: _RouteurMuet())
    assert ts.role_scope_for("AGENT_TEST") is None


# --------------------------------------------------------------------------
# CORE, source, priorite du declare
# --------------------------------------------------------------------------

def test_governed_edit_est_dans_le_noyau():
    """`run` (non gouverne : ecrit, supprime, execute) etait dans CORE et
    `governed_edit` (AST + scan secret + tree_lock) n'y etait pas. Un agent
    scope n'avait donc que la porte LARGE pour ecrire. Si ce test tombe,
    verifier qu'on n'a pas retire la porte etroite en gardant l'autre."""
    assert "governed_edit" in ts.CORE_TOOLS
    assert "run" in ts.CORE_TOOLS, "asymetrie inverse : ne pas retirer run en silence"


def test_tout_scope_derive_peut_editer_de_facon_gouvernee(monkeypatch):
    """Quel que soit le groupe derive, l'outil d'edition gouvernee reste visible."""
    monkeypatch.setattr(ts, "_specialites_for", lambda a: "architecture,ADR")
    monkeypatch.setattr(ts, "_router", lambda embed_fn=None: _RouteurMuet())
    for groupe in ts.TOOL_GROUPS:
        tools = set(ts.TOOL_GROUPS[groupe]) | set(ts.CORE_TOOLS)
        assert "governed_edit" in tools, groupe


def test_la_precondition_de_l_edition_suit_l_edition():
    """Les regles du depot imposent de lire les tree_locks et de publier son
    claim AVANT d'editer un fichier tracke. Exposer `governed_edit` sans ces
    deux-la rendrait l'action possible en masquant sa precondition : l'agent
    editerait sans pouvoir se coordonner, donc en ecrasant les autres surfaces."""
    assert "governed_edit" in ts.CORE_TOOLS
    for t in ("blackboard_read_zone", "blackboard_propose_fact"):
        assert t in ts.CORE_TOOLS, (
            "%s hors du noyau alors que governed_edit y est : action sans precondition" % t)


def test_tout_scope_derive_peut_se_coordonner(monkeypatch):
    for groupe in ts.TOOL_GROUPS:
        tools = set(ts.TOOL_GROUPS[groupe]) | set(ts.CORE_TOOLS)
        assert {"blackboard_read_zone", "blackboard_propose_fact"} <= tools, groupe


def test_core_tools_toujours_inclus(monkeypatch):
    monkeypatch.setattr(ts, "_specialites_for", lambda a: "architecture,ADR")
    monkeypatch.setattr(ts, "_router", lambda embed_fn=None: _RouteurMuet())
    tools = ts.role_scope_for("AGENT_TEST")
    assert set(ts.CORE_TOOLS) <= tools


def test_source_distingue_le_repli(monkeypatch):
    """Un repli ne doit pas se lire comme un routage nominal dans les journaux."""
    monkeypatch.setattr(ts, "_specialites_for", lambda a: "architecture,ADR")
    monkeypatch.setattr(ts, "_router", lambda embed_fn=None: _RouteurMuet())
    _tools, src = ts.expected_scope_for("AGENT_TEST")
    assert src == "role_derived_lexical"


def test_scope_declare_prime_sur_le_role(monkeypatch):
    monkeypatch.setattr(ts, "active_tools_for", lambda a: {"read"})
    monkeypatch.setattr(ts, "_specialites_for", lambda a: "architecture,ADR")
    tools, src = ts.expected_scope_for("AGENT_TEST")
    assert src == "declared"
    assert tools == {"read"}


def test_methode_du_role_none_hors_cache():
    assert ts.methode_du_role("AGENT_JAMAIS_VU") is None


def test_reset_purge_bien_le_cache_de_role(monkeypatch):
    """`_reset` oubliait `_ROLE_CACHE` : un test heritait du perimetre du precedent."""
    monkeypatch.setattr(ts, "_specialites_for", lambda a: "architecture,ADR")
    monkeypatch.setattr(ts, "_router", lambda embed_fn=None: _RouteurMuet())
    ts.role_scope_for("AGENT_TEST")
    assert ts.methode_du_role("AGENT_TEST") is not None
    ts._reset()
    assert ts.methode_du_role("AGENT_TEST") is None


# --------------------------------------------------------------------------
# Coherence des groupes avec le catalogue reel
# --------------------------------------------------------------------------

def test_les_groupes_ne_nomment_que_des_tools_existants():
    """TOOL_GROUPS date d'un census a 44 tools ; le catalogue en compte plus.
    Un groupe qui nomme un tool disparu reduit le perimetre en silence."""
    import ast

    reg = ROOT / "app" / "forge_mcp_registry.py"
    tree = ast.parse(reg.read_text(encoding="utf-8"))
    noms = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "_raw_tool_catalog", "_forge_dynamic_catalog"
        ):
            for d in ast.walk(node):
                if isinstance(d, ast.Dict):
                    for k, v in zip(d.keys, d.values):
                        if (isinstance(k, ast.Constant) and k.value == "name"
                                and isinstance(v, ast.Constant)):
                            noms.add(v.value)
    assert noms, "catalogue illisible : l'assertion suivante serait vide de sens"
    # Les `dyn_*` sont FORGES a l'execution : ils n'ont pas a figurer au
    # catalogue statique, et `get_tool_list` les autorise explicitement
    # (`ring <= 2 and name.startswith("dyn_")`). Les compter comme absents etait
    # un faux positif de ce test, pas une derive des groupes.
    inconnus = {}
    for g, tl in ts.TOOL_GROUPS.items():
        manquants = sorted(n for n in set(tl) - noms if not n.startswith("dyn_"))
        if manquants:
            inconnus[g] = manquants
    assert not inconnus, "groupes nommant des tools absents du catalogue : %s" % inconnus


def test_core_tools_existent_au_catalogue():
    import ast

    reg = ROOT / "app" / "forge_mcp_registry.py"
    tree = ast.parse(reg.read_text(encoding="utf-8"))
    noms = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "_raw_tool_catalog", "_forge_dynamic_catalog"
        ):
            for d in ast.walk(node):
                if isinstance(d, ast.Dict):
                    for k, v in zip(d.keys, d.values):
                        if (isinstance(k, ast.Constant) and k.value == "name"
                                and isinstance(v, ast.Constant)):
                            noms.add(v.value)
    assert set(ts.CORE_TOOLS) <= noms, sorted(set(ts.CORE_TOOLS) - noms)


# --------------------------------------------------------------------------
# Cablage sur tools/list -- verifier le DRAPEAU ne suffit pas
# --------------------------------------------------------------------------

def _source_get_tool_list() -> str:
    import ast

    reg = ROOT / "app" / "forge_mcp_registry.py"
    tree = ast.parse(reg.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_tool_list":
            return ast.get_source_segment(reg.read_text(encoding="utf-8"), node) or ""
    return ""


def test_get_tool_list_consulte_le_scope_derive():
    """Sans cet appel, le repli lexical existe mais n'atteint jamais la
    visibilite : le bypass opt-out resterait ouvert cote catalogue."""
    src = _source_get_tool_list()
    assert src, "get_tool_list introuvable"
    assert "expected_scope_for" in src, (
        "get_tool_list ne consulte pas expected_scope_for : le perimetre derive "
        "du role n'atteint pas tools/list"
    )


def test_le_drapeau_est_lu_et_desarme_par_defaut():
    src = _source_get_tool_list()
    assert "LAFORGE_TOOLS_LIST_ROLESCOPE" in src
    # desarme : la valeur par defaut du getenv doit etre vide, jamais "1"
    assert 'os.environ.get("LAFORGE_TOOLS_LIST_ROLESCOPE", "")' in src, (
        "le drapeau doit defaulter a vide -- l'armer par defaut changerait ce que "
        "voient tous les clients MCP sans decision owner"
    )


def test_le_chemin_d_erreur_du_scope_n_est_plus_muet():
    """Un scope qui s'evapore sur une erreur d'import doit laisser une trace ;
    le fail-open reste le bon defaut, le silence non."""
    src = _source_get_tool_list()
    assert "except Exception as _se" in src
    assert "logger.debug" in src


def test_desarme_le_comportement_reste_le_declare():
    """Drapeau absent -> `active_tools_for`, exactement l'ancien comportement."""
    src = _source_get_tool_list()
    assert "_ts.active_tools_for(agent)" in src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

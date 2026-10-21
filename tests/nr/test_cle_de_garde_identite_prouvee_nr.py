"""NR -- les gardes par identite ne se contournent pas en changeant de nom (racine R2, 17/10, derogations owner
forge_mcp_registry + nokido_hub « limitee a cette transmission »).

Confirme par lecture de forge_videur.resolve_identity (point INCONNU de la revue adverse de Codex) : un nom en en-tete
SANS jeton correspondant reste l'identite (via=header, ring plancher, sujet_prouve=False). Les compteurs de la phase 2
(disjoncteur de lecture, lecture par run, impulsion) comptaient par NOM : un appelant non authentifie repartait de zero
en changeant de nom a chaque appel. La preuve vit dans le hub (ToolRegistry.dispatch ne voit pas la requete) : le hub la
pose dans une ContextVar avant le dispatch ; tout appel NON PROUVE partage UN compteur. Un appel interne (ContextVar non
posee, aucune requete HTTP) garde son nom : ce n'est pas un appelant qui peut forger un en-tete.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_recon_breaker as RB  # noqa: E402


def _avec(prouve, fn):
    jeton = RB.IDENTITE_PROUVEE.set(prouve)
    try:
        return fn()
    finally:
        RB.IDENTITE_PROUVEE.reset(jeton)


def test_deux_noms_non_prouves_partagent_le_meme_compteur(monkeypatch):
    monkeypatch.setenv("LAFORGE_GARDES_PAR_PREUVE", "refus")
    assert _avec(False, lambda: (RB.cle_de_garde("ALICE"), RB.cle_de_garde("BOB"))) == ("NON_PROUVE", "NON_PROUVE")


def test_une_identite_prouvee_garde_son_propre_compteur(monkeypatch):
    monkeypatch.setenv("LAFORGE_GARDES_PAR_PREUVE", "refus")
    assert _avec(True, lambda: RB.cle_de_garde("claude")) == "CLAUDE"


def test_un_appel_interne_sans_preuve_posee_garde_son_nom(monkeypatch):
    monkeypatch.setenv("LAFORGE_GARDES_PAR_PREUVE", "refus")
    assert RB.cle_de_garde("HUB") == "HUB"


def test_en_observation_le_compteur_reste_par_nom_et_l_ecart_se_dit(monkeypatch, caplog):
    """Observer avant d'enforcer : par defaut, rien ne change pour l'appelant ; l'appel non prouve est JOURNALISE."""
    monkeypatch.delenv("LAFORGE_GARDES_PAR_PREUVE", raising=False)
    monkeypatch.setattr(RB, "_OBSERVES", {})
    with caplog.at_level("WARNING"):
        assert _avec(False, lambda: RB.cle_de_garde("alice")) == "alice"
        assert _avec(True, lambda: RB.cle_de_garde("claude")) == "claude"
    assert any("alice" in r.getMessage() and "NON PROUVE" in r.getMessage() for r in caplog.records)
    assert not any("claude" in r.getMessage() for r in caplog.records)


def test_la_preuve_absente_ne_pose_rien():
    """Un appel interne (prouve=None) ne pose aucune preuve : la ContextVar reste a son etat."""
    assert RB.poser_preuve(None) is None and RB.IDENTITE_PROUVEE.get() is None
    jeton = RB.poser_preuve(False)
    try:
        assert RB.IDENTITE_PROUVEE.get() is False
    finally:
        RB.retirer_preuve(jeton)
    assert RB.IDENTITE_PROUVEE.get() is None


def _appels(src_path, fonction):
    src = (ROOT / src_path).read_text(encoding="utf-8", errors="replace")
    arbre = ast.parse(src)
    return [n for n in ast.walk(arbre) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == fonction]


def test_les_compteurs_du_registre_sont_cles_par_identite_prouvee():
    """Les quatre sites (read, lecture par run, impulsion, remise) passent cle_de_garde(...), jamais le nom brut."""
    for f in ("verdict", "impulsion", "impulsion_remise"):
        sites = [c for c in _appels("app/forge_mcp_registry.py", f) if c.args]
        assert sites, f
        for c in sites:
            a0 = c.args[0]
            assert isinstance(a0, ast.Call) and isinstance(a0.func, ast.Attribute) and a0.func.attr == "cle_de_garde", (
                f, ast.unparse(a0))


def test_le_hub_pose_la_preuve_du_videur_avant_tout_appel_d_outil():
    """La preuve est posee par requete dans mcp_post (meme patron que set_trace_id / set_actor : une tache par
    requete, copiee dans les taches filles), AVANT le premier _tool_call ; anti-dup : elle n'est pas recalculee mais
    redemandee a sa SOURCE (`_identite_inbox` -> forge_videur.resolve_identity), et importee sous le MEME nom que le
    registre (nokido_agent.tools.forge_recon_breaker : deux noms d'import = deux ContextVar)."""
    src = (ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8", errors="replace")
    arbre = ast.parse(src)
    fn = next(n for n in ast.walk(arbre) if isinstance(n, ast.AsyncFunctionDef) and n.name == "mcp_post")
    corps = ast.get_source_segment(src, fn)
    i_preuve, i_appel = corps.find("poser_preuve("), corps.find("_tool_call(")
    assert 0 <= i_preuve < i_appel, "la preuve doit etre posee AVANT le premier appel d'outil"
    ligne = corps[i_preuve:corps.find("\n", i_preuve)]
    assert "_identite_inbox(request)" in ligne and "sujet_prouve" in ligne, ligne
    assert "from nokido_agent.tools.forge_recon_breaker import poser_preuve" in corps

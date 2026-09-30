# -*- coding: utf-8 -*-
"""NR — un terme METIER n'est pas une intention, et un marqueur CITE n'en est pas une.

CE QUI A ETE MESURE (2026-09-18). `--verify` annoncait 391 intentions « ouvertes ».
La ventilation les a montrees pour ce qu'elles etaient :

  * **196 sur 394 (50 %)** etaient declenchees par le seul mot « backlog », qui est
    dans `_CREATE` mais qui est AUSSI un mot du metier. 169 d'entre elles vivaient dans
    du code, et seulement 31 portaient un `#` ou un `TODO` :

        backlog TEXT NOT NULL DEFAULT '[]'              <- une colonne SQL
        def create_project(goal, backlog: list[dict])   <- un parametre
        backlog = _backlog()                            <- une variable

  * Restaient ensuite des marqueurs CITES, pas poses :

        if re.match(r"#\\s*(TODO|FIXME|HACK)\\b", s)     <- du code qui DETECTE
        > Marqueurs : ✅ fait · 🔄 en cours · ⬜ à faire  <- une LEGENDE

  * Et le fichier le plus « charge en intentions » du depot etait
    `forge_roadmap_keeper.py` LUI-MEME, avec 15 — sa prose cite les mots qu'il traque.
    C'est « un instrument ne lit jamais son propre vocabulaire », au pied de la lettre,
    et c'etait la cinquieme occurrence du motif dans la meme journee.

RESULTAT : 429 items -> 252 ; ouvertes 391 -> 218. Un chiffre qui inquiete sans servir
est devenu un chiffre sur lequel on peut travailler.

CE QUE CE NR PROTEGE DES DEUX COTES : les filtres doivent taire le bruit ET laisser
passer les vraies intentions. La seconde moitie est la plus importante — un filtre trop
large transformerait 218 chantiers reels en zero, et personne ne le verrait.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_roadmap_keeper as FRK  # noqa: E402


# ── le mot metier ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ligne", [
    "    backlog TEXT NOT NULL DEFAULT '[]',",
    "def create_project(goal: str, backlog: list[dict]) -> str:",
    "    backlog = _backlog()",
    '    return {"action": WAIT, "backlog": None}',
])
def test_le_mot_metier_seul_est_du_BRUIT(ligne):
    assert FRK._bruit_lexical(ligne) is True, ligne


@pytest.mark.parametrize("ligne", [
    "    # backlog RAG a vider avant la prochaine campagne",
    "    # TODO: brancher le drain",
    "- [ ] forge_x est à créer",
    "    # FIXME backlog non borne",
])
def test_un_VRAI_marqueur_passe_toujours(ligne):
    """MORSURE — c'est ce cote-ci qui protege : filtrer trop fort effacerait le travail."""
    assert FRK._bruit_lexical(ligne) is False, ligne


# ── `todo` identifiant contre TODO marqueur ──────────────────────────────────
@pytest.mark.parametrize("ligne", [
    "    for todo in lots:",
    "    todo = _restant()",
    '    print(f"{len(todo)} restants")',
    "    lot, todo = todo[:n], todo[n:]",
])
def test_todo_MINUSCULE_dans_du_code_est_un_identifiant(ligne):
    """Mesure du 2026-09-18 : le tri par agent local a montre des dizaines de ces lignes."""
    assert FRK._todo_identifiant(ligne) is True, ligne
    assert FRK._bruit_lexical(ligne) is True, ligne


@pytest.mark.parametrize("ligne", [
    "    # TODO: brancher le drain",
    "    # todo: brancher le drain",          # minuscule MAIS en commentaire
    "    // todo brancher le drain",
    "- [ ] TODO migration schema",
])
def test_un_TODO_marqueur_survit_a_ce_filtre(ligne):
    """MORSURE — la convention majuscule ET le commentaire minuscule restent des taches."""
    assert FRK._bruit_lexical(ligne) is False, ligne


def test_un_autre_declencheur_protege_la_ligne():
    """Une ligne qui dit « à créer » reste une intention, meme si `todo` y traine."""
    ligne = "    todo = 1  # forge_chose est à créer"
    assert FRK._bruit_lexical(ligne) is False, ligne


# ── le marqueur cite ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("ligne", [
    'if re.match(r"#\\s*(TODO|FIXME|HACK)\\b", s, re.IGNORECASE):',
    'score -= len(re.findall(r"#\\s*(TODO|FIXME)", code)) * 2',
    "> Marqueurs : ✅ fait · 🔄 en cours · ⬜ à faire.",
])
def test_un_marqueur_CITE_n_est_pas_une_intention(ligne):
    assert FRK._marqueur_cite(ligne) is True, ligne


@pytest.mark.parametrize("ligne", [
    "    # TODO migration schema : passer released_at en REAL",
    "    # Core GOAP — decompose_goal (TODO : implementer _goap_llm_call)",
    "- [ ] cabler forge_event_mesh",
])
def test_une_intention_POSEE_n_est_pas_prise_pour_une_citation(ligne):
    """Seconde morsure : deux vraies intentions mesurees ce jour doivent survivre."""
    assert FRK._marqueur_cite(ligne) is False, ligne


# ── l'instrument ne se lit pas lui-meme ──────────────────────────────────────
@pytest.mark.parametrize("rel,attendu", [
    ("tools/forge_roadmap_keeper.py", True),
    ("tools\\forge_intent_audit.py", True),
    ("app/forge_commit_guard.py", True),
    ("app/forge_rag_engine.py", False),
    ("docs/ROADMAP.md", False),
])
def test_les_traqueurs_de_marqueurs_s_excluent(rel, attendu):
    assert FRK._fichier_traqueur(rel) is attendu, rel


def test_un_traqueur_ne_rend_AUCUN_item(tmp_path):
    """Le contrat de bout en bout, pas seulement le predicat."""
    f = tmp_path / "forge_intent_audit.py"
    f.write_text("# TODO : creer forge_machin\n", encoding="utf-8")
    assert FRK._scan_intent_source(f, "tools/forge_intent_audit.py") == []


def test_un_fichier_ORDINAIRE_rend_bien_ses_intentions(tmp_path):
    """CONTRE-EPREUVE GLOBALE — sans elle, tout ce NR passerait sur un scan mort."""
    f = tmp_path / "plan.md"
    f.write_text("# Plan\n\n- [ ] forge_chose_absente est à créer\n", encoding="utf-8")
    items = FRK._scan_intent_source(f, "docs/plan.md")
    assert items, "le scan ne voit plus RIEN : les filtres ont tout emporte"
    assert items[0]["refs"] == ["forge_chose_absente"], items

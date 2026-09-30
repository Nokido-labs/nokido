# -*- coding: utf-8 -*-
"""NR — le wiki porte une provenance LISIBLE PAR UNE MACHINE (OKF v0.2).

ETAPE 3. Nokido pose deja sa provenance, mais dans un COMMENTAIRE HTML :

    <!-- nokido:genere outil=... sha=... le=... empreinte=... -->

Un commentaire se lit a l'oeil et se parse a la regex. Un frontmatter YAML se
VALIDE. Le format Open Knowledge Format v0.2 -- ingere en RAG le 2026-09-22
depuis `langchain-ai/openwiki` -- donne le vocabulaire deja eprouve :

    type         SEUL champ REQUIS ; absent -> `missing_type`
    generated    evenement d'acteur {by, at}
    verified     un evenement, ou une LISTE d'evenements
    sources      liste de mappings portant chacun un `resource` non vide
    status       draft | stable | deprecated
    stale_after  ISO 8601 avec OFFSET EXPLICITE

DEUX REGLES DU VALIDATEUR QUI SONT LE CONTRAT, PAS DU DETAIL

 1. IL RAPPORTE, IL NE LEVE PAS. Un validateur qui explose sur la premiere
    anomalie ne dit qu'UN defaut ; celui qui rend une liste les dit TOUS. On
    a paye aujourd'hui l'inverse : un gate qui annoncait 12 sites muets quand
    il y en avait 22.

 2. L'OFFSET EST EXIGE. `2026-09-22T13:57:14` sans offset n'est pas un
    instant : c'est une heure sans lieu. Deux corps qui la relisent dans deux
    fuseaux ne lisent pas le meme moment, et la fraicheur devient une opinion.

    Et le timestamp se valide sur de VRAIS composants calendaires, pas sur une
    forme : `2026-02-30T00:00:00+00:00` a la bonne tete et n'existe pas.

CE QUE CE CONTRAT N'EST PAS
    Il ne remplace pas `entete_origine`. La page garde son commentaire HTML ;
    on AJOUTE une provenance que la machine sait verifier. Rien n'est retire
    d'un artefact que d'autres outils lisent peut-etre deja.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]
for _p in (_RACINE, _RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_wiki_modules as wm  # noqa: E402 — livrable, jamais d'importorskip


def _valider(texte: str):
    f = getattr(wm, "valider_frontmatter_okf", None)
    assert f is not None, (
        "`forge_wiki_modules.valider_frontmatter_okf` ABSENTE — la provenance "
        "reste un commentaire HTML, non verifiable par une machine")
    return f(texte)


def _bloc(**champs) -> str:
    lignes = ["---"]
    for cle, val in champs.items():
        lignes.append("%s: %s" % (cle, val))
    lignes.append("---")
    lignes.append("")
    lignes.append("# Titre")
    return "\n".join(lignes)


# ── LE SEUL CHAMP REQUIS ────────────────────────────────────────────────

def test_type_absent_est_le_seul_defaut_bloquant():
    issues = _valider(_bloc(title="Reference"))
    assert any(i.get("code") == "missing_type" for i in issues), (
        "`type` manquant n'est pas signale : c'est le SEUL champ requis "
        "d'OKF v0.2. Issues : %s" % issues)


def test_un_frontmatter_minimal_valide_ne_rend_AUCUNE_issue():
    assert _valider(_bloc(type="reference")) == [], (
        "un frontmatter minimal et valide produit des issues : le validateur "
        "crie a faux, et un garde qui crie a faux se fait desarmer")


# ── LE VALIDATEUR RAPPORTE, IL NE LEVE PAS ──────────────────────────────

def test_il_RAPPORTE_plusieurs_defauts_au_lieu_de_lever_au_premier():
    """Un validateur qui explose ne dit qu'UN defaut. Mesure du jour : un gate
    annoncait 12 sites muets quand il y en avait 22."""
    issues = _valider(_bloc(title="", status="inconnu"))
    assert isinstance(issues, list), "le validateur a leve au lieu de rapporter"
    assert len(issues) >= 2, (
        "un seul defaut rapporte alors que trois sont presents (type absent, "
        "title vide, status hors vocabulaire) : %s" % issues)


def test_aucun_frontmatter_du_tout_est_DIT_et_non_ignore():
    issues = _valider("# Titre sans frontmatter\n")
    assert issues, (
        "une page SANS frontmatter passe pour valide : l'absence de provenance "
        "serait indistinguable d'une provenance correcte")


# ── L'OFFSET, ET LE CALENDRIER REEL ─────────────────────────────────────

def test_un_instant_SANS_offset_est_refuse():
    issues = _valider(_bloc(type="reference",
                            generated="{by: nokido, at: 2026-09-22T13:57:14}"))
    assert issues, (
        "un instant sans offset a ete accepte : ce n'est pas un instant, c'est "
        "une heure sans lieu -- deux fuseaux n'y lisent pas le meme moment")


def test_une_date_qui_N_EXISTE_PAS_est_refusee():
    """`2026-02-30` a la bonne FORME. Valider une forme n'est pas valider un
    instant."""
    issues = _valider(_bloc(type="reference",
                            generated="{by: nokido, at: 2026-02-30T00:00:00+00:00}"))
    assert issues, (
        "le 30 fevrier a ete accepte : le validateur controle une regex, pas "
        "un calendrier")


def test_un_instant_valide_avec_offset_passe():
    assert _valider(_bloc(type="reference",
                          generated="{by: nokido, at: 2026-09-22T13:57:14+00:00}")) == [], (
        "un instant parfaitement forme est refuse : le validateur est trop strict")


# ── LE VOCABULAIRE FERME ────────────────────────────────────────────────

def test_status_hors_vocabulaire_est_refuse():
    issues = _valider(_bloc(type="reference", status="peut-etre"))
    assert any("status" in str(i) for i in issues), (
        "un `status` hors {draft, stable, deprecated} est accepte : le "
        "vocabulaire n'est pas ferme, et une valeur inattendue tombe du cote "
        "sain par defaut")


@pytest.mark.parametrize("valeur", ["draft", "stable", "deprecated"])
def test_les_trois_status_du_vocabulaire_passent(valeur):
    assert _valider(_bloc(type="reference", status=valeur)) == [], valeur


# ── LE PRODUCTEUR, EPROUVE PAR NOTRE PROPRE VALIDATEUR ──────────────────
#
# Un producteur qui ecrit un frontmatter que notre validateur refuse serait la
# pire des situations : deux moities du meme contrat qui ne s'accordent pas.
# On les confronte donc l'une a l'autre.


def _produire(**kw):
    f = getattr(wm, "frontmatter_okf", None)
    assert f is not None, (
        "`forge_wiki_modules.frontmatter_okf` ABSENTE — le validateur existe, "
        "rien ne produit encore ce qu'il sait verifier")
    return f(**kw)


def test_ce_que_le_producteur_ecrit_passe_le_validateur():
    bloc = _produire(titre="Reference des modules", sha="abc123", empreinte="0dc4")
    assert _valider(bloc + "\n# Titre\n") == [], (
        "le producteur ecrit un frontmatter que NOTRE validateur refuse : les "
        "deux moities du contrat divergent")


def test_le_producteur_pose_un_instant_AVEC_offset():
    bloc = _produire(titre="X", sha="abc123", empreinte="0dc4")
    assert "+00:00" in bloc or bloc.count("Z") > 0, (
        "l'instant produit n'a pas d'offset explicite : une heure sans lieu")


def test_le_producteur_nomme_son_acteur():
    """`generated.by` dit QUI a genere. Sans lui, la provenance ne distingue
    pas un artefact du corps d'un fichier depose a la main."""
    bloc = _produire(titre="X", sha="abc123", empreinte="0dc4")
    assert "forge_wiki_modules" in bloc, (
        "l'acteur n'est pas nomme dans `generated` : %s" % bloc[:200])


def test_le_producteur_porte_le_sha_et_l_empreinte():
    """Ce que le commentaire HTML disait deja, mais dans un champ que la
    machine sait lire."""
    bloc = _produire(titre="X", sha="abc123def", empreinte="0dc48711")
    assert "abc123def" in bloc and "0dc48711" in bloc, bloc[:200]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

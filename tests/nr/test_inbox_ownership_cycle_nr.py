# -*- coding: utf-8 -*-
"""NR — cycle complet de la decision « ce sujet possede-t-il CETTE boite ».

CONTRAT (arrete par l'owner, 2026-09-22)

    Bearer -> preuve d'authentification -> sujet canonique
           -> normalisation des alias -> boite canonique
           -> comparaison avec /inbox/{agent_id}
           -> ALLOW : pop() autorise | DENY : aucun pop()

    L'ALIAS NE DECIDE JAMAIS DE L'IDENTITE.
    Il resout vers une identite canonique DEJA DEFINIE.

CE QUE CE FICHIER TESTE, ET CE QU'IL NE TOUCHE PAS
    Une fonction PURE de decision. Aucun `pop()` n'est execute ici : on ne teste
    pas une protection en consommant une boite qui contient du courrier utile.
    La route `/inbox/{agent_id}` n'est PAS armee par ce commit.

POURQUOI LA DECISION EST POSSIBLE -- ce que j'avais declare impossible
    J'ai soutenu que le contrat n'etait « pas decidable » parce que 7 alias sur
    294 designent plusieurs agents. C'etait faux, et la primitive existait :
    `forge_videur.canonical` (8 appelants) documente que

        « agt_gemini, AGY, GEMINI_RELAY, WORKER_CODE designent tous la boite
          ANTIGRAVITY. Une surface n'a PAS de boite propre : son courrier
          appartient a l'acteur qu'elle sert. »

    L'ambiguite n'etait pas un defaut du registre : c'etait le MODELE. Mesure :
    GEMINI, agt_gemini, AGY, agt_agy, GEMINI_DAEMON rendent tous `ANTIGRAVITY`.

        UNE IMPOSSIBILITE S'ENONCE APRES MESURE, JAMAIS AVANT

DEUX PIEGES QUE LA MESURE A SORTIS, ET QUE LE CONTRAT DOIT FERMER
    1. `canonical("INCONNU_XYZ")` rend `INCONNU_XYZ` -- un REPLI sur le nom brut.
       Comparer naivement deux canonicalisations laisserait n'importe qui
       s'inventer un nom et demander la boite du meme nom : l'egalite serait
       vraie sans qu'aucune identite existe. Le repli fabrique une
       AUTO-AUTORISATION.
    2. `_index_boites` avale son erreur et rend le cache precedent (ou vide) si
       le registre devient illisible -- tout retombe alors sur le nom brut. Un
       garde d'autorisation ne devient JAMAIS permissif quand sa source se tait.

        UNKNOWN = REFUSE, et un index muet est un UNKNOWN.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]
for _p in (_RACINE, _RACINE / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_videur as v  # noqa: E402 — apres l'ajustement de sys.path


def _d(agent_id, sujet, prouve=True):
    """Aucun `skipif`, aucun `importorskip` sur le LIVRABLE.

    Une decision d'autorisation absente doit rendre ces tests ROUGES. Un skip
    passerait la CI en ne mesurant rien -- c'est le faux vert que la methode
    par cliquets interdit, et le contrat serait « verifie » par du vide.
    """
    decide = getattr(v, "peut_consommer_boite", None)
    assert decide is not None, (
        "forge_videur.peut_consommer_boite ABSENTE — la decision d'ownership "
        "n'est pas ecrite : le contrat n'est verifie par personne")
    return decide(agent_id, sujet=sujet, sujet_prouve=prouve)


# ── LES SIX CAS DU CONTRAT ───────────────────────────────────────────────

def test_meme_sujet_meme_boite_ALLOW():
    r = _d("CLAUDE", "CLAUDE")
    assert r["allow"] is True, r


def test_sujet_different_DENY():
    """Le coeur du defaut : qui connait un agent_id prend son courrier."""
    r = _d("CLAUDE", "ANTIGRAVITY")
    assert r["allow"] is False, r


def test_un_alias_VALIDE_resout_vers_le_meme_sujet():
    """C'est le cas du consommateur REEL : `gemini_poll_daemon` s'annonce
    `GEMINI` et ecoute `/inbox/agt_gemini`. Si ce test rougit, le durcissement
    couperait le daemon -- et ce serait la raison de ne PAS armer."""
    r = _d("agt_gemini", "GEMINI")
    assert r["allow"] is True, (
        "le daemon legitime serait COUPE par le durcissement : %s" % r)


def test_un_alias_ne_DECIDE_pas_de_l_identite():
    """Deux alias de la MEME boite s'accordent ; un alias d'une AUTRE boite non.
    L'alias resout, il ne fonde pas l'identite."""
    assert _d("agt_agy", "AGY")["allow"] is True
    assert _d("agt_gemini", "CLAUDE")["allow"] is False


def test_un_nom_INCONNU_ne_s_auto_autorise_pas():
    """PIEGE 1. `canonical` retombe sur le nom brut : sans garde explicite,
    `FOO` demandant `/inbox/FOO` passerait par simple egalite."""
    r = _d("INCONNU_XYZ_42", "INCONNU_XYZ_42")
    assert r["allow"] is False, (
        "un nom absent du registre s'est auto-autorise : le repli de "
        "`canonical` sur le nom brut fabrique une identite. %s" % r)


def test_sujet_NON_PROUVE_DENY():
    """`X-Agent-Name` est DECLARATIF. Sans preuve d'authentification liee au
    porteur, l'appelant n'est pas un sujet -- il est une affirmation."""
    r = _d("CLAUDE", "CLAUDE", prouve=False)
    assert r["allow"] is False, (
        "une identite DECLAREE a suffi : identite declaree != authentifiee. %s" % r)


def test_sujet_ABSENT_DENY():
    for vide in (None, "", "   "):
        assert _d("CLAUDE", vide)["allow"] is False, vide


# ── PIEGE 2 : la source qui se tait ──────────────────────────────────────

def test_index_ILLISIBLE_refuse_au_lieu_de_laisser_passer(monkeypatch):
    """Registre muet -> aucune boite connue -> DENY. Un garde qui devient
    permissif quand sa source tombe protege exactement tant qu'on n'en a pas
    besoin."""
    monkeypatch.setattr(v, "_index_boites", lambda: {})
    r = _d("CLAUDE", "CLAUDE")
    assert r["allow"] is False, (
        "index vide et pourtant ALLOW : le garde s'ouvre quand le registre "
        "se tait. %s" % r)
    assert "lisible" in r["reason"].lower() or "index" in r["reason"].lower(), r


def test_la_raison_est_toujours_DITE():
    """Un refus qui ne dit pas pourquoi n'est pas instruisable."""
    for cas in (_d("CLAUDE", "ANTIGRAVITY"), _d("CLAUDE", "CLAUDE", prouve=False),
                _d("INCONNU_XYZ_42", "INCONNU_XYZ_42")):
        assert cas.get("reason"), cas


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

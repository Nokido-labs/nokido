# -*- coding: utf-8 -*-
"""NR — SENSIBILISATION : un rappel repete assez souvent devient un mur.

Directive owner du 2026-09-13, par analogie du corps (axe principal du dev) :
« un enfant se brule en mettant la main au feu, il l'assimile et ne le refait
plus jamais ; et surtout le signal de chaleur lui fait retirer la main tout de
suite ». Trois proprietes du reflexe nociceptif, et une seule etait cablee ici :

  1. le retrait PRECEDE la conscience (arc spinal ~25 ms, douleur corticale
     ~300 ms) -> un garde qui laisse l'agent decider est hors delai ;
  2. l'apprentissage est ONE-SHOT -> une brulure suffit, pas 2 886 ;
  3. un stimulus repete SANS consequence produit l'HABITUATION -> un nudge
     permanent n'echoue pas seulement, il ENTRAINE a l'ignorer.

Mesure du 2026-09-13, sur une seule session et un seul agent :
  gates BLOQUANTS (bash_guard, forge_tool_gate, CRITICAL_FILES) : 100 % suivis ;
  nudges (capability_gate, avertissement_reflexe de governed_edit)  : 0 % suivis,
  dont 4 emissions ignorees 4 fois. Et 13,2 % de consultation sur 2 886 editions.

Ce fichier verrouille la SENSIBILISATION : le gate compte ses propres rappels et
abaisse son seuil quand le meme revient — comme un tissu deja lese. Avec sa
reciproque, l'HABITUATION : un rappel qui n'est plus revu depuis longtemps est
oublie, sinon on accumule des peages morts.

Precedent deja dans le fichier gate (mur des dumps, 2026-09-06) : « une
discipline qui echoue trois fois en trois heures ne tient pas par la volonte :
elle devient un mur ». Le seuil de 3 vient de la, il n'est pas invente ici.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

gate = pytest.importorskip("hook_capability_gate")


def test_les_seuils_sont_declares():
    """Un seuil enfoui est un seuil qu'on ne peut ni lire ni mesurer.

    Mesure 2026-09-05 : deux defauts pour un meme garde (15 s / 60 s) = piege de
    relecture, on lisait l'un et l'autre s'appliquait.
    """
    assert gate.PROMOTION_SEUIL >= 2, "un seul rappel ne fait pas une serie"
    assert gate.PROMOTION_FENETRE_S > 0
    assert gate.OUBLI_S > gate.PROMOTION_FENETRE_S, (
        "l'oubli doit etre PLUS LONG que la fenetre de promotion, sinon un rappel "
        "est oublie avant d'avoir pu compter"
    )


def test_un_premier_rappel_reste_un_nudge():
    """Contre-epreuve : un garde qui bloque des la premiere fois se fait desarmer."""
    v = gate.promotion_verdict(["abc"], {}, time.time())
    assert v["promu"] is False


def test_le_meme_rappel_repete_devient_un_mur():
    """LE contrat : la repetition abaisse le seuil, sans qu'un agent y pense."""
    maintenant = time.time()
    journal = {"abc": [maintenant - 300, maintenant - 200, maintenant - 100]}
    v = gate.promotion_verdict(["abc"], journal, maintenant)
    assert v["promu"] is True, (
        "apres PROMOTION_SEUIL rappels dans la fenetre, le nudge doit devenir deny"
    )
    assert v["n"] >= gate.PROMOTION_SEUIL
    assert v["cle"] == "abc"


def test_un_rappel_ancien_est_OUBLIE():
    """HABITUATION : ce qui ne fait plus mal cesse d'etre surveille.

    Sans oubli, le corps accumule des peages morts et le premier rappel d'un
    defaut re-apparu bloquerait sur des occurrences vieilles de plusieurs mois.
    """
    maintenant = time.time()
    vieux = maintenant - (gate.OUBLI_S + 86400)
    journal = {"abc": [vieux, vieux + 10, vieux + 20]}
    v = gate.promotion_verdict(["abc"], journal, maintenant)
    assert v["promu"] is False, "des occurrences au-dela de OUBLI_S ne comptent plus"


def test_hors_fenetre_ne_promeut_pas():
    """Trois rappels etales sur six mois ne sont pas une recidive."""
    maintenant = time.time()
    etale = [maintenant - gate.PROMOTION_FENETRE_S - 10,
             maintenant - gate.PROMOTION_FENETRE_S - 20,
             maintenant - 5]
    v = gate.promotion_verdict(["abc"], {"abc": etale}, maintenant)
    assert v["promu"] is False


def test_deux_rappels_differents_ne_s_additionnent_pas():
    """Chaque defaut a SON seuil : sinon un agent actif se fait murer au hasard."""
    maintenant = time.time()
    journal = {"aaa": [maintenant - 10, maintenant - 20],
               "bbb": [maintenant - 30]}
    v = gate.promotion_verdict(["aaa", "bbb"], journal, maintenant)
    assert v["promu"] is False


def test_l_empreinte_est_stable_et_courte():
    """La cle du journal ne doit pas etre le message entier : il change de forme."""
    e1 = gate.empreinte_rappel("forme qui MARCHE : faire ceci")
    e2 = gate.empreinte_rappel("forme qui MARCHE : faire ceci")
    e3 = gate.empreinte_rappel("un autre rappel")
    assert e1 == e2 and e1 != e3
    assert 0 < len(e1) <= 16


def test_un_journal_illisible_ne_bloque_jamais():
    """Trois etats : un journal qu'on n'a PAS PU lire n'est pas un journal vide,
    mais il ne doit jamais produire un mur — on ne mure pas sur une absence de
    mesure. Il se tait, il ne crie pas.
    """
    v = gate.promotion_verdict(["abc"], None, time.time())
    assert v["promu"] is False

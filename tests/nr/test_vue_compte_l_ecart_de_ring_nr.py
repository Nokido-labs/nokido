# -*- coding: utf-8 -*-
"""NR — l'ecart de ring doit etre COMPTE sur trafic reel, pas estime sur une table.

POURQUOI CE FICHIER EXISTE
    `resolve_identity` expose `ring_si_borne` depuis le 2026-09-21 : ce que le
    ring VAUDRAIT si le plancher anti-spoof s'appliquait aussi au porteur du
    maitre. Le champ etait produit et lu par PERSONNE.

        PRODUCED != CONSUMED

    C'est le motif paye toute la journee, applique a mon propre correctif.

CE QUE CELA CHANGE POUR LA DECISION D'ARMEMENT
    L'estimation « 33 % du trafic » vient d'une table STATIQUE : les rings du
    registre croises avec les volumes cumules. Elle suppose que la composition
    du trafic ne bouge pas, et elle ne dit rien de ce qui se passe MAINTENANT.

    Un compteur sur le chemin reel repond a la question telle qu'elle se pose :
    « si on armait le plancher, combien d'appels seraient declasses, et
    lesquels ? » -- et il continue de repondre quand le trafic change.

        UNE DECISION D'AUTORITE SE PREND SUR UNE MESURE VIVANTE,
        PAS SUR UN INSTANTANE QU'ON RECOPIE

CE QUE CE COMPTEUR N'EST PAS
    Il n'arme rien, ne refuse rien, ne modifie aucun ring. Il OBSERVE. Un gate
    neuf est non bloquant le temps de mesurer son bruit ; ici on ne construit
    meme pas le gate -- seulement le chiffre qui permettra de decider.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]
for _p in (str(_RACINE), str(_RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_MODULE = "forge_videur_audit"


@pytest.fixture()
def vue_isolee(tmp_path, monkeypatch):
    """Vue NEUVE dans un fichier a part : un instrument ne pollue jamais la
    mesure qu'il observe."""
    m = importlib.import_module(_MODULE)
    monkeypatch.setattr(m, "_VUE", tmp_path / "vue_test.json")
    monkeypatch.setattr(m, "_vue", {})
    monkeypatch.setattr(m, "_depuis_flush", 0)
    return m


def _maitre(v, agent, ring, ring_si_borne=4):
    v.noter({"via": "master_token", "agent": agent, "ring": ring,
             "acteur": "classe:porteur_maitre", "sujet": agent,
             "ring_si_borne": ring_si_borne},
            "_resolve_ring", {"decision": "ALLOW"})


def test_la_vue_expose_un_compteur_d_ecart(vue_isolee):
    d = vue_isolee.vue()
    assert "ecart_si_borne" in d, (
        "`ring_si_borne` est produit et compte NULLE PART : l'impact d'un "
        "durcissement reste une estimation sur table statique")


def test_un_appel_declasse_est_compte(vue_isolee):
    """SUPERVISOR obtient 1 ; sous le plancher il obtiendrait 4."""
    _maitre(vue_isolee, "SUPERVISOR", ring=1)
    e = vue_isolee.vue()["ecart_si_borne"]
    assert e["observes"] == 1
    assert e["declasses"] == 1
    assert e["by_agent"].get("SUPERVISOR") == 1


def test_un_appel_sans_ecart_est_observe_mais_pas_declasse(vue_isolee):
    """CONTRE-EPREUVE. POST_COMMIT a deja ring 4 : armer ne lui coute RIEN.

    Sans cette distinction, le compteur dirait « 21 647 appels impactes » la
    ou 14 478 d'entre eux ne changeraient pas d'un iota -- et la decision se
    prendrait sur un chiffre trois fois trop gros.
    """
    _maitre(vue_isolee, "POST_COMMIT", ring=4)
    e = vue_isolee.vue()["ecart_si_borne"]
    assert e["observes"] == 1
    assert e["declasses"] == 0, "un appel sans ecart est compte comme declasse"
    assert "POST_COMMIT" not in e["by_agent"]


def test_le_compteur_nomme_QUI_serait_declasse(vue_isolee):
    """Un total ne suffit pas : couper 33 % du trafic n'a pas le meme sens
    selon que c'est le superviseur ou un client anonyme."""
    _maitre(vue_isolee, "SUPERVISOR", ring=1)
    _maitre(vue_isolee, "WEBHUB", ring=2)
    _maitre(vue_isolee, "WEBHUB", ring=2)
    _maitre(vue_isolee, "POST_COMMIT", ring=4)
    e = vue_isolee.vue()["ecart_si_borne"]
    assert e["observes"] == 4
    assert e["declasses"] == 3
    assert e["by_agent"] == {"SUPERVISOR": 1, "WEBHUB": 2}


def test_un_appel_hors_maitre_n_entre_pas_dans_le_compteur(vue_isolee):
    """SYMETRIQUE : le compteur mesure l'ecart PROPRE au porteur du maitre.

    Y verser les autres provenances gonflerait le denominateur et ferait
    paraitre l'impact plus petit qu'il n'est.
    """
    vue_isolee.noter({"via": "token", "agent": "GEMINI", "ring": 1},
                     "_resolve_ring", {"decision": "ALLOW"})
    e = vue_isolee.vue()["ecart_si_borne"]
    assert e["observes"] == 0 and e["declasses"] == 0


def test_un_ring_illisible_ne_compte_pas_comme_un_ecart(vue_isolee):
    """UNKNOWN != NO. Une valeur absente ou non numerique ne doit pas
    fabriquer un declassement -- ni en effacer un."""
    vue_isolee.noter({"via": "master_token", "agent": "X", "ring": None,
                      "ring_si_borne": 4}, "_resolve_ring", {})
    vue_isolee.noter({"via": "master_token", "agent": "Y", "ring": 1,
                      "ring_si_borne": "illisible"}, "_resolve_ring", {})
    e = vue_isolee.vue()["ecart_si_borne"]
    assert e["declasses"] == 0, "un ring illisible a ete compte comme un ecart"
    assert e.get("illisibles") == 2, (
        "ce qui n'a PAS pu etre juge doit etre compte a part, jamais range du "
        "cote sain")


def test_le_compteur_dit_ce_qu_il_mesure(vue_isolee):
    """Un instrument nomme son unite : ici des OBSERVATIONS, pas des requetes."""
    e = vue_isolee.vue()["ecart_si_borne"]
    assert e.get("note"), "le compteur n'explique pas ce qu'il compte"


def test_le_compteur_n_arme_rien(vue_isolee):
    """LA RETENUE, verrouillee : observer ne doit jamais modifier le ring."""
    _maitre(vue_isolee, "SUPERVISOR", ring=1)
    d = vue_isolee.vue()
    assert d["by_ring"].get("1") == 1, (
        "le ring observe a ete modifie par le compteur : un instrument qui "
        "change ce qu'il mesure n'est plus un instrument")
    assert "4" not in d["by_ring"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

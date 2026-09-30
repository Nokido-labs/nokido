# -*- coding: utf-8 -*-
"""NR — forge_handoff_worker : on teste l'EFFET, pas l'import.

Ce worker existe pour une raison mesuree (2026-08-30) : `forge_handoff` est le seul
candidat py314t qui threade reellement, mais il n'etait lance par AUCUN des 87
services — donc il tournait dans le processus du hub, avec GIL, et le gain x4,53
mesure en free-threaded etait inatteignable faute de frontiere de processus.

Deux proprietes decident de sa sagesse, et ce sont elles qu'on verrouille :

1. il ne demarre RIEN quand la RAM manque — ni quand elle est ILLISIBLE, ce qui
   n'est pas la meme chose que « il reste de la place » ;
2. il DECLARE s'il tourne sans GIL, au lieu de laisser croire au gain.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import json  # noqa: E402

from forge_handoff_worker import (  # noqa: E402
    CANAL,
    INTENT_ATTENDU,
    POOL_MAX,
    RAM_MIN_GB,
    etat_courant,
    free_threading_actif,
    taille_pool,
    un_cycle,
    valider_enveloppe,
)


def _enveloppe(**extra) -> str:
    """Enveloppe M2M valide, telle que le postal l'exige (chaine, pas dict)."""
    base = {"intent": INTENT_ATTENDU, "pointer_ref": "durable:essai:step_1",
            "confidence": 0.9, "job_id": "j1", "reply_to": "CLAUDE"}
    base.update(extra)
    return json.dumps(base)


def test_le_corps_arrive_en_CHAINE_pas_en_dict():
    """Mesure 2026-08-30 : passer un dict a `post()` leve sqlite3.ProgrammingError.

    Le postal stocke le corps dans une colonne SQL : c'est une chaine. Le worker
    doit donc decoder, pas supposer la forme.
    """
    ok, motif = valider_enveloppe(_enveloppe())
    assert ok, motif
    ok, _ = valider_enveloppe(json.loads(_enveloppe()))   # dict tolere aussi
    assert ok


def test_un_corps_non_json_est_refuse_en_le_disant():
    ok, motif = valider_enveloppe("ceci n'est pas du json")
    assert not ok and "non-JSON" in motif


def test_l_intent_M2M_est_EXIGE():
    """`post()` valide le protocole M2M : le worker parle le meme langage."""
    ok, motif = valider_enveloppe(_enveloppe(intent="COLLAB_PING"))
    assert not ok and "intent" in motif


def test_pointer_ref_est_obligatoire():
    """Le courrier porte un RENVOI, jamais la charge utile : sinon la RAM explose."""
    sans = json.dumps({"intent": INTENT_ATTENDU, "confidence": 0.9, "job_id": "j"})
    ok, motif = valider_enveloppe(sans)
    assert not ok and "pointer_ref" in motif


def test_le_canal_du_worker_a_une_identite_declaree():
    """Sans identite, `_channel_of` rend '' et le courrier n'est JAMAIS distribue.

    Mesure du jour : poste dans le vide, `delivered: []`, et rien ne le signalait —
    un garde branche sur un signal que personne n'emet.
    """
    import json as _j
    from pathlib import Path as _P

    racine = _P(__file__).resolve().parents[2]
    ident = _j.loads((racine / "config" / "agent_identities.json").read_text(encoding="utf-8"))
    agents = ident.get("agents", ident)
    assert CANAL in agents, "%s doit etre declare dans agent_identities.json" % CANAL
    assert agents[CANAL].get("channel"), "identite sans channel : courrier non distribuable"


def test_ram_sous_la_reserve_interdit_tout_travail():
    assert taille_pool(RAM_MIN_GB - 0.1, cpu_count=8) == 0
    assert taille_pool(0.0, cpu_count=8) == 0


def test_ram_ILLISIBLE_interdit_aussi_le_travail():
    """Le piege : traiter « je n'ai pas pu mesurer » comme « il reste de la place ».

    Une mesure absente n'est pas une mesure rassurante. Sans ce cas, un
    resource_state.json corrompu ferait demarrer huit threads sur une machine
    peut-etre deja saturee.
    """
    assert taille_pool(None, cpu_count=8) == 0


def test_le_pool_grandit_avec_la_ram_mais_reste_borne():
    petit = taille_pool(RAM_MIN_GB + 1.0, cpu_count=16)
    grand = taille_pool(RAM_MIN_GB + 6.0, cpu_count=16)
    assert 1 <= petit <= grand <= POOL_MAX, (petit, grand)


def test_le_pool_ne_depasse_jamais_le_nombre_de_coeurs():
    """Au-dela des coeurs, le dispatch coute plus qu'il ne rend (mesure du jour)."""
    assert taille_pool(64.0, cpu_count=2) <= 2


def test_un_cycle_a_pool_nul_ne_reclame_rien_et_dit_pourquoi():
    cr = un_cycle(0)
    assert cr["claimes"] == 0, cr
    assert cr["saute"] is True
    assert cr.get("motif"), "un cycle saute doit NOMMER sa raison"


def test_le_cycle_ne_pretend_JAMAIS_avoir_execute():
    """Reserve honnete : l'ingress est cable, l'execution du dispatch ne l'est pas.

    Sans ce test, un lecteur du compte-rendu croirait le worker au travail alors
    qu'il ne fait que reclamer et solder du courrier.
    """
    cr = un_cycle(0)
    assert cr.get("execute") == 0


def test_le_mode_free_threading_est_declare_pas_suppose():
    ft = free_threading_actif()
    assert set(ft) >= {"free_threading", "motif"}
    assert isinstance(ft["free_threading"], bool)
    assert ft["motif"], "le mode doit etre motive, pas juste booleen"


def test_l_etat_expose_la_raison_quand_le_pool_est_nul():
    e = etat_courant()
    assert "pool" in e and "free_threading" in e
    if e["pool"] == 0:
        assert e["raison_pool_nul"], (
            "un pool nul sans raison affichee est un refus muet : impossible a diagnostiquer"
        )

# -*- coding: utf-8 -*-
"""NR -- le keeper n'ordonne pas l'arret du drain d'embeddings toutes les 30 s pendant 5 min.

Enquete AGY job_0b1eed08 (owner 18/10, verifiee au journal) : sandbox/supervisor_ordres.jsonl portait 471 ordres
LLAMA_KEEPER `service/stop/NokidoEmbedTrigger` sur les 8 000 dernieres lignes, un toutes les ~30 s apres chaque
arret reel. Cause : `_drain_on_demand` juge le drain « vivant » sur un battement de moins de 300 s ; apres
l'arret, le DERNIER battement du processus mort reste frais 5 min et chaque tick redemande l'arret.

Contrats (dette, superviseur, battement et ensure remplaces par des doublures -- jamais le vrai sandbox) :
  1. un arret accepte n'est pas redemande tant qu'aucun battement n'est posterieur a cet ordre ;
  2. un battement posterieur a l'ordre (le drain a ete relance) redonne lieu a un arret ;
  3. un arret REFUSE (success False) est retente au tick suivant -- REQUESTED != ACHIEVED.
"""
import os
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_llama_keeper as K  # noqa: E402
from nokido_agent.tools import forge_ensure_service as E  # noqa: E402

pytestmark = pytest.mark.timeout(60)


@pytest.fixture()
def drain(monkeypatch, tmp_path):
    hb = tmp_path / "embed_auto_trigger.heartbeat"
    hb.write_text("x", encoding="utf-8")
    t0 = time.time() - 10
    os.utime(hb, (t0, t0))
    ordres = []
    reponse = {"success": True}
    monkeypatch.setattr(K, "HB_DRAIN", hb)
    monkeypatch.setattr(K, "_DRAIN_ARRET_TS", 0.0, raising=False)
    monkeypatch.setattr(K, "MONITOR_ONLY", False)
    monkeypatch.setattr(K, "_dette_embed", lambda: 0)
    monkeypatch.setattr(K, "_supervisor_claimed", lambda: set())
    monkeypatch.setattr(E, "ensure", lambda nom, acte: (ordres.append((nom, acte)), dict(reponse))[1])
    return hb, ordres, reponse


def test_un_arret_accepte_n_est_pas_redemande_sur_le_battement_du_mort(drain):
    hb, ordres, _ = drain
    K._drain_on_demand(50.0)
    K._drain_on_demand(50.0)
    K._drain_on_demand(50.0)
    assert ordres == [("NokidoEmbedTrigger", "stopped")]


def test_un_battement_posterieur_a_l_ordre_redonne_un_arret(drain):
    hb, ordres, _ = drain
    K._drain_on_demand(50.0)
    t = time.time() + 5
    os.utime(hb, (t, t))
    K._drain_on_demand(50.0)
    assert ordres == [("NokidoEmbedTrigger", "stopped")] * 2


def test_un_arret_refuse_est_retente(drain):
    hb, ordres, reponse = drain
    reponse["success"] = False
    K._drain_on_demand(50.0)
    K._drain_on_demand(50.0)
    assert len(ordres) == 2

# -*- coding: utf-8 -*-
"""NR (19/10, relecture pair claude.ai pair_1df7144aae22bdf5, verifiee sur piece) : deux defauts du verdict automatique.

1. SECRET : `_emettre_transient` publiait au tableau noir les 300 derniers caracteres du `detail` BRUT (sortie du CLI
   de l'agent) -- sans `_caviarder`, alors que `_clore_delegation` le caviardait. Une erreur de fournisseur qui recopie
   un en-tete d'autorisation partait telle quelle.
2. VIDE MASQUE : `verdict_automatique` cherchait `_RE_PANNE_INFRA` dans TOUTE la prose de l'agent avant le test VIDE --
   un compte rendu qui CITE un 429 faisait d'un vide prouve un INCONNU. Une panne d'infrastructure se lit en TETE de
   sortie (comme `_panne_cli`), pas au milieu d'un rapport.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402

TEMOIN = "tok_" + "A1b2C3d4E5f6" * 4


def test_le_transient_panne_est_caviarde(monkeypatch):
    publie = []
    import nokido_agent.app.forge_swarm_blackboard as BB
    monkeypatch.setattr(BB, "apply_fact_sync", lambda zone, valeur, **k: publie.append(valeur) or {"ok": True})
    T._emettre_transient("MISTRAL", "job_x", "panne", "Error: 429 Too Many Requests ; Authorization: Bearer " + TEMOIN)
    assert publie and TEMOIN not in publie[0]


def test_un_rapport_qui_cite_un_429_reste_vide():
    effet = "[effet observe] commits produits : 0 (a..a) ; fichiers non commites : 0 ; [AUCUN EFFET] 0 commit"
    rapport = ("J'ai lu les journaux de l'executeur et le harness. " * 12
               + "Le fournisseur avait rendu un 429 Too Many Requests la veille, sans lien avec cette tache.")
    assert T.verdict_automatique(False, effet, rapport, None) == "VIDE"


def test_une_panne_en_tete_reste_inconnu():
    effet = "[effet observe] commits produits : 0 (a..a) ; fichiers non commites : 0 ; [AUCUN EFFET] 0 commit"
    assert T.verdict_automatique(False, effet, "harness MUET apres 1680 s -- job vibe_x", None) == "INCONNU"
    assert T.verdict_automatique(False, effet, "Error: Client error '429 Too Many Requests'", None) == "INCONNU"

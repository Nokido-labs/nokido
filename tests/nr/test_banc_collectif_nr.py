# -*- coding: utf-8 -*-
"""NR -- le banc collectif compare deux bras sur les MEMES taches et ne declare un gain qu'au-dela du bruit.

Owner 15/10 : « Banc d'abord, puis mode revue ». `tools/forge_banc_collectif.comparer` (pur, sans reseau) :
  1. compte les taches SAUVEES par l'equipe et PERDUES (regressions), sur les taches communes seulement ;
  2. compte les appels reels (1 + corrections) de chaque bras ;
  3. ne dit « GAIN COLLECTIF MESURE » qu'au-dela du bruit des discordants (McNemar approche) ;
  4. aucune tache commune -> INCONNU, jamais « 0 % ».
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_banc_collectif as banc  # noqa: E402


def _run(passes, repairs=0):
    return {"elapsed_s": 10.0, "results": [{"task_id": "T%d" % i, "pass": p, "repairs": repairs}
                                           for i, p in enumerate(passes)]}


def test_gain_net_au_dela_du_bruit():
    seul = _run([False] * 20 + [True] * 20, repairs=2)
    equipe = _run([True] * 40, repairs=1)
    c = banc.comparer(seul, equipe)
    assert c["taches_communes"] == 40 and c["pass_rate"] == {"seul": 50.0, "equipe": 100.0}
    assert len(c["sauvees_par_equipe"]) == 20 and c["perdues_par_equipe"] == []
    assert c["appels"] == {"seul": 120, "equipe": 80}
    assert c["verdict"].startswith("GAIN COLLECTIF MESURE")


def test_ecart_sous_le_bruit_n_est_pas_un_gain():
    seul = _run([True, False, True, False] * 10)
    equipe = _run([False, True, True, False] * 10)
    c = banc.comparer(seul, equipe)
    assert c["gain_points"] == 0.0 and "SOUS LE BRUIT" in c["verdict"]


def test_une_erreur_de_transport_n_est_jamais_une_tache_sauvee():
    # Banc 164 du 15/10 : groq en quota rend llm_error a partir de la tache 98. Sans exclusion, 60 « sauvees ».
    seul = _run([True] * 20 + [False] * 20)
    for r in seul["results"][20:]:
        r["reason"] = "llm_error"
    equipe = _run([True] * 40)
    c = banc.comparer(seul, equipe)
    assert c["taches_communes"] == 20 and len(c["hors_mesure_transport"]) == 20
    assert c["sauvees_par_equipe"] == [] and c["verdict"].startswith("AUCUN ECART")
    tout_transport = banc.comparer(seul, {"results": [dict(r, reason="llm_error") for r in equipe["results"]]})
    assert tout_transport["taches_communes"] == 0 and tout_transport["verdict"].startswith("INCONNU")


def test_aucun_ecart_et_aucune_tache_commune():
    assert banc.comparer(_run([True, False]), _run([True, False]))["verdict"].startswith("AUCUN ECART")
    c = banc.comparer({"results": []}, _run([True]))
    assert c["taches_communes"] == 0 and c["verdict"].startswith("INCONNU") and c["pass_rate"]["seul"] is None

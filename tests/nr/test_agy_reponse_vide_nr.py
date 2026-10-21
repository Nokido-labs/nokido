"""NR -- une sortie AGY « SUCCESS » a reponse VIDE n'est pas un succes ; les actions refusees par son bac sont DITES.

Mesure 19/10 02:38 (journal NokidoTaskExecutorAntigravity, job_3e380d6a) : `{"status":"SUCCESS","response":"",
..."denied_actions":[{"action":"read_file","display_name":"ViewFile"}]}` apres 298 s et 220 k jetons -> l'executeur
a ecrit « DELEGATE -> AGY OK (332 chars) » : `detail = response or error or raw` retombait sur l'enveloppe JSON, et le
statut seul faisait le verdict. DECLARE n'est pas ACHIEVED.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402


def test_succes_a_reponse_vide_est_un_echec_qui_nomme_les_refus():
    raw = json.dumps({"status": "SUCCESS", "response": "  ", "denied_actions": [
        {"action": "read_file", "display_name": "ViewFile"}]})
    ok, detail = T.lire_sortie_agy(raw)
    assert ok is False and "REPONSE VIDE" in detail and "read_file" in detail


def test_succes_avec_reponse_reste_un_succes():
    ok, detail = T.lire_sortie_agy(json.dumps({"status": "SUCCESS", "response": "fait : rapport ecrit"}))
    assert ok is True and detail == "fait : rapport ecrit"


def test_erreur_et_sortie_illisible():
    ok, detail = T.lire_sortie_agy(json.dumps({"status": "ERROR", "error": "quota"}))
    assert ok is False and detail == "quota"
    ok, detail = T.lire_sortie_agy("")
    assert ok is False and "vide" in detail

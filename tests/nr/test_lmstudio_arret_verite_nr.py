# -*- coding: utf-8 -*-
"""NR (3/11) : `nokido_ensure_service lmstudio stopped` a rendu « RAM inchangee (aucun modele n'etait resident) »
alors que node.exe sous llmster.exe tenait 5,42 Go (qwen2.5-7b-instruct charge). `lms server stop` coupe le
SERVEUR HTTP, pas le moteur : le modele reste. Contrat : (a) l'arret decharge les modeles AVANT de couper le serveur ;
(b) le verdict ne deduit jamais l'absence de modele d'une RAM qui ne bouge pas -- il dit ce que llmster tient encore.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_ensure_service as ES  # noqa: E402


def test_ram_inchangee_avec_moteur_charge_le_dit():
    d = ES._verdict_arret_lmstudio(0.02, 5.42)
    assert "aucun modele" not in d and "5.42" in d and "llmster" in d, d


def test_vraie_liberation_annoncee():
    d = ES._verdict_arret_lmstudio(5.4, 0.05)
    assert "+5.40 Go rendus" in d, d


def test_moteur_vide_et_ram_stable():
    d = ES._verdict_arret_lmstudio(0.0, 0.05)
    assert "aucun modele" in d, d   # PROUVE par la mesure du moteur, plus deduit de la RAM


def test_l_arret_decharge_avant_de_couper_le_serveur():
    src = (ROOT / "tools" / "forge_ensure_service.py").read_text(encoding="utf-8")
    i = src.find("def _lmstudio(")
    corps = src[i:src.find("\ndef ", i + 5)]
    assert corps.find('["unload", "--all"]') != -1 and corps.find('["unload", "--all"]') < corps.find('if desire == "stopped":')

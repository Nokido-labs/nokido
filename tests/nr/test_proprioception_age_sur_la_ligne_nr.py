"""NR -- le bloc proprioceptif dit l'AGE du bilan sur chaque ligne (owner 18/10 : « la ram est a 73% ! ta mesure est
encore fausse »).

Mesure du 18/10 : le hook UserPromptSubmit affichait « ❌ RAM hote a 94.7% » tire d'un bilan vieux de 37 a 61 min ;
l'age n'apparaissait que sur une note SEPAREE, et l'agent a relaye le chiffre comme une mesure presente. Une valeur
instantanee (RAM) sans son age sur la meme ligne se lit comme actuelle.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import forge_memoire_active as ma  # noqa: E402


def _bilan(tmp_path, age_s):
    p = tmp_path / "health_diagnostic.json"
    p.write_text(json.dumps({"score": 48, "confiance": 0.91,
                             "gaps": ["❌ RAM hôte à 94.7% — au-delà du seuil"]}), encoding="utf-8")
    t = time.time() - age_s
    os.utime(p, (t, t))
    return p


def test_un_bilan_ancien_porte_son_age_sur_chaque_ligne(tmp_path, monkeypatch):
    _bilan(tmp_path, 48 * 60)
    monkeypatch.setattr(ma, "SANDBOX", tmp_path)
    entrees, note = ma._proprioceptive()
    ram = [e["texte"] for e in entrees if "RAM" in e["texte"]]
    assert ram and "il y a 48 min" in ram[0], ram
    assert all("il y a" in e["texte"] for e in entrees), "le score aussi date du bilan"
    assert note and "48 min" in note


def test_un_bilan_frais_n_est_pas_surcharge(tmp_path, monkeypatch):
    _bilan(tmp_path, 5)
    monkeypatch.setattr(ma, "SANDBOX", tmp_path)
    entrees, _ = ma._proprioceptive()
    assert not any("il y a" in e["texte"] for e in entrees)

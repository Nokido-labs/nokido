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


def _hermetique(monkeypatch, tmp_path, ram):
    """RAM et demarrage de la stack FIGES : sinon le verdict depend de la machine (8/11, CI en lots : 2 rouges quand
    la RAM reelle s'ecartait de plus de 5 points de celle du bilan)."""
    monkeypatch.setattr(ma, "SANDBOX", tmp_path)
    monkeypatch.setattr(ma, "_mesure_ram_directe", lambda: ram)
    monkeypatch.setattr(ma, "_dernier_demarrage_stack", lambda: time.time() - 86400)


def test_un_bilan_ancien_porte_son_age_sur_chaque_ligne(tmp_path, monkeypatch):
    _bilan(tmp_path, 48 * 60)
    _hermetique(monkeypatch, tmp_path, 94.7)
    entrees, note = ma._proprioceptive()
    ram = [e["texte"] for e in entrees if "RAM" in e["texte"]]
    assert ram and "il y a 48 min" in ram[0], ram
    assert all("il y a" in e["texte"] for e in entrees), "le score aussi date du bilan"
    assert note and "48 min" in note


def test_un_bilan_frais_n_est_pas_surcharge(tmp_path, monkeypatch):
    _bilan(tmp_path, 5)
    _hermetique(monkeypatch, tmp_path, 94.7)
    entrees, _ = ma._proprioceptive()
    assert not any("il y a" in e["texte"] for e in entrees)


def test_ram_contredite_nomme_la_ram_et_date_le_bilan(tmp_path, monkeypatch):
    _bilan(tmp_path, 48 * 60)
    _hermetique(monkeypatch, tmp_path, 73.0)
    entrees, _ = ma._proprioceptive()
    ram = [e["texte"] for e in entrees if "RAM" in e["texte"]]
    assert ram and "bilan perime" in ram[0] and "il y a 48 min" in ram[0] and "73.0" in ram[0], ram


def test_ram_contredite_bilan_frais_sans_age(tmp_path, monkeypatch):
    _bilan(tmp_path, 5)
    _hermetique(monkeypatch, tmp_path, 73.0)
    entrees, _ = ma._proprioceptive()
    ram = [e["texte"] for e in entrees if "RAM" in e["texte"]]
    assert ram and "bilan perime" in ram[0], ram
    assert not any("il y a" in e["texte"] for e in entrees), entrees

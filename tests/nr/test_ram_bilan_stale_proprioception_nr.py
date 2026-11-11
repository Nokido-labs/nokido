# -*- coding: utf-8 -*-
"""NR RED/VERT : vitaux hôte (RAM) dans le bloc proprioceptif.

DEFAUT MESURE (owner 8/11 « encore une fausse alerte ram a plus de 90 %, ce n'etait pas le cas ») :
la ligne `[memoire:proprioceptive] ETAT DU CORPS` du hook UserPromptSubmit affichait
« ❌ RAM hote a 90.6% … (bilan il y a 14 min) », texte issu de health_diagnostic.json
depuis audit['host_vitals']['ram_pct'], alors que le bilan datait d'AVANT un reboot full stack.
Mesure directe (GlobalMemoryStatusEx) a 73.8 %.
STALE affiche comme present = violation de la constitution.

Contrat :
1) Bilan a 90.6 % + mesure directe simulee a 73 % -> aucune ligne « ❌ RAM hote a 90.6% »
   et affichage « bilan perime (90.6% il y a N min), mesure directe 73.0% ».
2) Bilan anterieur au dernier demarrage du hub/superviseur -> STALE, jamais affiche comme alerte presente.
3) Mesure directe illisible -> « RAM ILLISIBLE », jamais l'ancienne valeur presentee comme actuelle.
4) Mesure directe concordante (ecart <= 5 points) -> valeur directe affichee.
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


def _creer_bilan(tmp_path, age_s, ram_pct=90.6):
    p = tmp_path / "health_diagnostic.json"
    p.write_text(
        json.dumps({
            "score": 45,
            "confiance": 0.90,
            "host_vitals": {"ram_pct": ram_pct},
            "gaps": [f"❌ RAM hôte à {ram_pct}% — au-delà du seuil où le gate P1 refuse tout spawn (85%)"],
        }),
        encoding="utf-8",
    )
    t = time.time() - age_s
    os.utime(p, (t, t))
    return p


def test_bilan_90_et_mesure_directe_73_aucune_fausse_alerte(tmp_path, monkeypatch):
    """Bilan à 90.6% + mesure directe à 73% : aucune fausse alerte ❌ 90.6%, mention bilan périmé + mesure directe."""
    _creer_bilan(tmp_path, age_s=14 * 60, ram_pct=90.6)
    monkeypatch.setattr(ma, "SANDBOX", tmp_path)
    monkeypatch.setattr(ma, "_mesure_ram_directe", lambda: 73.0)
    monkeypatch.setattr(ma, "_dernier_demarrage_stack", lambda: time.time() - 3600)  # boot il y a 1h

    entrees, _ = ma._proprioceptive()
    textes = [e["texte"] for e in entrees]

    # Aucune fausse alerte ❌ RAM hôte à 90.6%
    assert not any("❌ RAM" in t for t in textes), f"Fausse alerte encore présente: {textes}"
    assert not any("90.6%" in t and "❌" in t for t in textes), f"Fausse alerte ❌: {textes}"

    # Doit annoncer le bilan périmé et la mesure directe
    perime = [t for t in textes if "bilan perime" in t]
    assert len(perime) == 1, f"Attendu ligne bilan perime dans {textes}"
    assert "90.6%" in perime[0] and "73.0%" in perime[0] and "il y a 14 min" in perime[0]


def test_bilan_anterieur_au_dernier_demarrage_stale_non_affiche(tmp_path, monkeypatch):
    """Bilan antérieur au redémarrage de la stack : STALE, jamais affiché comme alerte présente."""
    now = time.time()
    # Bilan vieux de 30 min, redémarrage il y a 10 min
    _creer_bilan(tmp_path, age_s=30 * 60, ram_pct=92.0)
    monkeypatch.setattr(ma, "SANDBOX", tmp_path)
    monkeypatch.setattr(ma, "_mesure_ram_directe", lambda: 70.0)
    monkeypatch.setattr(ma, "_dernier_demarrage_stack", lambda: now - 10 * 60)

    entrees, _ = ma._proprioceptive()
    textes = [e["texte"] for e in entrees]

    # Aucune alerte RAM présente
    assert not any("RAM" in t for t in textes), f"Alerte STALE affichée: {textes}"


def test_mesure_directe_illisible_affiche_ram_illisible(tmp_path, monkeypatch):
    """Mesure directe illisible -> 'RAM ILLISIBLE', jamais l'ancienne valeur présentée comme actuelle."""
    _creer_bilan(tmp_path, age_s=15 * 60, ram_pct=91.5)
    monkeypatch.setattr(ma, "SANDBOX", tmp_path)
    monkeypatch.setattr(ma, "_mesure_ram_directe", lambda: None)
    monkeypatch.setattr(ma, "_dernier_demarrage_stack", lambda: time.time() - 3600)

    entrees, _ = ma._proprioceptive()
    textes = [e["texte"] for e in entrees]

    assert not any("❌ RAM" in t for t in textes)
    assert any("RAM ILLISIBLE" in t for t in textes), f"Attendu 'RAM ILLISIBLE' dans {textes}"


def test_mesure_directe_concordante_vraie_alerte_presente(tmp_path, monkeypatch):
    """Quand la RAM est réellement à 94.7% (mesure directe 94.7%), l'alerte directe est affichée."""
    _creer_bilan(tmp_path, age_s=48 * 60, ram_pct=94.7)
    monkeypatch.setattr(ma, "SANDBOX", tmp_path)
    monkeypatch.setattr(ma, "_mesure_ram_directe", lambda: 94.7)
    monkeypatch.setattr(ma, "_dernier_demarrage_stack", lambda: time.time() - 3600)

    entrees, note = ma._proprioceptive()
    ram = [e["texte"] for e in entrees if "RAM" in e["texte"]]
    assert ram and "il y a 48 min" in ram[0], ram
    assert "94.7%" in ram[0]

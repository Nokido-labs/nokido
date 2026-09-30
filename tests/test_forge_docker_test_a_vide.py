"""tests/test_forge_docker_test_a_vide.py — Unit tests pour la sauvegarde d'état, restauration et verdict d'innocence.
"""

import json
import pytest
from pathlib import Path
from tools import forge_docker_test_a_vide as tv


def test_sauvegarder_etat_preserves_non_no_policies(tmp_path, monkeypatch):
    etat_file = tmp_path / "docker_test_a_vide_etat.json"
    monkeypatch.setattr(tv, "ETAT", etat_file)
    
    # 1. Première sauvegarde avec vraie politique
    tv._sauvegarder_etat({"cont1": "always", "cont2": "unless-stopped"})
    d1 = json.loads(etat_file.read_text(encoding="utf-8"))
    assert d1["politiques"]["cont1"] == "always"
    assert d1["politiques"]["cont2"] == "unless-stopped"
    
    # 2. Deuxième sauvegarde avec politiques neutralisées ("no")
    tv._sauvegarder_etat({"cont1": "no", "cont2": "no"})
    d2 = json.loads(etat_file.read_text(encoding="utf-8"))
    
    # Doit fusionner et CONSERVER les politiques d'origine
    assert d2["politiques"]["cont1"] == "always"
    assert d2["politiques"]["cont2"] == "unless-stopped"


def test_restaurer_status_outputs(tmp_path, monkeypatch, capsys):
    etat_file = tmp_path / "docker_test_a_vide_etat.json"
    monkeypatch.setattr(tv, "ETAT", etat_file)
    
    # 1. Fichier absent -> rien a restaurer
    rc1 = tv._restaurer()
    out1, _ = capsys.readouterr()
    assert rc1 == 0
    assert "[rien-a-restaurer]" in out1

    # 2. Fichier avec seulement des "no" -> etat-perdu
    etat_file.write_text(json.dumps({"ts": 123, "politiques": {"c1": "no"}}), encoding="utf-8")
    rc2 = tv._restaurer()
    out2, _ = capsys.readouterr()
    assert rc2 == 0
    assert "[etat-perdu]" in out2


def test_isoler_window_non_concluant(monkeypatch, capsys):
    # Mock engine up et docker execs
    monkeypatch.setattr(tv, "_engine_up", lambda: True)
    monkeypatch.setattr(tv, "_politiques", lambda: {"cont1": "always"})
    monkeypatch.setattr(tv, "_sauvegarder_etat", lambda p: p)
    monkeypatch.setattr(tv, "_d", lambda *args, **kwargs: (0, ""))
    
    times = [0.0, 0.0, 1000.0]
    monkeypatch.setattr(tv.time, "time", lambda: times.pop(0) if times else 1000.0)
    monkeypatch.setattr(tv.time, "sleep", lambda s: None)
    
    # Fenêtre 4 min (240s) avec latence 300s -> 2x latence = 600s (10 min requis)
    tv._isoler("cont1", minutes=4, latence_sec=300)
    out, _ = capsys.readouterr()
    assert "VERDICT NON CONCLUANT" in out
    assert "inferieure au seuil d'innocence" in out


def test_isoler_window_concluant_innocent(monkeypatch, capsys):
    monkeypatch.setattr(tv, "_engine_up", lambda: True)
    monkeypatch.setattr(tv, "_politiques", lambda: {"cont1": "always"})
    monkeypatch.setattr(tv, "_sauvegarder_etat", lambda p: p)
    monkeypatch.setattr(tv, "_d", lambda *args, **kwargs: (0, ""))
    
    times = [0.0, 0.0, 1000.0]
    monkeypatch.setattr(tv.time, "time", lambda: times.pop(0) if times else 1000.0)
    monkeypatch.setattr(tv.time, "sleep", lambda s: None)

    # Fenêtre 10 min (600s) avec latence 300s -> >= 2x latence
    tv._isoler("cont1", minutes=10, latence_sec=300)
    out, _ = capsys.readouterr()
    assert "N EST PAS le coupable" in out

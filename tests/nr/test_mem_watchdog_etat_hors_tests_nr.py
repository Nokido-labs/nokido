"""NR -- revue d'integration des paliers memoire (CLAUDE 28/10) : un test ne touche jamais l'etat vivant.

Mesure : sandbox/hub_mem_palier.json reel ecrit a 14:57:16 par un processus pytest de 110 Mo (le hub pese
~500 Mo et n'avait pas redemarre) pendant la passe des NR du chien de garde -- d'anciens NR appellent _check(),
qui publie desormais, sans rediriger le chemin. Sous pytest, le chemin PAR DEFAUT ne publie pas ; un chemin
redirige (monkeypatch de _ETAT_PATH) publie normalement.
"""
from __future__ import annotations

from app.hardware import mem_watchdog as M


def test_sous_pytest_le_chemin_par_defaut_ne_publie_pas(monkeypatch, tmp_path):
    faux_defaut = tmp_path / "hub_mem_palier.json"
    monkeypatch.setattr(M, "_ETAT_PATH_DEFAUT", faux_defaut)
    monkeypatch.setattr(M, "_ETAT_PATH", faux_defaut)
    M.MemWatchdog()._check(rss=100.0, maintenant=1.0)
    assert not faux_defaut.exists()


def test_un_chemin_redirige_publie_toujours(monkeypatch, tmp_path):
    monkeypatch.setattr(M, "_ETAT_PATH_DEFAUT", tmp_path / "defaut.json")
    cible = tmp_path / "redirige.json"
    monkeypatch.setattr(M, "_ETAT_PATH", cible)
    M.MemWatchdog()._check(rss=100.0, maintenant=1.0)
    assert cible.exists()

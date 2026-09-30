"""Delai de demarrage Docker derive de la charge (volet b du P1).

Incident source : le keeper a tue un engine SAIN parce que son boot, lent sous
RAM 88 %, depassait un delai de 90 s calibre a 70 %.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_ROOT, "tools"), os.path.join(_ROOT, "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_docker_keeper as dk  # noqa: E402


def test_ram_inconnue_retombe_sur_la_base(monkeypatch):
    """Pas de mesure = pas d'adaptation. On ne devine pas."""
    monkeypatch.setattr(dk, "_ram_pct_now", lambda: 0.0)
    t, why = dk._boot_timeout_for_load()
    assert t == dk.BOOT_TIMEOUT_S
    assert "inconnue" in why


def test_repli_monotone_croit_avec_la_pression(monkeypatch):
    monkeypatch.setattr(dk, "_load_boot_samples", lambda: [])
    vals = []
    for ram in (60.0, 70.0, 80.0, 88.0, 95.0):
        monkeypatch.setattr(dk, "_ram_pct_now", lambda r=ram: r)
        vals.append(dk._boot_timeout_for_load()[0])
    assert vals == sorted(vals), "le delai doit croitre avec la charge"
    assert vals[0] == dk.BOOT_TIMEOUT_S, "sous 70% on garde la base"
    assert vals[3] > dk.BOOT_TIMEOUT_S, "a 88% l engine sain doit avoir plus de temps"


def test_le_cas_de_l_incident(monkeypatch):
    """RAM 88 % : le budget doit depasser franchement les 90 s qui ont tue l engine."""
    monkeypatch.setattr(dk, "_load_boot_samples", lambda: [])
    monkeypatch.setattr(dk, "_ram_pct_now", lambda: 88.0)
    t, _ = dk._boot_timeout_for_load()
    assert t > 150.0


def test_jamais_au_dela_du_plafond(monkeypatch):
    monkeypatch.setattr(dk, "_load_boot_samples", lambda: [])
    monkeypatch.setattr(dk, "_ram_pct_now", lambda: 100.0)
    assert dk._boot_timeout_for_load()[0] <= dk.BOOT_TIMEOUT_MAX_S


def test_population_maigre_ne_declenche_pas_la_regression(monkeypatch):
    """Moins de MIN_SAMPLES : on ne conclut pas d'une poignee de points."""
    monkeypatch.setattr(dk, "_load_boot_samples", lambda: [(80.0, 300.0)] * (dk.BOOT_MIN_SAMPLES - 1))
    monkeypatch.setattr(dk, "_ram_pct_now", lambda: 80.0)
    assert "repli" in dk._boot_timeout_for_load()[1]


def test_regression_utilisee_des_que_la_population_suffit(monkeypatch):
    """Boots observes de plus en plus lents a mesure que la RAM monte."""
    samples = [(60.0, 40.0), (70.0, 60.0), (80.0, 90.0), (88.0, 140.0), (92.0, 180.0), (95.0, 210.0)]
    monkeypatch.setattr(dk, "_load_boot_samples", lambda: samples)
    monkeypatch.setattr(dk, "_ram_pct_now", lambda: 88.0)
    t, why = dk._boot_timeout_for_load()
    assert "regression" in why
    assert dk.BOOT_TIMEOUT_S <= t <= dk.BOOT_TIMEOUT_MAX_S
    # ~140 s observes a 88 % x marge -> nettement au-dessus de la base fixe.
    assert t > dk.BOOT_TIMEOUT_S


def test_regression_reste_bornee_sur_donnees_aberrantes(monkeypatch):
    monkeypatch.setattr(dk, "_load_boot_samples",
                        lambda: [(50.0 + i, 10_000.0 * (i + 1)) for i in range(8)])
    monkeypatch.setattr(dk, "_ram_pct_now", lambda: 90.0)
    assert dk._boot_timeout_for_load()[0] <= dk.BOOT_TIMEOUT_MAX_S


def test_purge_du_verrou_vhd_est_armee_par_defaut(monkeypatch):
    """CAUSE RACINE du sawtooth (22-07, re-mesuree 24-07 12:09:29Z) :
    docker_data.vhdx reste ATTACHE apres une mort brutale
    (WSL_E_USER_VHD_ALREADY_ATTACHED) -> chaque boot echoue son mount -> boucle
    auto-entretenue, meme Nokido arrete. `--unmount` purge sans tuer WSL, la ou
    `--shutdown` decapitait un Docker sain en plein boot (doom-loop 23-07)."""
    appels = []
    monkeypatch.setattr(dk, "_active_console_session_id", lambda: None)
    monkeypatch.setattr(dk.subprocess, "run",
                        lambda *a, **k: appels.append(a[0]) or type("R", (), {"returncode": 0})())
    monkeypatch.delenv("DOCKER_KEEPER_WSL_UNMOUNT", raising=False)
    dk._wsl_unmount()
    assert appels and appels[0][:2] == ["wsl", "--unmount"], appels


def test_purge_vhd_desarmable(monkeypatch):
    appels = []
    monkeypatch.setattr(dk, "_active_console_session_id", lambda: None)
    monkeypatch.setattr(dk.subprocess, "run", lambda *a, **k: appels.append(a[0]))
    monkeypatch.setenv("DOCKER_KEEPER_WSL_UNMOUNT", "0")
    dk._wsl_unmount()
    assert appels == []


def test_purge_vhd_ne_leve_jamais(monkeypatch):
    """Best-effort : une purge qui echoue ne doit pas empecher le lancement."""
    def _boom(*a, **k):
        raise OSError("wsl absent")

    monkeypatch.setattr(dk, "_active_console_session_id", lambda: None)
    monkeypatch.setattr(dk.subprocess, "run", _boom)
    monkeypatch.delenv("DOCKER_KEEPER_WSL_UNMOUNT", raising=False)
    dk._wsl_unmount()  # ne doit pas lever


def test_enregistrement_borne_le_fichier(monkeypatch, tmp_path):
    p = tmp_path / "samples.jsonl"
    monkeypatch.setattr(dk, "BOOT_SAMPLES_PATH", p)
    for i in range(dk.BOOT_SAMPLES_KEEP + 25):
        dk._record_boot_sample(30.0 + i, 80.0)
    assert len(dk._load_boot_samples()) <= dk.BOOT_SAMPLES_KEEP


def test_enregistrement_ignore_les_mesures_vides(monkeypatch, tmp_path):
    p = tmp_path / "samples.jsonl"
    monkeypatch.setattr(dk, "BOOT_SAMPLES_PATH", p)
    dk._record_boot_sample(0.0, 80.0)
    dk._record_boot_sample(50.0, 0.0)
    assert dk._load_boot_samples() == []


def test_aller_retour_enregistrement_lecture(monkeypatch, tmp_path):
    p = tmp_path / "samples.jsonl"
    monkeypatch.setattr(dk, "BOOT_SAMPLES_PATH", p)
    dk._record_boot_sample(123.0, 87.0)
    assert (87.0, 123.0) in dk._load_boot_samples()

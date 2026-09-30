# -*- coding: utf-8 -*-
"""NR — le wheel probe ne doit ni se tromper d'interpreteur, ni ecraser une mesure.

Deux defauts MESURES le 2026-08-30, dans le meme lancement :

1. Le probe resolvait ses trois interpreteurs par `expanduser("~/miniforge3/...")`.
   Lance en `run_job`, il tourne sous le compte sandbox dont HOME vaut
   `C:\\Users\\Default` : les trois envs deviennent introuvables.
2. Il ecrivait quand meme `latest.json`, ecrasant 14 417 octets de mesures reelles
   par 581 octets d'erreurs. Le resultat se lisait alors « plus rien ne marche en
   free-threaded » au lieu de « je n'ai pas pu regarder ».

Le second est le plus grave : une sonde qui detruit la derniere mesure valide est
pire qu'une sonde qui ne tourne pas.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from forge_wheel_probe_monthly import (  # noqa: E402
    ENVS_PROVENANCE,
    TARGET_ENVS,
    _envs_depuis_services_toml,
    _envs_par_expanduser,
    doit_ecrire_latest,
    snapshot_est_reel,
)

REEL = {"envs": {"py314_gil": {"packages": []}, "py314t_nogil": {"error": "boom"}}}
ERREUR = {"envs": {"py312_base": {"error": "executable not found"},
                   "py314_gil": {"error": "executable not found"},
                   "py314t_nogil": {"error": "executable not found"}}}


def test_les_trois_envs_sont_resolus():
    assert set(TARGET_ENVS) == {"py312_base", "py314_gil", "py314t_nogil"}


def test_les_chemins_viennent_de_services_toml_et_sont_absolus():
    chemins, provenance = _envs_depuis_services_toml()
    assert chemins, "services.toml doit fournir les trois interpreteurs : %s" % provenance
    for nom, p in chemins.items():
        assert Path(p).is_absolute(), "%s n'est pas un chemin absolu : %r" % (nom, p)
        assert "Default" not in p, (
            "%s pointe vers le profil Default : c'est le bug du compte sandbox" % nom
        )


def test_la_provenance_est_declaree():
    """Un repli doit se DIRE, sinon on croit mesurer ce qu'on ne mesure pas."""
    assert ENVS_PROVENANCE
    chemins, _ = _envs_depuis_services_toml()
    if chemins:
        assert "services.toml" in ENVS_PROVENANCE
    else:
        assert "repli" in ENVS_PROVENANCE.lower()


def test_le_repli_expanduser_reste_disponible():
    assert set(_envs_par_expanduser()) == {"py312_base", "py314_gil", "py314t_nogil"}


def test_snapshot_est_reel_distingue_les_trois_cas():
    assert snapshot_est_reel(REEL) is True
    assert snapshot_est_reel(ERREUR) is False
    assert snapshot_est_reel({}) is False


def test_un_snapshot_en_erreur_n_ecrase_PAS_un_snapshot_reel():
    ok, motif = doit_ecrire_latest(ERREUR, REEL)
    assert ok is False, motif
    assert "CONSERVE" in motif


def test_un_snapshot_reel_ecrase_toujours():
    ok, _ = doit_ecrire_latest(REEL, ERREUR)
    assert ok is True
    ok, _ = doit_ecrire_latest(REEL, REEL)
    assert ok is True


def test_sans_ancien_snapshot_on_ecrit_meme_une_erreur():
    """Premier lancement : mieux vaut une trace d'echec que rien du tout."""
    ok, motif = doit_ecrire_latest(ERREUR, None)
    assert ok is True and "anterieur" in motif


def test_deux_snapshots_en_erreur_se_remplacent():
    ok, _ = doit_ecrire_latest(ERREUR, ERREUR)
    assert ok is True, "rien de reel a proteger : le plus recent doit gagner"

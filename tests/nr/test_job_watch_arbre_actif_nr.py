"""NR -- le guet ne declare plus FIGE un job dont le journal se tait mais dont l'ARBRE travaille (13/10).

Un cycle de soif a ete dit FIGE apres 15 min de journal muet alors que son enfant lisait 37 Mo/s dans la base :
le wrapper de run_job reste a 0 % pendant que l'enfant travaille. Activite illisible = dite, jamais « inactif ».
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_job_watch_cli as cli  # noqa: E402


def _job(tmp_path, nom):
    (tmp_path / ("%s.log" % nom)).write_text("...", encoding="utf-8")
    (tmp_path / ("%s.json" % nom)).write_text(json.dumps({"pid": 4242}), encoding="utf-8")


def _temps():
    t = {"v": 1000.0}
    return t, (lambda: t["v"]), (lambda _s: t.__setitem__("v", t["v"] + 600.0))


def test_un_arbre_actif_n_est_pas_fige(tmp_path):
    _job(tmp_path, "job_a")
    t, horloge, dormir = _temps()
    cumul = {"cpu": 0.0, "io": 0}

    def activite(pid):
        assert pid == 4242
        cumul["cpu"] += 2.0
        cumul["io"] += 50_000_000
        return cumul["cpu"], cumul["io"]

    vues = []
    cli.surveiller("job_a", gel_s=900, max_s=3000, intervalle=1, ecrire=vues.append, jobs_dir=tmp_path,
                   horloge=horloge, dormir=dormir, activite=activite)
    assert not any("FIGE —" in l for l in vues), vues
    assert any("arbre travaille" in l for l in vues), vues
    assert any("TOUJOURS EN COURS" in l for l in vues), vues


def test_un_arbre_inactif_est_fige_et_dit_inactif(tmp_path):
    _job(tmp_path, "job_b")
    t, horloge, dormir = _temps()
    vues = []
    cli.surveiller("job_b", gel_s=900, max_s=999999, intervalle=1, ecrire=vues.append, jobs_dir=tmp_path,
                   horloge=horloge, dormir=dormir, activite=lambda pid: (10.0, 1000))
    assert any("FIGE" in l and "INACTIF" in l for l in vues), vues


def test_une_activite_illisible_est_dite_au_verdict(tmp_path):
    _job(tmp_path, "job_c")
    t, horloge, dormir = _temps()
    vues = []
    cli.surveiller("job_c", gel_s=900, max_s=999999, intervalle=1, ecrire=vues.append, jobs_dir=tmp_path,
                   horloge=horloge, dormir=dormir, activite=lambda pid: None)
    assert any("FIGE" in l and "ILLISIBLE" in l for l in vues), vues


def test_un_client_qui_attend_un_serveur_n_est_pas_fige(tmp_path):
    """15/10 : pack natif en attente de l'embedder :8099 -- CPU et octets lus/ecrits plats, seules ses operations
    d'E/S (reseau, `other_count` sous Windows) avancent. Il etait dit FIGE."""
    _job(tmp_path, "job_d")
    t, horloge, dormir = _temps()
    cumul = {"ops": 0}

    def activite(pid):
        cumul["ops"] += 2700
        return 49.3, 45_000_000, cumul["ops"]

    vues = []
    cli.surveiller("job_d", gel_s=900, max_s=3000, intervalle=1, ecrire=vues.append, jobs_dir=tmp_path,
                   horloge=horloge, dormir=dormir, activite=activite)
    assert not any("FIGE —" in l for l in vues), vues
    assert any("arbre travaille" in l and "operations" in l for l in vues), vues


def test_trois_champs_stables_restent_fige_inactif(tmp_path):
    _job(tmp_path, "job_e")
    t, horloge, dormir = _temps()
    vues = []
    cli.surveiller("job_e", gel_s=900, max_s=999999, intervalle=1, ecrire=vues.append, jobs_dir=tmp_path,
                   horloge=horloge, dormir=dormir, activite=lambda pid: (10.0, 1000, 7))
    assert any("FIGE" in l and "INACTIF" in l for l in vues), vues


def test_le_vrai_capteur_compte_les_operations(tmp_path):
    """Chemin reel : `_activite_arbre` sur le process courant rend trois champs, et une ecriture fait avancer les
    operations (pas seulement une fonction verifiee « par lecture »)."""
    import os

    avant = cli._activite_arbre(os.getpid())
    assert avant is not None and len(avant) == 3, avant
    f = tmp_path / "temoin.bin"
    for _ in range(80):
        with open(f, "wb") as fh:
            fh.write(b"x" * 4096)
            fh.flush()
            os.fsync(fh.fileno())
    apres = cli._activite_arbre(os.getpid())
    assert apres[2] > avant[2], (avant, apres)

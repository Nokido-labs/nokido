# -*- coding: utf-8 -*-
"""NR owner 4/11 (« ram disque cpu NPU GPU, sans zone d'ombre ») : GPU et NPU entrent dans la serie des vitaux.

Le corps ne lisait que le moteur 3D du GPU, par un PowerShell plafonne a 2 s (gpu_sample_ms 2019 mesure) dont l'echec
republie l'ancienne valeur. Mesure du pre-vol : PDH en memoire, ~1,3 ms, sous le compte sandbox aussi, voit trois
adaptateurs. Un adaptateur sans moteur 3D, a moteur compute seul, est classe accelerateur ; que ce soit bien le NPU reste
a prouver sous charge.
"""
import importlib
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE.parent), str(RACINE), str(RACINE / "app")]
vc = importlib.import_module("forge_vitals_channels")

GPU = "luid_0x00000000_0x00014FE2_phys_0"
BASIC = "luid_0x00000000_0x00016AEB_phys_0"
NPU = "luid_0x00000000_0x00016B63_phys_0"


def _m(pid, luid, eng, typ, v):
    return ("pid_%d_%s_eng_%d_engtype_%s" % (pid, luid, eng, typ), v)


MOTEURS = [_m(1, GPU, 0, "3D", 10.0), _m(2, GPU, 0, "3D", 5.0), _m(3, GPU, 1, "Compute", 40.0), _m(3, GPU, 2, "VideoDecode", 2.0),
           _m(4, BASIC, 0, "3D", 0.0), _m(5, NPU, 0, "Compute", 7.5)]
DED = [(GPU, 1237 * 2**20), (BASIC, 0.0), (NPU, 0.0)]
SHA = [(GPU, 587 * 2**20), (BASIC, 0.0), (NPU, 0.0)]


def test_l_agregation_separe_gpu_et_accelerateur():
    r = vc.agreger_gpu(MOTEURS, DED, SHA)
    assert r["g3d"] == 15.0, "somme des processus sur le moteur 3D du GPU principal"
    assert r["gcp"] == 40.0, "le compute du GPU, que le corps ne lisait pas"
    assert r["gded"] == 1237 and r["gsha"] == 587
    assert r["acc"] == 7.5, "l'adaptateur a compute seul, jamais melange au GPU"


def test_le_gpu_principal_est_celui_qui_a_de_la_memoire_pas_le_rendu_de_base():
    r = vc.agreger_gpu([_m(1, BASIC, 0, "3D", 90.0), _m(2, GPU, 0, "3D", 3.0)], DED, SHA)
    assert r["g3d"] == 3.0


def test_sans_accelerateur_le_canal_est_absent_pas_nul():
    r = vc.agreger_gpu([_m(1, GPU, 0, "3D", 3.0)], [(GPU, 10.0)], [(GPU, 1.0)])
    assert "acc" not in r, "absent n'est pas 0 : un accelerateur au repos et pas d'accelerateur different"


def test_rien_a_lire_rend_rien_pas_des_zeros():
    assert vc.agreger_gpu([], [], []) == {}


def test_les_canaux_sont_declares_en_serie():
    assert vc.GROUPES.get("gpu") == (vc.grp_gpu, "serie")
    for k in ("g3d", "gcp", "gded", "gsha", "acc"):
        assert k in vc.SCHEMA


def test_premiere_collecte_ne_publie_rien(monkeypatch):
    """Un pourcentage n'a pas de valeur sans seconde collecte : 0 ferait passer un GPU sature pour un GPU au repos."""
    monkeypatch.setitem(vc._PDH_GPU, "query", None)
    monkeypatch.setitem(vc._PDH_GPU, "amorce", False)
    monkeypatch.setitem(vc._PDH_GPU, "panne", "")
    monkeypatch.setattr(vc, "_pdh_gpu_ouvrir", lambda: "")
    monkeypatch.setattr(vc, "_pdh_gpu_collecter", lambda: True)
    vals, note = vc.grp_gpu({})
    assert vals == {} and "premiere collecte" in note


def test_compteur_refuse_rend_la_raison(monkeypatch):
    monkeypatch.setattr(vc, "_pdh_gpu_ouvrir", lambda: "refuse a ce compte")
    vals, note = vc.grp_gpu({})
    assert vals == {} and "ILLISIBLE" in note and "refuse a ce compte" in note

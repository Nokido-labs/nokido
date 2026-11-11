# -*- coding: utf-8 -*-
"""NR (owner 3/11, reparation 3 : « regulateur disque etendu aux jobs ») : regulation_disque ne voyait que les services
supervises ; quatre jobs ont parcouru plus d'un million de fichiers sur C: sans etre freines. Sous saturation PROUVEE
(pression_disque == SATUREE), les jobs qui lisent/ecrivent au-dela du plancher passent en priorite d'E/S TRES BASSE
(reversible, rien n'est tue) ; au retour du calme, priorite normale rendue. OBSERVE par defaut
(NOKIDO_REGULATION_DISQUE_JOBS=observer) : journal seulement. Source des jobs vivants : os.scandir de sandbox/jobs (date
portee par l'entree de repertoire), fiche recente SANS .rc -- jamais la relecture des 35 000 fiches."""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_resource_manager as RM  # noqa: E402


def _fiche(d, jid, pid, rc=False, age_s=0):
    f = d / ("%s.json" % jid)
    f.write_text(json.dumps({"pid": pid, "started": "2026-11-03T22:00:00"}), encoding="utf-8")
    t = time.time() - age_s
    os.utime(f, (t, t))
    if rc:
        (d / ("%s.rc" % jid)).write_text("0", encoding="utf-8")


def test_jobs_vivants_sans_rc_et_recents(tmp_path):
    _fiche(tmp_path, "job_vivant", 101)
    _fiche(tmp_path, "job_fini", 102, rc=True)
    _fiche(tmp_path, "job_vieux", 103, age_s=3 * 86400)
    assert RM.jobs_vivants(tmp_path, maintenant=time.time()) == {"job_vivant": 101}


def test_freiner_seulement_sous_saturation_et_au_dessus_du_plancher():
    couts = {"job_a": (80.0, 5.0), "job_b": (2.0, 1.0)}
    assert RM.jobs_a_freiner("SATUREE", couts, io_min_mo_s=5.0) == [("job_a", 80.0)]
    assert RM.jobs_a_freiner("NORMALE", couts, io_min_mo_s=5.0) == []
    assert RM.jobs_a_freiner("ILLISIBLE", couts, io_min_mo_s=5.0) == []


class _P:
    def __init__(self, pid, enfants=()):
        self.pid, self._enfants, self.prio = pid, list(enfants), None

    def children(self, recursive=True):
        return self._enfants

    def ionice(self, v):
        self.prio = v


def test_le_geste_baisse_la_priorite_de_tout_l_arbre():
    enfant = _P(2)
    racine = _P(1, [enfant])
    n = RM._priorite_es_arbre(1, basse=True, _process=lambda pid: racine)
    assert n == 2 and racine.prio == enfant.prio == RM._IOPRIO_BASSE


def test_tick_observer_journalise_sans_agir(tmp_path, monkeypatch):
    gestes = []
    monkeypatch.setattr(RM, "_priorite_es_arbre", lambda pid, basse, **k: gestes.append((pid, basse)) or 1)
    etat = RM.regulation_disque_jobs("SATUREE", {"job_a": 101}, {"job_a": (80.0, 1.0)}, {}, mode="observer",
                                     journal=tmp_path / "j.jsonl", io_min_mo_s=5.0)
    assert gestes == [] and etat == {}
    ligne = json.loads((tmp_path / "j.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert ligne["freiner"] == ["job_a"] and ligne["mode"] == "observer"


def test_tick_bloquant_freine_puis_rend_au_calme(tmp_path, monkeypatch):
    gestes = []
    monkeypatch.setattr(RM, "_priorite_es_arbre", lambda pid, basse, **k: gestes.append((pid, basse)) or 1)
    etat = RM.regulation_disque_jobs("SATUREE", {"job_a": 101}, {"job_a": (80.0, 1.0)}, {}, mode="bloquant",
                                     journal=tmp_path / "j.jsonl", io_min_mo_s=5.0)
    assert gestes == [(101, True)] and etat == {"job_a": 101}
    etat = RM.regulation_disque_jobs("NORMALE", {"job_a": 101}, {}, etat, mode="bloquant",
                                     journal=tmp_path / "j.jsonl", io_min_mo_s=5.0)
    assert gestes[-1] == (101, False) and etat == {}

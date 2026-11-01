# -*- coding: utf-8 -*-
"""NR (28/10) : le harness worker doit rester LISIBLE et VIVANT pendant un job.

Mesure : 27/10 10:02 puis 28/10 10:06:31, le worker se tait juste apres « job ... demarre » et ne
reparle plus (34 min le 28/10) : aucune fin de job, aucune pile -- le service est en « journal sans
pipe », et le chien de garde (faulthandler) vidait les piles sur sys.stderr, donc DANS LE VIDE.
Deux reparations : (1) le pouls pendant job survit a une erreur de _heartbeat (un fil qui meurt en
silence laisse le pouls perimer pendant un job sain) ; (2) le chien ecrit dans un FICHIER.
"""
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_harness_worker as hw  # noqa: E402


def test_le_pouls_pendant_job_survit_a_une_erreur(monkeypatch):
    appels = []
    fin = threading.Event()

    def heartbeat(**kw):
        appels.append(kw)
        if len(appels) == 1:
            raise OSError("base verrouillee")
        if len(appels) >= 3:
            fin.set()

    monkeypatch.setattr(hw, "_heartbeat", heartbeat)
    monkeypatch.setattr(hw, "_POULS_PENDANT_JOB_S", 0.01)
    t = threading.Thread(target=hw._battre_tant_que, args=(fin, "job_x"), daemon=True)
    t.start()
    t.join(5)
    assert len(appels) >= 3, "le fil du pouls est mort a la premiere erreur"
    assert appels[0] == {"job_en_cours": "job_x"}


def test_le_chien_ecrit_dans_un_fichier(monkeypatch, tmp_path):
    vus = {}

    def capture(delai, repeat=False, file=None):
        vus["file"] = file

    monkeypatch.setattr(hw, "_CHEMIN_CHIEN", tmp_path / "chien.log")
    monkeypatch.setattr(hw, "_FICHIER_CHIEN", None)
    import faulthandler
    monkeypatch.setattr(faulthandler, "dump_traceback_later", capture)
    monkeypatch.setattr(faulthandler, "cancel_dump_traceback_later", lambda: None)
    hw._armer_chien(10)
    assert vus["file"] is not sys.stderr
    assert Path(vus["file"].name) == tmp_path / "chien.log"
    vus["file"].close()

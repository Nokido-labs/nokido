"""NR 31/10 (owner : « orchestrer ce cycle dans un worker asynchrone pilote par l'inactivite CPU/RAM », feu vert point 3).

Etude AGY 8c421e6a8 : la phase de sommeil est decidee par l'HEURE seule (forge_circadian.PHASE_WINDOWS, current_phase) ;
_is_dormant (forge_circadian_loop) lit des tables d'une autre epoque et n'a pas d'appelant. Extension de la brique
existante : inactivite_mesuree (toutes les sources PROUVEES calmes, sinon on s'abstient) et phase_a_tirer (sommeil en
dette tire hors creneau si inactif ; creneau de sommeil differe sous charge, sauf dette > 48 h : jamais de famine).
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timedelta

from nokido_agent.app import forge_circadian as C

NUIT = datetime(2026, 10, 31, 23, 30)   # creneau NREM1
JOUR = datetime(2026, 10, 31, 14, 0)    # creneau JOUR


class _Etat:
    def __init__(self, dettes):
        self.d = dettes

    def debt_hours(self, phase):
        return self.d.get(phase, 0.0)


def _base(tmp_path, statut=None, il_y_a_min=60):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT, status TEXT, created_at TEXT, updated_at TEXT)")
    if statut:
        q = (datetime.now() - timedelta(minutes=il_y_a_min)).isoformat(timespec="seconds")
        c.execute("INSERT INTO tasks VALUES ('t', ?, ?, ?)", (statut, q, q))
    c.commit()
    c.close()
    return db


def _homeo(tmp_path, age_s=30, urgent=False):
    p = tmp_path / "homeostasis_state.json"
    p.write_text(json.dumps({"last_tick_ts": time.time() - age_s, "health_urgent": urgent}), encoding="utf-8")
    return p


def test_inactif_quand_tout_est_prouve_calme(tmp_path):
    ok, motif = C.inactivite_mesuree(tasks_db=_base(tmp_path, "done", 90), ram=55.0, cpu=8.0,
                                     homeo=_homeo(tmp_path))
    assert ok is True, motif


def test_une_tache_en_vol_empeche(tmp_path):
    ok, motif = C.inactivite_mesuree(tasks_db=_base(tmp_path, "running", 5), ram=55.0, cpu=8.0,
                                     homeo=_homeo(tmp_path))
    assert ok is False and "tache" in motif


def test_charge_ram_ou_cpu_empeche(tmp_path):
    assert C.inactivite_mesuree(tasks_db=_base(tmp_path), ram=92.0, cpu=8.0, homeo=_homeo(tmp_path))[0] is False
    assert C.inactivite_mesuree(tasks_db=_base(tmp_path), ram=50.0, cpu=70.0, homeo=_homeo(tmp_path))[0] is False


def test_source_illisible_on_s_abstient(tmp_path):
    ok, motif = C.inactivite_mesuree(tasks_db=tmp_path / "absente.db", ram=50.0, cpu=5.0, homeo=_homeo(tmp_path))
    assert ok is False and "illisible" in motif.lower()
    ok, _ = C.inactivite_mesuree(tasks_db=_base(tmp_path), ram=50.0, cpu=5.0, homeo=_homeo(tmp_path, age_s=7200))
    assert ok is False  # homeostat perime : pas une preuve de calme


def test_inactif_le_jour_tire_le_sommeil_en_dette():
    phase, raison = C.phase_a_tirer(JOUR, _Etat({C.Phase.NREM3: 30.0, C.Phase.NREM1: 5.0}), inactif=True)
    assert phase == C.Phase.NREM3 and "inactivit" in raison


def test_creneau_de_sommeil_sous_charge_differe():
    phase, raison = C.phase_a_tirer(NUIT, _Etat({C.Phase.NREM1: 30.0}), inactif=False)
    assert phase is None and "charge" in raison


def test_jamais_de_famine_au_dela_de_48h():
    phase, _ = C.phase_a_tirer(NUIT, _Etat({C.Phase.NREM1: 60.0}), inactif=False)
    assert phase == C.Phase.NREM1


def test_le_runner_auto_emprunte_l_inactivite(monkeypatch, capsys):
    """Chemin REEL : forge_circadian_runner --auto decide par phase_a_tirer(inactivite_mesuree()), plus par l'heure seule."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    import forge_circadian_runner as RUN
    tirees = []
    monkeypatch.setattr(RUN, "load_state", lambda: _Etat({C.Phase.NREM3: 30.0}))
    monkeypatch.setattr(RUN, "save_state", lambda s: None)
    monkeypatch.setattr(RUN, "inactivite_mesuree", lambda: (True, "inactif (test)"))
    monkeypatch.setattr(RUN, "fire_phase", lambda p, state=None, dry_run=False: tirees.append(p) or {"phase": p.value})
    monkeypatch.setattr(sys, "argv", ["forge_circadian_runner.py", "--auto", "--dry-run"])
    assert RUN.main() == 0
    assert tirees == [C.Phase.NREM3]


def test_chaque_decision_auto_laisse_une_trace(monkeypatch, tmp_path):
    """31/10 : Nokido-Circadian-Auto tourne sous pythonw (aucune console) ; un tick qui DIFFERE n'ecrivait rien -> le
    declenchement etait improuvable. Chaque decision --auto s'ecrit dans un journal (jsonl)."""
    import json as _j
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    import forge_circadian_runner as RUN
    journal = tmp_path / "circadian_auto.jsonl"
    monkeypatch.setattr(RUN, "JOURNAL_AUTO", journal)
    monkeypatch.setattr(RUN, "load_state", lambda: _Etat({}))
    monkeypatch.setattr(RUN, "save_state", lambda s: None)
    monkeypatch.setattr(RUN, "inactivite_mesuree", lambda: (False, "1 tache(s) en vol"))
    monkeypatch.setattr(sys, "argv", ["forge_circadian_runner.py", "--auto"])
    assert RUN.main() == 0
    ligne = _j.loads(journal.read_text(encoding="utf-8").splitlines()[-1])
    assert ligne["decision"] == "differe" and "en vol" in ligne["inactivite"] and ligne["ts"]


def test_creneau_ordinaire_inchange():
    phase, _ = C.phase_a_tirer(JOUR, _Etat({C.Phase.JOUR: 25.0}), inactif=False)
    assert phase == C.Phase.JOUR
    assert C.phase_a_tirer(JOUR, _Etat({C.Phase.JOUR: 3.0}), inactif=False)[0] is None

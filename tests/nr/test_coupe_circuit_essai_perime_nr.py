"""NR 7/11 : le verrou d'essai HALF_OPEN n'avait ni echeance ni proprietaire.

Mesure : GPTOSS, DEFAUT2, DEFAUT3, DEFAUT5 refuses 15 a 21 h apres la fin de leur repos, sans aucune tache en cours.
Mecanisme : `_reaffecter` consomme l'essai de la surface choisie, puis la boucle de l'executeur le redemande pour la
MEME tache, se voit refuser (« essai en cours ») et reaffecte a nouveau, en laissant le verrou pose.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _chemin in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

import forge_task_executor as T  # noqa: E402

T0 = 1_800_000_000.0


def _etat(monkeypatch, tmp_path, entree):
    fichier = tmp_path / "coupe_circuit.json"
    fichier.write_text(json.dumps({"A": entree}), encoding="utf-8")
    monkeypatch.setattr(T, "_fichier_coupe_circuit", lambda: fichier)
    return fichier


def _lu(fichier):
    return json.loads(fichier.read_text(encoding="utf-8"))["A"]


def test_verrou_frais_refuse_puis_perime_accorde(monkeypatch, tmp_path):
    f = _etat(monkeypatch, tmp_path, {"etat": "HALF_OPEN", "trial_active": False})
    assert T.autoriser_essai_half_open("A", maintenant=T0)[0] is True
    assert _lu(f)["essai_depuis"] == T0
    assert T.autoriser_essai_half_open("A", maintenant=T0 + T._ESSAI_TTL_S - 1)[0] is False
    assert T.autoriser_essai_half_open("A", maintenant=T0 + T._ESSAI_TTL_S + 1)[0] is True
    assert _lu(f)["essai_depuis"] == T0 + T._ESSAI_TTL_S + 1
    assert T.autoriser_essai_half_open("A", maintenant=T0 + T._ESSAI_TTL_S + 2)[0] is False


def test_verrou_ancien_format_sans_date_est_perime(monkeypatch, tmp_path):
    f = _etat(monkeypatch, tmp_path, {"etat": "HALF_OPEN", "trial_active": True})
    assert T.autoriser_essai_half_open("A", maintenant=T0)[0] is True
    assert _lu(f)["essai_depuis"] == T0


def test_succes_et_echec_retirent_la_date(monkeypatch, tmp_path):
    f = _etat(monkeypatch, tmp_path, {"etat": "HALF_OPEN", "trial_active": True, "essai_depuis": T0})
    T.enregistrer_succes_executeur("A")
    assert "essai_depuis" not in _lu(f)
    f = _etat(monkeypatch, tmp_path, {"etat": "HALF_OPEN", "trial_active": True, "essai_depuis": T0})
    T.enregistrer_echec_executeur("A", "echec", maintenant=T0)
    assert "essai_depuis" not in _lu(f)


def _tache(vers, age_s):
    quand = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(T0 - age_s))
    return {"reaffectations": json.dumps([{"de": "Z", "vers": "Y"}, {"de": "Y", "vers": vers, "quand": quand}])}


def test_essai_reserve_a_la_tache_reaffectee():
    assert T._essai_reserve_a_cette_tache(_tache("A", 60), "a", maintenant=T0) is True
    assert T._essai_reserve_a_cette_tache(_tache("B", 60), "A", maintenant=T0) is False
    assert T._essai_reserve_a_cette_tache(_tache("A", T._ESSAI_TTL_S + 1), "A", maintenant=T0) is False


def test_essai_reserve_illisible_ou_absent_refuse():
    assert T._essai_reserve_a_cette_tache({"reaffectations": None}, "A", maintenant=T0) is False
    assert T._essai_reserve_a_cette_tache({"reaffectations": "pas du json"}, "A", maintenant=T0) is False
    assert T._essai_reserve_a_cette_tache({}, "A", maintenant=T0) is False


def test_ligne_du_lot_sans_colonne_lit_la_base(monkeypatch):
    """Chemin reel : la boucle recoit un sqlite3.Row qui peut ne pas porter `reaffectations`."""
    quand = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(T0 - 60))
    trace = json.dumps([{"de": "Y", "vers": "A", "quand": quand}])

    def _base():
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE tasks (id TEXT, reaffectations TEXT)")
        conn.execute("INSERT INTO tasks VALUES ('t1', ?)", (trace,))
        return conn

    monkeypatch.setattr(T, "_db", _base)
    ligne = _base().execute("SELECT id FROM tasks").fetchone()
    assert T._essai_reserve_a_cette_tache(ligne, "A", maintenant=T0) is True


def test_boucle_executeur_consulte_la_reservation():
    source = (ROOT / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
    assert "_essai_reserve_a_cette_tache(task, _agent_dedie)" in source

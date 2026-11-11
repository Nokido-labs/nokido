"""tests/nr/test_job_watch_barriere_nr.py — NR mode barriere et flux de forge_job_watch_cli.py.

Contrat du 7/11 :
- `--barriere` (combinable avec --job, --task, --delegations) : AUCUNE ligne stdout tant que TOUT le lot n'est pas termine ou que --max-s n'est pas atteint.
- L'avancement va dans sandbox/job_watch_etat.json pour un terminal voisin.
- A la fin, UNE seule ligne JSON de 500 caracteres au plus : {termines, echecs:[id courts], gels:[id courts], expire:bool, pointeur}.
- Un job gele ou un delai depasse n'est jamais annonce comme termine.
- `--delegations` seul adopte ce comportement par defaut, l'ancien flux passe derriere `--flux`.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from tools.forge_job_watch_cli import (
    main,
    suivre_delegations,
    surveiller,
    surveiller_tache,
)


def _creer_base_tasks(chemin: Path, taches: list[dict]):
    con = sqlite3.connect(str(chemin))
    con.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, status TEXT, from_agent TEXT, "
        "created_at TEXT, progress_at TEXT, reaffectations INTEGER, result TEXT, cause_echec TEXT)"
    )
    for t in taches:
        con.execute(
            "INSERT INTO tasks (id, agent, status, from_agent, created_at, progress_at, reaffectations, result, cause_echec) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                t.get("id"),
                t.get("agent"),
                t.get("status"),
                t.get("from_agent"),
                t.get("created_at"),
                t.get("progress_at"),
                t.get("reaffectations", 0),
                t.get("result"),
                t.get("cause_echec"),
            ),
        )
    con.commit()
    con.close()


def test_barriere_3_taches_transitions_zero_avant_fin_puis_exactement_une_ligne_json(tmp_path):
    """3 taches qui changent d'etat : 0 ligne avant la fin puis exactement 1 ligne JSON valide."""
    db = tmp_path / "tasks.db"
    etat_json = tmp_path / "job_watch_etat.json"

    # Initialement: 3 taches running
    taches_init = [
        {"id": "job_001_part1", "agent": "agt_test", "status": "running", "from_agent": "demandeur", "created_at": "2026-11-07T10:00:00Z"},
        {"id": "job_002_part1", "agent": "agt_test", "status": "running", "from_agent": "demandeur", "created_at": "2026-11-07T10:00:00Z"},
        {"id": "job_003_part1", "agent": "agt_test", "status": "running", "from_agent": "demandeur", "created_at": "2026-11-07T10:00:00Z"},
    ]
    _creer_base_tasks(db, taches_init)

    lignes_sorties = []
    t_courant = [1000.0]

    def faux_time():
        return t_courant[0]

    tour = [0]

    def faux_sleep(d):
        t_courant[0] += d
        tour[0] += 1
        # Au cours de la surveillance, les 3 taches finissent par passer en done
        con = sqlite3.connect(str(db))
        if tour[0] == 1:
            con.execute("UPDATE tasks SET status='done' WHERE id='job_001_part1'")
        elif tour[0] == 2:
            con.execute("UPDATE tasks SET status='done' WHERE id='job_002_part1'")
        elif tour[0] == 3:
            con.execute("UPDATE tasks SET status='done' WHERE id='job_003_part1'")
        con.commit()
        con.close()

    rc = suivre_delegations(
        db=str(db),
        de="demandeur",
        gel_s=900,
        max_s=4800,
        intervalle=1,
        ecrire=lignes_sorties.append,
        horloge=faux_time,
        dormir=faux_sleep,
        barriere=True,
        etat_json=etat_json,
    )

    assert rc == 0
    # Exactement 1 ligne emise
    assert len(lignes_sorties) == 1
    ligne = lignes_sorties[0]
    assert len(ligne) <= 500

    data = json.loads(ligne)
    assert data["termines"] == 3
    assert data["echecs"] == []
    assert data["gels"] == []
    assert data["expire"] is False
    assert "pointeur" in data

    # Verifier que l'avancement a bien ete ecrit dans job_watch_etat.json
    assert etat_json.exists()
    etat_data = json.loads(etat_json.read_text(encoding="utf-8"))
    assert etat_data["mode"] == "delegations"
    assert etat_data["total"] == 3


def test_barriere_tache_en_echec_nommee(tmp_path):
    """Une tache en echec est nommee dans echecs (id court), pas dans termines."""
    db = tmp_path / "tasks.db"
    etat_json = tmp_path / "job_watch_etat.json"

    taches_init = [
        {"id": "job_aaa_sub1", "agent": "agt_test", "status": "running", "from_agent": "demandeur", "created_at": "2026-11-07T10:00:00Z"},
        {"id": "job_bbb_sub1", "agent": "agt_test", "status": "running", "from_agent": "demandeur", "created_at": "2026-11-07T10:00:00Z"},
    ]
    _creer_base_tasks(db, taches_init)

    lignes = []
    t_courant = [1000.0]

    def faux_time():
        return t_courant[0]

    def faux_sleep(d):
        t_courant[0] += d
        con = sqlite3.connect(str(db))
        con.execute("UPDATE tasks SET status='done' WHERE id='job_aaa_sub1'")
        con.execute("UPDATE tasks SET status='failed' WHERE id='job_bbb_sub1'")
        con.commit()
        con.close()

    rc = suivre_delegations(
        db=str(db),
        de="demandeur",
        gel_s=900,
        max_s=4800,
        intervalle=1,
        ecrire=lignes.append,
        horloge=faux_time,
        dormir=faux_sleep,
        barriere=True,
        etat_json=etat_json,
    )

    assert rc == 0
    assert len(lignes) == 1
    data = json.loads(lignes[0])
    assert data["termines"] == 1
    assert "job_bbb" in data["echecs"]
    assert data["expire"] is False


def test_barriere_expiration_max_s_expire_vrai_jamais_termine(tmp_path):
    """Expiration --max-s = expire vrai, jamais termine (taches non terminees non comptees)."""
    db = tmp_path / "tasks.db"
    etat_json = tmp_path / "job_watch_etat.json"

    taches_init = [
        {"id": "job_encours_1", "agent": "agt_test", "status": "running", "from_agent": "demandeur", "created_at": "2026-11-07T10:00:00Z"},
    ]
    _creer_base_tasks(db, taches_init)

    lignes = []
    t_courant = [1000.0]

    def faux_time():
        return t_courant[0]

    def faux_sleep(d):
        # On depasse max_s direct
        t_courant[0] += 100

    rc = suivre_delegations(
        db=str(db),
        de="demandeur",
        gel_s=900,
        max_s=50,
        intervalle=1,
        ecrire=lignes.append,
        horloge=faux_time,
        dormir=faux_sleep,
        barriere=True,
        etat_json=etat_json,
    )

    assert rc == 0
    assert len(lignes) == 1
    data = json.loads(lignes[0])
    assert data["expire"] is True
    assert data["termines"] == 0


def test_flux_conserve_ancien_flux(tmp_path):
    """--flux conserve l'ancien flux ligne par ligne des evenements."""
    db = tmp_path / "tasks.db"

    taches_init = [
        {"id": "job_flx_1", "agent": "agt_test", "status": "running", "from_agent": "demandeur", "created_at": "2026-11-07T10:00:00Z"},
    ]
    _creer_base_tasks(db, taches_init)

    lignes = []
    t_courant = [1000.0]

    def faux_time():
        return t_courant[0]

    def faux_sleep(d):
        t_courant[0] += d
        con = sqlite3.connect(str(db))
        con.execute("UPDATE tasks SET status='done' WHERE id='job_flx_1'")
        con.commit()
        con.close()
        t_courant[0] += 5000  # declenche max_s a la boucle suivante

    rc = suivre_delegations(
        db=str(db),
        de="demandeur",
        gel_s=900,
        max_s=100,
        intervalle=1,
        ecrire=lignes.append,
        horloge=faux_time,
        dormir=faux_sleep,
        barriere=False,
    )

    assert rc == 0
    # En mode flux, on a les lignes d'evenements habituelles
    assert any("STATUT" in l or "DELEGATIONS" in l for l in lignes)
    # Et aucune ligne n'est un dictionnaire JSON {termines:...}
    assert not any(l.startswith('{"termines"') for l in lignes)


def test_main_cli_delegations_defaut_barriere_et_flag_flux(tmp_path, monkeypatch, capsys):
    """Le point d'entree reel : --delegations est barriere par defaut, --flux reactive l'ancien flux."""
    db = tmp_path / "tasks.db"
    taches_init = [
        {"id": "job_m1_part", "agent": "agt_test", "status": "done", "from_agent": "me", "created_at": "2026-11-07T10:00:00Z"},
    ]
    _creer_base_tasks(db, taches_init)

    # 1. Par defaut: --delegations -> barriere
    rc = main(["--delegations", "--db", str(db), "--de", "me", "--max-s", "10", "--intervalle", "1"])
    assert rc == 0
    out, _ = capsys.readouterr()
    lignes = [l.strip() for l in out.strip().splitlines() if l.strip()]
    assert len(lignes) == 1
    d = json.loads(lignes[0])
    assert d["termines"] == 1
    assert d["expire"] is False

    # 2. Avec --flux: passe en flux
    rc = main(["--delegations", "--flux", "--db", str(db), "--de", "me", "--max-s", "0", "--intervalle", "1"])
    assert rc == 0
    out2, _ = capsys.readouterr()
    lignes2 = [l.strip() for l in out2.strip().splitlines() if l.strip()]
    # En max-s 0 immediat, fin de veille emise
    assert any("fin de veille" in l for l in lignes2)


def test_barriere_tache_done_avec_cause_echec_ou_failure_ou_rien_produit_compte_dans_echecs(tmp_path, capsys):
    """Faits mesures le 7/11 (job_5abb579a) :
    Une tache done dont cause_echec n'est pas nul, ou dont le rendu porte status_code FAILURE,
    ou [RIEN PRODUIT], compte dans echecs, pas dans termines (aussi bien via --task que --delegations).
    """
    db = tmp_path / "tasks.db"
    taches_init = [
        {
            "id": "job_5abb579a_sub1",
            "agent": "MISTRAL",
            "status": "done",
            "from_agent": "me",
            "created_at": "2026-11-07T10:00:00Z",
            "cause_echec": "QUOTA",
            "result": '{"status_code": "FAILURE", "detail": "402 Payment Required [RIEN PRODUIT]"}',
        },
        {
            "id": "job_ok123456_sub1",
            "agent": "MISTRAL",
            "status": "done",
            "from_agent": "me",
            "created_at": "2026-11-07T10:00:00Z",
            "cause_echec": None,
            "result": '{"status_code": "SUCCESS", "detail": "livraison ok"}',
        },
    ]
    _creer_base_tasks(db, taches_init)

    # 1. Test via le vrai point d'entree CLI: --task job_5abb579a_sub1 --barriere
    rc = main(["--task", "job_5abb579a_sub1", "--db", str(db), "--barriere", "--max-s", "10", "--intervalle", "1"])
    assert rc == 0
    out, _ = capsys.readouterr()
    lignes = [l.strip() for l in out.strip().splitlines() if l.strip()]
    assert len(lignes) == 1
    d = json.loads(lignes[0])
    assert d["termines"] == 0
    assert "job_5abb579a" in d["echecs"]

    # 2. Test via le vrai point d'entree CLI: --delegations --barriere
    rc2 = main(["--delegations", "--db", str(db), "--de", "me", "--barriere", "--max-s", "10", "--intervalle", "1"])
    assert rc2 == 0
    out2, _ = capsys.readouterr()
    lignes2 = [l.strip() for l in out2.strip().splitlines() if l.strip()]
    assert len(lignes2) == 1
    d2 = json.loads(lignes2[0])
    assert d2["termines"] == 1
    assert "job_5abb579a" in d2["echecs"]

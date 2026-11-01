"""NR -- suivi des delegations par Nokido, visible de TOUT CLI (owner 22/10).

RED ecrit par Claude. Owner : « des monitors sur les affectations aux autres CLI ; Claude n'est qu'un client parmi
d'autres, il faut que ca emane de Nokido, qu'on puisse le voir dans les autres CLI ». Forme : extension de
tools/forge_job_watch_cli.py (deja le suiveur de taches de la boucle), lu sur tasks.db -- la source qui porte agent,
statut, progres et reaffectations -- et pas un second systeme. Une transition se DEDUIT de deux lectures (statut ou
agent change) : aucun emetteur nouveau n'est requis, donc aucun garde branche sur un signal que personne n'emet.
Tout CLI le voit par le `run` du hub (`--delegations --une-fois`) ; une boucle le suit en continu (`--delegations`).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_job_watch_cli as W  # noqa: E402

T0 = 1_800_000_000.0


def _iso(ts):
    import datetime as dt
    return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%d %H:%M:%S")


def _base(tmp_path, lignes):
    db = tmp_path / "tasks.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, description TEXT, agent TEXT, status TEXT, result TEXT, "
                "created_at TEXT, updated_at TEXT, job_id TEXT, from_agent TEXT, progress_at REAL, reaffectations TEXT)")
    for l in lignes:
        con.execute("INSERT INTO tasks (id, agent, status, result, created_at, updated_at, from_agent, progress_at, "
                    "reaffectations) VALUES (?,?,?,?,?,?,?,?,?)", l)
    con.commit()
    con.close()
    return db


def _t(tid, agent, status, de="claude", age=600, progres=None, reaff=None, result=None):
    return (tid, agent, status, result, _iso(T0 - age), _iso(T0 - age), de, progres, reaff)


def test_vue_des_delegations_en_vol(tmp_path):
    db = _base(tmp_path, [_t("job_a", "ANTIGRAVITY", "running", progres=T0 - 30),
                          _t("job_b", "OPENCODE_GLM", "pending"),
                          _t("job_c", "MISTRAL", "done")])
    vue = W.delegations_en_vol(db, maintenant=T0)
    assert {d["task_id"] for d in vue} == {"job_a", "job_b"}, "une tache terminee n'est plus en vol"
    a = next(d for d in vue if d["task_id"] == "job_a")
    assert a["agent"] == "ANTIGRAVITY" and a["statut"] == "running" and a["age_s"] == 600
    assert a["depuis_progres_s"] == 30


def test_filtre_par_demandeur_insensible_a_la_casse(tmp_path):
    db = _base(tmp_path, [_t("job_a", "ANTIGRAVITY", "running", de="CLAUDE"),
                          _t("job_b", "OPENCODE_GLM", "pending", de="gemini")])
    assert [d["task_id"] for d in W.delegations_en_vol(db, maintenant=T0, de="claude")] == ["job_a"]


def test_transitions_deduites_de_deux_lectures():
    avant = {"job_a": {"agent": "OPENCODE_GLM", "statut": "running"},
             "job_b": {"agent": "ANTIGRAVITY", "statut": "pending"}}
    apres = {"job_a": {"agent": "OPENCODE_GPTOSS", "statut": "pending"},
             "job_b": {"agent": "ANTIGRAVITY", "statut": "running"},
             "job_c": {"agent": "MISTRAL", "statut": "pending"}}
    ev = W.transitions(avant, apres)
    genres = {(e["task_id"], e["genre"]) for e in ev}
    assert ("job_a", "REAFFECTEE") in genres, "un changement d'agent est une reaffectation, pas un silence"
    assert ("job_b", "STATUT") in genres and ("job_c", "NOUVELLE") in genres
    assert all(W.ligne_evenement(e) for e in ev)


def test_rien_ne_change_rien_n_est_ecrit():
    etat = {"job_a": {"agent": "ANTIGRAVITY", "statut": "running"}}
    assert W.transitions(etat, dict(etat)) == []


def test_tache_sans_progres_signalee_une_seule_fois(tmp_path):
    db = _base(tmp_path, [_t("job_a", "ANTIGRAVITY", "running", progres=T0 - 3600)])
    vue = W.delegations_en_vol(db, maintenant=T0)
    deja = set()
    a1 = W.alertes_gel(vue, gel_s=900, deja=deja)
    a2 = W.alertes_gel(vue, gel_s=900, deja=deja)
    assert [x["task_id"] for x in a1] == ["job_a"] and a2 == []


def test_progres_illisible_n_est_pas_un_gel(tmp_path):
    """Pas de progress_at = INCONNU : on ne fabrique pas une panne (constitution : UNKNOWN != NO)."""
    db = _base(tmp_path, [_t("job_a", "ANTIGRAVITY", "running", progres=None)])
    vue = W.delegations_en_vol(db, maintenant=T0)
    assert vue[0]["depuis_progres_s"] is None
    assert W.alertes_gel(vue, gel_s=900, deja=set()) == []


def test_point_d_entree_une_fois(tmp_path, capsys):
    """Le chemin REEL (drapeau CLI) que tout CLI emprunte par le `run` du hub."""
    db = _base(tmp_path, [_t("job_a", "ANTIGRAVITY", "running", progres=T0 - 30)])
    rc = W.main(["--delegations", "--une-fois", "--db", str(db)])
    out = capsys.readouterr().out
    assert rc == 0 and "job_a" in out and "ANTIGRAVITY" in out


def test_la_skill_partagee_dit_comment_suivre():
    """Visible des AUTRES CLI : la forme est ecrite dans une surface distribuee, pas seulement ici."""
    texte = (ROOT / "docs" / "skills" / "forge-pipeline" / "SKILL.md").read_text(encoding="utf-8")
    assert "--delegations" in texte

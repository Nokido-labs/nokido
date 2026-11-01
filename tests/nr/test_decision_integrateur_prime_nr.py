"""NR : la decision de l'INTEGRATEUR prime sur le verdict automatique de l'executeur (owner 26/10).

Mesure 26/10 : le registre sandbox/motivation_resultats.jsonl ne recevait que le verdict automatique ;
CLAUDE_HEADLESS y comptait 45 VIDE + 37 REJETEE alors que 91 de ses jobs sont cites dans alpha. Le score
hedoniste lit DEUX signaux (tasks.db a 70 %, le registre a 30 %) : la decision doit corriger les deux.
Cle de dedoublonnage = (job, repondeur) : une reaffectation garde l'echec de A ET le succes de B.
"""
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_R = Path(__file__).resolve().parents[2]
for _p in (str(_R), str(_R / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_motivation as m  # noqa: E402

J1 = "job_36bef7a6_1792940027_claude_p1_profils"
J2 = "job_4b3bbd10_1792937000_claude_soif"


def _registre(monkeypatch, tmp_path):
    p = tmp_path / "motivation_resultats.jsonl"
    monkeypatch.setattr(m, "RESULTATS", p)
    monkeypatch.setenv("NOKIDO_MOTIVATION_SANS_CORPS", "1")
    return p


def test_la_decision_porte_job_sha_source_et_motif(monkeypatch, tmp_path):
    p = _registre(monkeypatch, tmp_path)
    m.decider_integration(J1, "claude_headless", "INTEGREE", sha="9ae498fa9", motif="relu, NR verts")
    ligne = json.loads(p.read_text(encoding="utf-8").splitlines()[-1])
    assert ligne["repondeur"] == "CLAUDE_HEADLESS" and ligne["verdict"] == "INTEGREE"
    assert ligne["job_id"] == J1 and ligne["sha"] == "9ae498fa9"
    assert ligne["source"] == "integrateur" and ligne["motif"] == "relu, NR verts"


def test_l_integrateur_ecrase_le_faux_negatif_du_meme_repondeur(monkeypatch, tmp_path):
    _registre(monkeypatch, tmp_path)
    m.recompenser_resultat("CLAUDE_HEADLESS", "M:ecrit", "VIDE", preuve=J1[:40] + " : [COMMIT REFUSE]")
    m.decider_integration(J1, "CLAUDE_HEADLESS", "INTEGREE", sha="abc")
    f = m.force_repondeurs(m.lire_resultats(), "M:ecrit")["CLAUDE_HEADLESS"]
    assert (f["n"], f["integrees"]) == (1, 1)


def test_une_reaffectation_garde_l_echec_de_a_et_le_succes_de_b(monkeypatch, tmp_path):
    _registre(monkeypatch, tmp_path)
    m.recompenser_resultat("OPENCODE_GLM", "M:ecrit", "REJETEE", preuve=J2[:40] + " : syntaxe")
    m.decider_integration(J2, "CLAUDE_HEADLESS", "INTEGREE", sha="def")
    force = m.force_repondeurs(m.lire_resultats(), "M:ecrit")
    assert (force["OPENCODE_GLM"]["n"], force["OPENCODE_GLM"]["rejetees"]) == (1, 1)
    assert (force["CLAUDE_HEADLESS"]["n"], force["CLAUDE_HEADLESS"]["integrees"]) == (1, 1)


def test_sans_decision_le_registre_est_lu_comme_avant(monkeypatch, tmp_path):
    _registre(monkeypatch, tmp_path)
    m.recompenser_resultat("MISTRAL", "M:ecrit", "VIDE", preuve=J1[:40] + " : vide")
    m.recompenser_resultat("MISTRAL", "M:ecrit", "REJETEE", preuve="sans identifiant de job")
    assert m.force_repondeurs(m.lire_resultats(), "M:ecrit")["MISTRAL"]["n"] == 2


def test_le_rattrapage_retro_compte_et_se_debranche(monkeypatch, tmp_path):
    """Rattrapage owner 26/10 (161 jobs cites dans alpha) : source integrateur_retro, retour arriere par drapeau."""
    _registre(monkeypatch, tmp_path)
    m.recompenser_resultat("CLAUDE_HEADLESS", "M:ecrit", "VIDE", preuve=J1[:40] + " : [COMMIT REFUSE]")
    m.recompenser_resultat("CLAUDE_HEADLESS", "M:ecrit", "INTEGREE", job_id=J1, sha="abc",
                           source="integrateur_retro", motif="retro_alpha:abc")
    f = m.force_repondeurs(m.lire_resultats(), "M:ecrit")["CLAUDE_HEADLESS"]
    assert (f["n"], f["integrees"]) == (1, 1)
    monkeypatch.setenv("NOKIDO_MOTIVATION_SANS_RETRO", "1")
    f = m.force_repondeurs(m.lire_resultats(), "M:ecrit")["CLAUDE_HEADLESS"]
    assert (f["n"], f["integrees"]) == (1, 0)
    assert m.decisions_integrateur(m.lire_resultats()) == {}


def _taches():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE tasks (id TEXT, agent TEXT, status TEXT, result TEXT, created_at TEXT,"
              " updated_at TEXT, reaffectations TEXT, job_id TEXT)")
    quand = datetime.now().isoformat(timespec="seconds")
    c.execute("INSERT INTO tasks VALUES ('t1','CLAUDE_HEADLESS','done',"
              "'[effet observe] commits produits : 0 ; [COMMIT REFUSE] travail laisse non livre',?,?,NULL,?)",
              (quand, quand, J1))
    return c


def test_la_part_tasks_db_obeit_aussi_a_l_integrateur(monkeypatch, tmp_path):
    _registre(monkeypatch, tmp_path)
    c = _taches()
    avant = m.scores_hedonistes_mesure(["CLAUDE_HEADLESS"], c, resultats=[])["CLAUDE_HEADLESS"]
    assert (avant["livrees"], avant["touches"]) == (0, 1)
    m.decider_integration(J1, "CLAUDE_HEADLESS", "INTEGREE", sha="abc")
    apres = m.scores_hedonistes_mesure(["CLAUDE_HEADLESS"], c, resultats=m.lire_resultats())["CLAUDE_HEADLESS"]
    assert (apres["livrees"], apres["touches"]) == (1, 1)


def test_le_point_d_entree_decision_traverse_main(tmp_path):
    p = tmp_path / "reg.jsonl"
    env = dict(os.environ, NOKIDO_MOTIVATION_RESULTATS=str(p), NOKIDO_MOTIVATION_SANS_CORPS="1",
               PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, str(_R / "app" / "forge_motivation.py"), "--decision", J1,
                        "OPENCODE_GLM", "REJETEE", "--sha", "f00", "--motif", "hors sujet"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=25)
    assert r.returncode == 0, r.stderr[-400:]
    ligne = json.loads(p.read_text(encoding="utf-8").splitlines()[-1])
    assert (ligne["source"], ligne["verdict"], ligne["job_id"]) == ("integrateur", "REJETEE", J1)

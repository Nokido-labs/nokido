"""P2 du debat « contexte servi » (tour 3 tranche par l'owner le 8/11) : le reconciliateur CLOT une tache dont la
session est PROUVEE morte, apres avoir preserve son travail ; il s'abstient sur tout doute (STALE != DEAD).

Constat 8/11 : session AGY perdue, tache restee `running` des heures, travail preserve (ef1c5cf34) sans que la tache
soit close ni l'emetteur prevenu. `_tache_est_en_vol` cherchait `id LIKE '%<court>'` alors que `court_tache` rend
tete + empreinte (jamais un suffixe) : seul le repli « une tache de l'agent en vol » decidait.

Contrat (tools/forge_worktree.py) :
- `reconcilier_worktree_orphelin(..., vivacite=None, emettre=None)` et `balayer_et_reconcilier(..., vivacite=None,
  emettre=None)` ; `vivacite(pid, cree) -> True|False|None` (defaut forge_task_executor._vivacite_processus) ;
  `emettre(task_id, payload)` = task_result a l'emetteur (defaut : hub `task action=result`), payload M2M
  {intent, status_code, pointer_ref}.
- la tache du worktree se RESOUT par `court_tache(id) == court` (ou suffixe : nommage d'avant le 31/10) ; une tache
  resolue decide seule ; aucune resolue -> repli prudent actuel (toute tache de l'agent en vol = abstention).
- tache resolue `running` : pid non note -> abstention `tache_en_vol` ; vivacite None -> abstention
  `vivacite_illisible` signalee ; True -> `tache_en_vol` ; False (mort PROUVEE) -> preservation puis cloture.
- cloture = statut EXISTANT `failed`, `cause_echec='SESSION_PERDUE'`, `result` += branche preserve + sha (ou chemin
  de la sauvegarde), puis UNE emission (pointer_ref porte le sha ou la sauvegarde). Rien n'est supprime.
- verdict = grade de `scorecard_de_livraison` (OPTIMAL/PARTIAL/REJECTED/UNRATED), plus `_rejouer_tests_sur_commit`.
- sauvegarde (cas 0 commit) dont le manifeste nomme une tache `running` a mort prouvee : meme cloture.
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_worktree as W  # noqa: E402

TID = "job_999c83e8_1794163532_oauth_nkc_nb_cvt_task_assign"
AGENT = "ANTIGRAVITY"
GIT = ["git", "-c", "safe.directory=*", "-c", "user.email=t@t", "-c", "user.name=t"]


@pytest.fixture(autouse=True)
def _identite_git(monkeypatch):
    # le reconciliateur committe sans identite explicite : la CI n'a pas toujours de config globale
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"),
                 ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@t")):
        monkeypatch.setenv(k, v)


def _git(d, *a):
    return subprocess.run([*GIT, *a], cwd=d, capture_output=True, text=True, errors="replace")


def _arbre(tmp_path, fichier="travail.py", contenu="X = 1\n"):
    # `.git` en fichier, depot a cote : forme d'un vrai worktree de tache, chemins courts (MAX_PATH de la CI)
    d = tmp_path / "taches" / f"antigravity_{W.court_tache(TID)}"
    d.mkdir(parents=True)
    for a in (["init", "-q", "--separate-git-dir", str(tmp_path / "g_wt")], ["commit", "-q", "--allow-empty", "-m", "x"]):
        r = _git(d, *a)
        assert r.returncode == 0, r.stderr
    (d / fichier).write_text(contenu, encoding="utf-8")
    return d


def _base(tmp_path, lignes):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, status TEXT, result TEXT, updated_at TEXT, "
              "exec_pid INTEGER, exec_cree REAL, cause_echec TEXT, from_agent TEXT)")
    for tid, statut, pid in lignes:
        c.execute("INSERT INTO tasks (id, agent, status, result, exec_pid, exec_cree, from_agent) VALUES (?,?,?,?,?,?,?)",
                  (tid, AGENT, statut, "", pid, 1.0 if pid else None, "agt_claude"))
    c.commit()
    c.close()
    return db


def _ligne(db, tid=TID):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    try:
        return dict(c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone())
    finally:
        c.close()


def _non_committe(wt):
    return "travail.py" in _git(wt, "status", "--short", "--untracked-files=all").stdout


def _appel(wt, db, vivacite, emis, vus=None):
    vus = [] if vus is None else vus
    return W.reconcilier_worktree_orphelin(wt, root=wt, tasks_db=db, registre=set(),
                                           notifier=lambda *a: vus.append(a), vivacite=vivacite,
                                           emettre=lambda tid, p: emis.append((tid, p)))


def test_mort_prouvee_preserve_puis_clot_et_previent_l_emetteur(tmp_path):
    wt, db, emis = _arbre(tmp_path), _base(tmp_path, [(TID, "running", 4242)]), []
    r = _appel(wt, db, lambda pid, cree: False, emis)
    assert r["action"] == "preserve", r
    ligne = _ligne(db)
    assert ligne["status"] == "failed" and ligne["cause_echec"] == "SESSION_PERDUE", ligne
    assert r["sha"] in ligne["result"] and r["branche"] in ligne["result"], "la tache close pointe vers le travail"
    assert len(emis) == 1 and emis[0][0] == TID, emis
    assert {"intent", "status_code", "pointer_ref"} <= set(emis[0][1]) and r["sha"] in emis[0][1]["pointer_ref"]
    assert (wt / "travail.py").is_file(), "rien n'est supprime"


def test_verdict_est_la_scorecard_de_livraison(tmp_path):
    wt, db = _arbre(tmp_path), _base(tmp_path, [(TID, "running", 4242)])
    r = _appel(wt, db, lambda *a: False, [])
    assert r["verdict"] == "PARTIAL", r  # un .py qui compile, aucun NR livre : ni INDETERMINE ni vert


def test_vivacite_illisible_abstention_signalee(tmp_path):
    wt, db, emis, vus = _arbre(tmp_path), _base(tmp_path, [(TID, "running", 4242)]), [], []
    r = _appel(wt, db, lambda *a: None, emis, vus)
    assert r["action"] == "ignore" and r["motif"] == "vivacite_illisible", r
    assert vus, "le doute se dit"
    assert _ligne(db)["status"] == "running" and not emis
    assert _non_committe(wt), "rien n'est committe sur un doute"


def test_sans_pid_note_abstention(tmp_path):
    wt, db, emis = _arbre(tmp_path), _base(tmp_path, [(TID, "running", None)]), []
    r = _appel(wt, db, lambda *a: pytest.fail("vivacite consultee sans pid"), emis)
    assert r["action"] == "ignore" and r["motif"] == "tache_en_vol", r
    assert _ligne(db)["status"] == "running" and not emis and _non_committe(wt)


def test_session_vivante_jamais_close(tmp_path):
    wt, db, emis = _arbre(tmp_path), _base(tmp_path, [(TID, "running", 4242)]), []
    r = _appel(wt, db, lambda *a: True, emis)
    assert r["action"] == "ignore" and r["motif"] == "tache_en_vol", r
    assert _ligne(db)["status"] == "running" and not emis and _non_committe(wt)


def test_tache_resolue_par_court_tache_decide_seule(tmp_path):
    autre = "job_0a1b2c3d_1794160000_oauth_nkc_nb_cvt_task_assign"
    wt, emis = _arbre(tmp_path), []
    db = _base(tmp_path, [(TID, "done", None), (autre, "running", 77)])
    r = _appel(wt, db, lambda *a: True, emis)
    assert r["action"] == "preserve", "une AUTRE tache de l'agent ne bloque pas le worktree d'une tache close : %r" % r
    assert _ligne(db)["status"] == "done" and not emis, "tache deja terminale : ni reecrite ni re-annoncee"
    assert _ligne(db, autre)["status"] == "running"


def test_aucune_tache_resolue_repli_prudent(tmp_path):
    wt, emis = _arbre(tmp_path), []
    db = _base(tmp_path, [("job_77777777_1794160001_sans_rapport", "running", 77)])
    r = _appel(wt, db, lambda *a: False, emis)
    assert r["action"] == "ignore" and r["motif"] == "tache_en_vol", r
    assert not emis and _non_committe(wt)


def _sauvegarde(tmp_path, monkeypatch, statut, vivant):
    depot = tmp_path / "depot"
    sauv = depot / "sandbox" / "sauvegardes_executeurs" / AGENT / TID
    sauv.mkdir(parents=True)
    (sauv / "a.py").write_text("A = 1\n", encoding="utf-8")
    (sauv / "manifeste.json").write_text(json.dumps({"tache": TID, "agent": AGENT, "fichiers": ["a.py"]}),
                                         encoding="utf-8")
    db = _base(tmp_path, [(TID, statut, 4242)])
    monkeypatch.setattr(W, "interrupteur_reconciliateur_actif", lambda root: True)
    monkeypatch.setattr(W, "garde_ressources_au_rouge", lambda: False)
    emis = []
    W.balayer_et_reconcilier(root=depot, wt_root=tmp_path / "wt_vide", tasks_db=db, registre=set(),
                             notifier=lambda *a: None, vivacite=lambda *a: vivant,
                             emettre=lambda t, p: emis.append((t, p)))
    return sauv, db, emis


def test_sauvegarde_zero_commit_clot_la_tache_a_mort_prouvee(tmp_path, monkeypatch):
    sauv, db, emis = _sauvegarde(tmp_path, monkeypatch, "running", False)
    ligne = _ligne(db)
    assert ligne["status"] == "failed" and ligne["cause_echec"] == "SESSION_PERDUE", ligne
    assert "sauvegardes_executeurs" in ligne["result"]
    assert len(emis) == 1 and "sauvegardes_executeurs" in emis[0][1]["pointer_ref"], emis
    assert (sauv / "manifeste.json").is_file() and (sauv / "a.py").is_file(), "rien n'est supprime"


def test_sauvegarde_session_vivante_tache_intacte(tmp_path, monkeypatch):
    _sauv, db, emis = _sauvegarde(tmp_path, monkeypatch, "running", True)
    assert _ligne(db)["status"] == "running" and not emis

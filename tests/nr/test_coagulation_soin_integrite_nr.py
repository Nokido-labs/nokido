"""NR 7/11 : le corps VERIFIE et SOIGNE ses signaux d'integrite de livraison ; l'owner ne recoit que les decisions.

Consigne owner du 7/11 : « si le corps recoit des signaux il doit savoir les traiter de facon autonome », « a part les
relayer je ne peux pas en faire grand chose ». Mesure (job_e0f6498bb5d5) : 52 constats non acquittes dans
`delivery_integrity_findings`, le plus ancien en juillet, aucun consommateur n'appelle `ack` ; `_triage` envoyait tout
`high` non classe en `escalate`, donc chez l'owner.

Prouve, par le chemin reel (`_triage`, `coagulate`, `run_remediation_cycle`) et sur bases JETABLES :
1. une voie `soin` pour ces signaux, apres securite et service (inchanges) ; `commits_non_pousses` est un etat ;
2. le soin re-mesure le fait present et n'acquitte que le resolu ou le contredit, et SEULEMENT arme ;
   illisible = pas d'acquittement ; rien n'est supprime ;
3. un suspect confirme -> UNE tache de reverification, dedupliquee, plafonnee par jour, jamais vers une surface payante ;
4. vers l'owner : une ligne, la decision et le resultat du soin ; rien pour ce que le corps soigne ;
5. inhibiteur : le soin n'emet aucun signal, et un signal signe par la remediation ne relance pas le soin.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_coagulation as C  # noqa: E402
from nokido_agent.app import forge_delivery_integrity as D  # noqa: E402
from nokido_agent.app import forge_remediation as R  # noqa: E402

VIEUX = "2026-10-01T00:00:00+00:00"
SHA40 = "1234567890abcdef1234567890abcdef12345678"
EFFET = "[effet observe] commits produits : %s (aaaa111..bbbb222) ; fichiers non commites : 0"
OK = '{"intent":"OK_DONE","pointer_ref":"commit:%s"}'


def _ev(constat: str, cible: str = "x", sev: str = "high", **extra) -> dict:
    payload = {"detail": "%s:%s detail" % (constat, cible), "tick": 3, "vsm_action": "reevaluer_perimetre_police"}
    payload.update(extra)
    return {"id": 1, "kind": "algedonic:delivery_integrity", "severity": sev, "payload": payload}


def _id(kind, target):
    return hashlib.md5((kind + target).encode()).hexdigest()[:16]


@pytest.fixture
def corps(tmp_path, monkeypatch):
    """Bases jetables + git/gh simules + depot de tache et signaux enregistres. Rien ne touche la base vivante."""
    tasks = tmp_path / "tasks.db"
    con = sqlite3.connect(tasks)
    con.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, created_at TEXT, status TEXT, "
                "description TEXT, result TEXT)")
    lignes = [
        # contredite : sha dans la consigne + 1 commit observe
        ("job_contredit", "done", "CI de reference 50221f9ca", (EFFET % 1) + " | ok\n" + OK % "50221f9ca"),
        # suspect confirme : sha dans la consigne, 0 commit observe (forme job_af6dbf75)
        ("job_suspect", "done", "reprendre 50221f9ca", (EFFET % 0) + " | ok\n" + OK % "50221f9ca"),
        # non conclu : sha hors consigne, marqueur absent
        ("job_muet", "done", "consigne", "ok\n" + OK % "ddddddd4"),
    ]
    for tid, st, desc, res in lignes:
        con.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?)", (tid, "AGY", "2026-10-24T10:54:45", st, desc, res))
    con.commit()
    con.close()
    constats = tmp_path / "constats.db"
    c = sqlite3.connect(constats)
    D._ensure_schema(c)
    for kind, target in (("attestation_commit_anterieur", "job_contredit:50221f9ca"),
                         ("attestation_commit_anterieur", "job_suspect:50221f9ca"),
                         ("attestation_commit_anterieur", "job_muet:ddddddd4"),
                         ("travail_non_commite", "3 fichier(s)"),
                         ("file_non_drainee", "AGY:pending"),
                         ("submodule_non_bumpe", "Nokido"),
                         ("ci_en_echec", "CI"),
                         ("commits_non_pousses", "main->origin/main")):
        c.execute("INSERT INTO delivery_integrity_findings (id, kind, target, severity, detail, created_at) "
                  "VALUES (?,?,?,?,?,?)", (_id(kind, target), kind, target, "high", "d", "2026-07-01T00:00:00+00:00"))
    c.commit()
    c.close()

    def faux_git(repo, *args):
        if args[0] == "show":
            return VIEUX
        if args[0] == "diff":
            return ""                                    # plus aucun fichier sale
        if args[0] == "ls-tree":
            return "160000 commit %s\tNokido" % SHA40
        if args[0] == "rev-parse":
            return "main" if "--abbrev-ref" in args else SHA40   # submodule rattrape
        return None

    monkeypatch.setattr(D, "TASKS_DB", tasks)
    monkeypatch.setattr(D, "DB", constats)
    monkeypatch.setattr(D, "_git", faux_git)
    monkeypatch.setattr(D, "_gh", lambda *a, **k: None)   # CI illisible : jamais acquittee
    depots, signaux = [], []
    monkeypatch.setattr(R, "_deposer_reverif",
                        lambda description, agent: depots.append((agent, description)) or {"task_id": "t%d" % len(depots)})
    monkeypatch.setattr(R, "_REVERIF_ETAT", tmp_path / "reverif.json")
    import nokido_agent.app.forge_critical_events as CE
    import nokido_agent.app.forge_heartbeat as HB
    monkeypatch.setattr(CE, "persist", lambda kind, sev, payload: signaux.append((kind, payload)) or 1)
    monkeypatch.setattr(HB, "beat_daemon", lambda *a, **k: None)
    return {"constats": constats, "depots": depots, "signaux": signaux, "tmp": tmp_path}


def _acquittes(db):
    c = sqlite3.connect(db)
    try:
        return {(k, t): m for k, t, m in c.execute(
            "SELECT kind, target, ack_motif FROM delivery_integrity_findings WHERE acked_at IS NOT NULL")}
    finally:
        c.close()


def _n_lignes(db):
    c = sqlite3.connect(db)
    try:
        return c.execute("SELECT COUNT(*) FROM delivery_integrity_findings").fetchone()[0]
    finally:
        c.close()


# ── 1. Tri ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("constat", ["attestation_commit_anterieur", "travail_non_commite", "file_non_drainee",
                                     "submodule_non_bumpe", "ci_en_echec"])
def test_les_signaux_d_integrite_vont_au_soin(constat):
    assert C._triage(_ev(constat))[0] == "soin"


def test_commits_non_pousses_est_un_etat_pas_une_alerte():
    voie, raison = C._triage(_ev("commits_non_pousses", "main->origin/main"))
    assert voie == "ack" and "etat" in raison.lower()


def test_securite_et_service_restent_tries_avant_le_soin():
    assert C._triage(_ev("ci_en_echec", "gitleaks", fuite="secret exfil"))[0] == "escalate"
    ev = _ev("ci_en_echec")
    ev["kind"] = "algedonic:delivery_integrity service_down"
    assert C._triage(ev)[0] == "escalate"


# ── 2. Soin ───────────────────────────────────────────────────────────────────
def test_soin_desarme_n_acquitte_rien_et_dit_ce_qu_il_ferait(corps):
    r = R.run_remediation_cycle(armed=False, lesions=["algedonic:delivery_integrity"])
    soin = r["debts"]["delivery_integrity"]
    assert _acquittes(corps["constats"]) == {}
    assert corps["depots"] == []
    assert "attestation_commit_anterieur:job_contredit:50221f9ca" in soin["a_acquitter"]
    assert "NON ARME" in soin["resume"]


def test_soin_arme_acquitte_le_resolu_et_garde_le_reste(corps):
    r = R.run_remediation_cycle(armed=True, lesions=["algedonic:delivery_integrity"])
    soin = r["debts"]["delivery_integrity"]
    acq = _acquittes(corps["constats"])
    assert set(acq) == {("attestation_commit_anterieur", "job_contredit:50221f9ca"),
                        ("travail_non_commite", "3 fichier(s)"),
                        ("file_non_drainee", "AGY:pending"),
                        ("submodule_non_bumpe", "Nokido")}, acq
    assert all(m for m in acq.values()), "un acquittement sans motif"
    assert _n_lignes(corps["constats"]) == 8, "le soin ne supprime rien"
    assert "ci_en_echec:CI" in soin["inconnus"]                       # illisible : pas d'acquittement
    assert "attestation_commit_anterieur:job_muet:ddddddd4" in soin["persistants"]   # non conclu : garde
    assert soin["suspects"] == ["attestation_commit_anterieur:job_suspect:50221f9ca"]


# ── 3. Suspect confirme : une tache, dedupliquee, plafonnee, gratuite ────────
def test_suspect_confirme_une_seule_tache_de_reverification(corps):
    R.run_remediation_cycle(armed=True, lesions=["delivery_integrity"])
    R.run_remediation_cycle(armed=True, lesions=["delivery_integrity"])
    assert len(corps["depots"]) == 1, corps["depots"]
    agent, desc = corps["depots"][0]
    assert agent not in R._SURFACES_PAYANTES
    assert "job_suspect" in desc and "50221f9ca" in desc


def test_tache_de_reverification_plafonnee_par_jour(corps, monkeypatch):
    monkeypatch.setattr(R, "REVERIF_MAX_JOUR", 0)
    soin = R.run_remediation_cycle(armed=True, lesions=["delivery_integrity"])["debts"]["delivery_integrity"]
    assert corps["depots"] == []
    assert any(t.get("statut") == "PLAFOND_JOUR" for t in soin["taches"]), soin["taches"]


def test_surface_payante_exclue_par_defaut(corps, monkeypatch):
    monkeypatch.setenv("LAFORGE_INTEGRITE_REVERIF_AGENT", "CLAUDE_HEADLESS")
    monkeypatch.delenv("LAFORGE_INTEGRITE_REVERIF_PAYANT", raising=False)
    R.run_remediation_cycle(armed=True, lesions=["delivery_integrity"])
    assert corps["depots"] and corps["depots"][0][0] != "CLAUDE_HEADLESS"


# ── 4 & 5. Chemin reel de la coagulation, decision owner, inhibiteur ─────────
def _brancher(monkeypatch, tmp_path, evs):
    import nokido_agent.app.forge_critical_events as CE
    import nokido_agent.app.forge_endocrine as EN
    import nokido_agent.app.forge_opsec as OP

    lots = {"n": 0}

    def unprocessed(limit):
        lots["n"] += 1
        return evs if lots["n"] == 1 else []

    alertes = []
    monkeypatch.setattr(CE, "unprocessed", unprocessed)
    monkeypatch.setattr(CE, "mark_processed", lambda ids: len(ids))
    monkeypatch.setattr(CE, "purge_older_than", lambda j: 0)
    monkeypatch.setattr(CE, "alerter_owner", lambda sujet, grav, detail, emetteur="?": alertes.append(detail) or "emise")
    monkeypatch.setattr(EN, "release", lambda *a, **k: None)
    monkeypatch.setattr(OP, "is_human_locked", lambda: False)
    monkeypatch.setattr(C, "_log", lambda *a, **k: None)
    monkeypatch.setattr(C, "_REFRACTAIRE", tmp_path / "refractaire.json", raising=False)
    return alertes


def test_coagulation_soigne_et_ne_remonte_que_la_decision(corps, monkeypatch):
    evs = [dict(_ev("attestation_commit_anterieur", "job_suspect:50221f9ca"), id=1),
           dict(_ev("ci_en_echec", "CI"), id=2),
           dict(_ev("commits_non_pousses", "main->origin/main"), id=3),
           dict(_ev("submodule_illisible", ".gitmodules"), id=4)]
    alertes = _brancher(monkeypatch, corps["tmp"], evs)
    t = C.coagulate(armed=True)
    assert t["soin"] == 3 and t["consumed"] == 4, t
    assert len(alertes) == 1, alertes
    ligne = alertes[0]
    assert "\n" not in ligne and "decision" in ligne.lower() and "soin" in ligne.lower(), ligne
    assert ("attestation_commit_anterieur", "job_contredit:50221f9ca") in _acquittes(corps["constats"])
    assert len(corps["depots"]) == 1


def test_le_produit_du_soin_ne_reemet_aucun_signal(corps, monkeypatch):
    alertes = _brancher(monkeypatch, corps["tmp"], [dict(_ev("travail_non_commite", "3 fichier(s)"), id=1)])
    C.coagulate(armed=True)
    assert corps["signaux"] == [], "le soin a emis un signal : il relancerait la coagulation"
    assert alertes == []
    signe = _ev("travail_non_commite", "3 fichier(s)", origine="forge_remediation")
    assert C._triage(signe)[0] == "ack"


def test_le_balayage_complet_ne_relance_pas_le_soin_d_integrite(monkeypatch):
    # forge_autonomous_loops.pat_remediation balaie tout (lesions=None) a chaque tick : le soin d'integrite (git, gh,
    # 60 constats) n'y a pas sa place, il ne tourne que sur un signal qui le demande.
    appels = []

    def check_delivery_integrity(armed):
        appels.append(armed)
        return {}

    monkeypatch.setattr(R, "CHECKS", [check_delivery_integrity])
    monkeypatch.setattr("nokido_agent.app.forge_heartbeat.beat_daemon", lambda *a, **k: None)
    R.run_remediation_cycle(armed=False)
    R.run_remediation_cycle(armed=False, lesions=["lesion_inconnue"])
    assert appels == []
    R.run_remediation_cycle(armed=False, lesions=["algedonic:delivery_integrity"])
    assert appels == [False]


# ── Garde-fous : requete ciblee, CI sans coffre ──────────────────────────────
def test_la_requete_des_constats_ne_touche_que_sa_table(tmp_path):
    db = tmp_path / "partagee.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE rag_chunks (id INTEGER PRIMARY KEY, txt TEXT)")
    D._ensure_schema(c)
    plan = c.execute("EXPLAIN QUERY PLAN " + D._SQL_OUVERTS, (10,)).fetchall()
    c.close()
    textes = " ".join(str(r[-1]) for r in plan)
    assert "delivery_integrity_findings" in textes and "rag_chunks" not in textes, plan


def test_le_soin_ci_ne_lit_pas_le_coffre(monkeypatch):
    def coffre(*a, **k):
        raise AssertionError("lecture du coffre par le soin")

    vus = []

    def faux_run(cmd, **k):
        vus.append(cmd)
        return subprocess.CompletedProcess(cmd, 4, "", "not logged in")

    monkeypatch.setattr(D, "_gh_env", coffre)
    monkeypatch.setattr(D, "_git", lambda *a, **k: "main")
    monkeypatch.setattr(D.subprocess, "run", faux_run)
    r = D.remesurer("ci_en_echec", "CI")
    assert r["etat"] == "INCONNU", r
    assert vus and vus[0][:3] == ["gh", "run", "list"], vus
    assert json.dumps(r)  # rendu serialisable


# ── 6. CI rouge persistante : une tache d'ANALYSE, dedupliquee par workflow+commit, jamais un relancement ─────
_RUNS_ROUGES = json.dumps([{"name": "CI", "status": "completed", "conclusion": "failure", "headSha": "abc1234def5678"}])


def test_ci_rouge_persistante_cree_une_tache_d_analyse_dedupliquee(corps, monkeypatch):
    monkeypatch.setattr(D, "_gh", lambda *a, **k: _RUNS_ROUGES)
    R.run_remediation_cycle(armed=True, lesions=["delivery_integrity"])
    R.run_remediation_cycle(armed=True, lesions=["delivery_integrity"])
    ci = [d for d in corps["depots"] if "abc1234" in d[1]]
    assert len(ci) == 1, corps["depots"]
    desc = ci[0][1].lower()
    assert "analyse" in desc and "ne relance" in desc, desc
    assert "ci_en_echec:CI" not in _acquittes(corps["constats"])   # persiste : jamais acquitte


def test_ci_rouge_nouveau_commit_nouvelle_tache(corps, monkeypatch):
    monkeypatch.setattr(D, "_gh", lambda *a, **k: _RUNS_ROUGES)
    R.run_remediation_cycle(armed=True, lesions=["delivery_integrity"])
    autre = json.dumps([{"name": "CI", "status": "completed", "conclusion": "failure", "headSha": "fff9999aaa0000"}])
    monkeypatch.setattr(D, "_gh", lambda *a, **k: autre)
    R.run_remediation_cycle(armed=True, lesions=["delivery_integrity"])
    assert len([d for d in corps["depots"] if "fff9999" in d[1]]) == 1, corps["depots"]
    assert len([d for d in corps["depots"] if "abc1234" in d[1]]) == 1, corps["depots"]


def test_statut_gh_illisible_ni_acquittement_ni_tache_ci(corps, monkeypatch):
    monkeypatch.setattr(D, "_gh", lambda *a, **k: None)
    soin = R.run_remediation_cycle(armed=True, lesions=["delivery_integrity"])["debts"]["delivery_integrity"]
    assert "ci_en_echec:CI" in soin["inconnus"]
    assert ("ci_en_echec", "CI") not in _acquittes(corps["constats"])
    assert not [d for d in corps["depots"] if "CI" in d[1] and "analyse" in d[1].lower()], corps["depots"]


def test_ci_rouge_sans_sha_lisible_ne_cree_rien(corps, monkeypatch):
    sans_sha = json.dumps([{"name": "CI", "status": "completed", "conclusion": "failure"}])
    monkeypatch.setattr(D, "_gh", lambda *a, **k: sans_sha)
    R.run_remediation_cycle(armed=True, lesions=["delivery_integrity"])
    assert not [d for d in corps["depots"] if "analyse" in d[1].lower()], corps["depots"]

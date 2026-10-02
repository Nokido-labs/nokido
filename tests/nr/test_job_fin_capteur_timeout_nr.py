"""NR -- dette D : chaque fiche de job dit SI un delai l'a coupee, et POURQUOI elle a fini.

bb:dette_D_sans_capteur_2026-09-20 : sur 1705 fiches, aucune ne portait `timed_out` ; un job
tue par un delai ne se distinguait pas d'un job rouge. Par le CHEMIN REEL : `launch_job`
genere le vrai wrapper, qui tourne ici en sous-process (le lanceur sandbox Windows est
remplace par un Popen), puis `read_job` lit la fin. Trois etats, jamais deux :
  delai depasse -> VRAI ; fin normale -> FAUX ; fin illisible ou fiche tronquee -> INCONNU.
Observation seule : le sort des jobs ne change pas.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

from nokido_agent.app import forge_job_runner as fjr
from nokido_agent.app import forge_process_identity as fpi
from nokido_agent.app import forge_sandbox_exec as fse

pytestmark = pytest.mark.timeout(120)


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    d = tmp_path / "jobs"
    monkeypatch.setattr(fjr, "JOBS_DIR", d)
    monkeypatch.setattr(fjr, "_root", lambda: tmp_path)
    # Hermetique : l'identite de run et le registre des pid du lanceur ecrivent sous
    # sandbox/ reel -- on les garde dans le tmp.
    monkeypatch.setattr(fpi, "get_hub_run_id", lambda: "nr-run")
    monkeypatch.setattr(fpi, "record", lambda *a, **k: None)
    procs = []

    def _spawn(cmd, log, err, online=False):
        p = subprocess.Popen(shlex.split(cmd), stdout=open(log, "w"), stderr=open(err, "w"))
        procs.append(p)
        return {"ok": True, "pid": p.pid}
    monkeypatch.setattr(fse, "spawn_as_sandbox_detached", _spawn)
    yield tmp_path
    for p in procs:
        if p.poll() is None:
            p.kill()


def _lancer(tmp, corps: str, **kw) -> str:
    script = tmp / ("job_%d.py" % int(time.time() * 1e6))
    script.write_text(corps, encoding="utf-8")
    r = fjr.launch_job(str(script), **kw)
    assert r["ok"], r
    return r["job_id"]


def _attendre(job_id, delai=60):
    fin = time.time() + delai
    while time.time() < fin:
        r = fjr.read_job(job_id)
        if r["status"] != "running":
            return r
        time.sleep(0.2)
    pytest.fail("le job %s n'a pas fini" % job_id)


# ── par le chemin reel ────────────────────────────────────────────────────────────────
def test_job_coupe_par_un_delai_est_vrai(jobs):
    jid = _lancer(jobs, "import subprocess, sys\n"
                        "subprocess.run([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=0.5)\n")
    r = _attendre(jid)
    assert r["timed_out"] == fjr.VRAI and r["fin"]["cause"] == "DELAI", r["fin"]
    fiche = json.loads((fjr.JOBS_DIR / f"{jid}.json").read_text(encoding="utf-8"))
    assert fiche["timed_out"] == fjr.VRAI                     # la FICHE le porte, pas la memoire


def test_fin_normale_est_faux(jobs):
    r = _attendre(_lancer(jobs, "print('ok')\n"))
    assert r["rc"] == 0 and r["timed_out"] == fjr.FAUX and r["fin"]["cause"] == "NORMALE"
    assert json.loads((fjr.JOBS_DIR / f"{r['job_id']}.fin").read_text())["cause"] == "SORTIE"


def test_job_rouge_sans_delai_est_faux_et_dit_son_rc(jobs):
    r = _attendre(_lancer(jobs, "raise SystemExit(3)\n"))
    assert r["timed_out"] == fjr.FAUX and r["fin"]["cause"] == "ERREUR" and r["fin"]["rc"] == 3


def test_plafond_rss_est_une_cause_nommee(jobs):
    pytest.importorskip("psutil")
    jid = _lancer(jobs, "import time\nx = bytearray(64 * 1024 * 1024)\ntime.sleep(30)\n",
                  rss_cap_mb=8)
    r = _attendre(jid)
    assert r["rc"] == 137 and r["timed_out"] == fjr.FAUX and r["fin"]["cause"] == "PLAFOND_RSS"


# ── fins illisibles : INCONNU, jamais FAUX ────────────────────────────────────────────
def _fiche(d: Path, jid: str, rc=None, err=None, log=None, **rec):
    d.mkdir(parents=True, exist_ok=True)
    base = {"job_id": jid, "script": str(d / "bloc_pur.py"), "log": str(d / f"{jid}.log"),
            "rc_file": str(d / f"{jid}.rc"), "started": rec.pop("started", "2026-10-02T10:00:00"),
            "status": rec.pop("status", "done")}
    base.update(rec)
    (d / f"{jid}.json").write_text(json.dumps(base), encoding="utf-8")
    if rc is not None:
        (d / f"{jid}.rc").write_text(str(rc), encoding="utf-8")
    if err is not None:
        (d / f"{jid}.err").write_text(err, encoding="utf-8")
    if log is not None:
        (d / f"{jid}.log").write_text(log, encoding="utf-8")
    return base


def test_fiche_tronquee_est_inconnue(jobs):
    d = fjr.JOBS_DIR
    d.mkdir(parents=True)
    (d / "job_tronque.json").write_text('{"job_id": "job_tron', encoding="utf-8")
    assert fjr.qualifier_fin(None)["timed_out"] == fjr.INCONNU
    r = fjr.annoter_fiches(apply=True)
    assert r["illisibles"] == 1 and r["annotees"] == 0
    assert fjr.compteur_timeouts()["fiches_illisibles"] == 1


def test_rc_tronque_ou_journaux_absents_sont_inconnus(jobs):
    d = fjr.JOBS_DIR
    _fiche(d, "job_rcvide", rc="")
    _fiche(d, "job_muet", rc=1)                                # ni .err ni .log
    assert fjr.qualifier_fin(json.loads((d / "job_rcvide.json").read_text()))["cause"] == "RC_ILLISIBLE"
    m = fjr.qualifier_fin(json.loads((d / "job_muet.json").read_text()))
    assert m["timed_out"] == fjr.INCONNU and m["cause"] == "JOURNAL_ILLISIBLE"


def test_arret_externe_et_signal_sont_inconnus(jobs):
    d = fjr.JOBS_DIR
    k = _fiche(d, "job_tue", rc=137, err="", status="killed")
    s = _fiche(d, "job_sig", rc=-15, err="rien\n")
    assert fjr.qualifier_fin(k)["cause"] == "ARRET_EXTERNE" and fjr.qualifier_fin(k)["timed_out"] == fjr.INCONNU
    assert fjr.qualifier_fin(s)["cause"] == "SIGNAL" and fjr.qualifier_fin(s)["timed_out"] == fjr.INCONNU


def test_bandeau_pytest_timeout_est_un_delai(jobs):
    d = fjr.JOBS_DIR
    f = _fiche(d, "job_bloc", rc=1, err="", log="+" * 30 + " Timeout " + "+" * 30 + "\n")
    assert fjr.qualifier_fin(f)["timed_out"] == fjr.VRAI


# ── compteur sur FENETRE ──────────────────────────────────────────────────────────────
def test_compteur_fenetre_par_script_ignore_le_vieux(jobs):
    d = fjr.JOBS_DIR
    # 5 vieux timeouts, puis 3 fins propres recentes : la fenetre de 3 ne voit que le present
    for i in range(5):
        _fiche(d, "job_vieux%d" % i, rc=1, log="+++ Timeout +++\n", started="2026-09-0%dT00:00:00" % (i + 1))
    for i in range(3):
        _fiche(d, "job_neuf%d" % i, rc=0, started="2026-10-02T0%d:00:00" % i)
    c = fjr.compteur_timeouts(n=3)["scripts"]["bloc_pur"]
    assert c["jobs"] == 3 and c["VRAI"] == 0 and c["FAUX"] == 3 and c["taux"] == 0.0
    large = fjr.compteur_timeouts(n=8)["scripts"]["bloc_pur"]
    assert large["VRAI"] == 5 and large["taux"] == round(5 / 8, 3)


def test_compteur_inconnus_hors_taux_et_cli(jobs, capsys):
    d = fjr.JOBS_DIR
    _fiche(d, "job_a", rc=1)                       # journal illisible -> INCONNU
    _fiche(d, "job_b", rc=0)
    c = fjr.compteur_timeouts(n=10)["scripts"]["bloc_pur"]
    assert c["INCONNU"] == 1 and c["FAUX"] == 1 and c["taux"] == 0.0
    assert fjr._main(["--timeouts", "--n", "10", "--script", "bloc_pur"]) == 0
    assert json.loads(capsys.readouterr().out)["scripts"]["bloc_pur"]["jobs"] == 2


def test_annotation_a_blanc_n_ecrit_rien(jobs):
    d = fjr.JOBS_DIR
    _fiche(d, "job_x", rc=0)
    avant = (d / "job_x.json").read_text()
    assert fjr.annoter_fiches(apply=False)["annotees"] == 1
    assert (d / "job_x.json").read_text() == avant
    fjr.annoter_fiches(apply=True)
    assert json.loads((d / "job_x.json").read_text())["timed_out"] == fjr.FAUX


def test_le_garde_ecrit_la_cause_avant_le_signal_de_fin():
    """Ordre SANS COURSE (2026-10-02, CI de reference f340e9ca4) : _tue, puis .fin et motif, puis
    .rc (le signal de fin), puis le kill. Avec l'ancien ordre (kill, .rc, puis .fin), read_job
    lisait « 137 sans motif » sous charge et figeait INCONNU ; et le thread principal, reveille
    par la mort du process avant `_tue = True`, pouvait ecrire SON rc. Le .fin ne remplace
    toujours pas le .rc : il le precede."""
    src = Path(fjr.__file__).read_text(encoding="utf-8")
    for cause in ("PLAFOND_LOG", "PLAFOND_RSS"):
        i_fin = src.find("_noter_fin('%s', 137)" % cause)
        assert i_fin > 0, cause
        i_tue = src.rfind("_tue = True", 0, i_fin)
        i_rc = src.find("open(_rc, 'w').write('137')", i_fin)
        i_kill = src.find("_p.kill()", i_fin)
        assert 0 < i_tue < i_fin < i_rc < i_kill, (cause, i_tue, i_fin, i_rc, i_kill)
    i_sortie = src.find("_noter_fin('SORTIE', rc)")
    assert 0 < i_sortie < src.find("open(_rc, 'w').write(str(rc))", i_sortie)
    assert sys.executable  # le wrapper reste lance par l'interpreteur courant

"""NR — ce que /admin/run_job DOIT transmettre au runner, prouve par COMPORTEMENT.

MAILLON 1 du CAP LONG V8. Le NR voisin `test_admin_run_job_observable_nr`
verifie le TEXTE de la route (« launch_job est-il cite ? »). Le mandat exige
davantage : « Le NR doit verifier le comportement observable, pas seulement la
presence d'un appel a launch_job. » Celui-ci exerce donc le runner REELLEMENT,
sans lancer le moindre process.

MESURE ROUGE QUI MOTIVE LE MAILLON (2026-09-21)
==============================================
`tools/nokido_hub.py::admin_run_job` fabrique un wrapper de 266 octets :

    import subprocess
    rc = subprocess.run([py, script]).returncode
    open(rc_file, 'w').write(str(rc))

`forge_job_runner.launch_job` porte NEUF gardes que ce wrapper n'a pas, et
chacun est ne d'un incident date, ecrit dans le module lui-meme :

    cap LOG 200 Mo      28/07 : 3 jobs x 70 Go = 211 Go, disque plein, hub mort
    cap RSS 6 Go        02/08 : 15 Go par URL x12, famine RAM, bureau fige
    kill de l'ARBRE     13/09 : pytest 8,6 Go survit au kill du wrapper (50 Mo)
    .rc toujours ecrit  05/09 : garde mort avant le .rc -> running a vie
    137 non ecrase      un kill de regulation reste distinct d'une erreur appli
    script_args         20/08 : --once perdu -> one-shot devenu daemon infini
    lane + release      sinon bail orphelin 2 h (saturation du 30/08)
    identite process    hub_run_id / service_id au registre superviseur
    LAFORGE_JOB_ID      progression jointe par read_job

Et le repertoire : `JOBS_DIR` a ete deplace vers `sandbox/jobs` EXACTEMENT
pour fuir `C:/tmp/nokido_jobs`, « la zone d'explosion » -- or la route y ecrit
toujours.

CE NR NE LANCE AUCUN PROCESS : `spawn_as_sandbox_detached` est substitue. Ce
qu'on mesure, c'est ce que le runner PREPARE -- wrapper, record, environnement.
"""
import importlib
import json

import pytest

RUNNER = "nokido_agent.app.forge_job_runner"


@pytest.fixture()
def runner(tmp_path, monkeypatch):
    """Runner isole : jobs dans tmp_path, racine dans tmp_path, spawn neutralise."""
    mod = importlib.import_module(RUNNER)
    jobs = tmp_path / "jobs"
    monkeypatch.setattr(mod, "JOBS_DIR", jobs)
    monkeypatch.setattr(mod, "_root", lambda: tmp_path)

    vus = {}

    def faux_spawn(cmd, log, err, online=False):
        vus["cmd"] = cmd
        vus["online"] = online
        return {"pid": 4242}

    import nokido_agent.app.forge_sandbox_exec as sx
    monkeypatch.setattr(sx, "spawn_as_sandbox_detached", faux_spawn)
    mod._vus = vus
    return mod


@pytest.fixture()
def script(tmp_path):
    p = tmp_path / "cible_de_test.py"
    p.write_text("print('cible')\n", encoding="utf-8")
    return p


def _record(mod, res):
    return json.loads((mod.JOBS_DIR / (res["job_id"] + ".json")).read_text(encoding="utf-8"))


def _wrapper(mod, res):
    return (mod.JOBS_DIR / (res["job_id"] + "_wrap.py")).read_text(encoding="utf-8")


# --------------------------------------------------- ce que le runner PREPARE

def test_la_lane_demandee_arrive_dans_le_record(runner, script):
    """Une lane qui n'arrive pas au record n'est jamais relachee : bail orphelin
    de 2 h, puis saturation -- l'incident du 2026-08-30."""
    res = runner.launch_job(str(script), lane="ci")
    assert res["ok"], res
    assert _record(runner, res)["lane"] == "ci"


def test_les_arguments_arrivent_a_la_cible(runner, script):
    """MESURE 2026-08-20 : sans script_args, un `--once` etait silencieusement
    perdu et un drain one-shot repartait en daemon infini. Un job detache qui ne
    peut pas recevoir de mode ne peut pas non plus s'arreter."""
    res = runner.launch_job(str(script), script_args="--once --limite 3")
    corps = _wrapper(runner, res)
    assert "--once" in corps
    assert "--limite" in corps


def test_les_deux_gardes_sont_dans_le_wrapper(runner, script):
    """Le wrapper de 266 o de la route n'a ni l'un ni l'autre."""
    corps = _wrapper(runner, runner.launch_job(str(script)))
    assert "LOG_CAP" in corps, "sans cap de log : 211 Go et disque plein (28/07)"
    assert "RSS_CAP" in corps, "sans cap RSS : famine RAM et bureau fige (02/08)"


def test_le_garde_tue_l_arbre_pas_seulement_le_parent(runner, script):
    """13/09 : le pytest de 8,6 Go a SURVECU au kill de son wrapper de 50 Mo."""
    corps = _wrapper(runner, runner.launch_job(str(script)))
    assert "children(recursive=True)" in corps


def test_le_job_porte_son_identite_dans_l_environnement(runner, script):
    """Sans LAFORGE_JOB_ID, la progression emise par la cible n'est rattachable
    a rien : PRODUCED resterait INOBSERVABLE."""
    res = runner.launch_job(str(script))
    corps = _wrapper(runner, res)
    assert "LAFORGE_JOB_ID" in corps
    assert res["job_id"] in corps


def test_rien_n_est_ecrit_dans_la_zone_d_explosion(runner, script):
    """`JOBS_DIR` a ete deplace vers sandbox/jobs POUR fuir C:/tmp/nokido_jobs.
    Un chemin code en dur y ramenerait en silence."""
    res = runner.launch_job(str(script))
    for suffixe in (".json", "_wrap.py"):
        chemin = runner.JOBS_DIR / (res["job_id"] + suffixe)
        assert chemin.exists()
        assert "nokido_jobs" not in str(chemin)


def test_online_est_transmis_au_spawn(runner, script):
    runner.launch_job(str(script), online=True)
    assert runner._vus["online"] is True


# ------------------------------------------- ACCEPTED n'est pas PRODUCED

def test_le_lancement_ne_prouve_que_l_acceptation(runner, script):
    """Invariant du mandat : ACCEPTED != SPAWNED != RUNNING != PRODUCED.

    `launch_job` rend ok=True des que le spawn a repondu. Ce n'est PAS une
    preuve de production : aucun .rc n'existe encore, et le statut inscrit est
    une INTENTION, pas une observation.
    """
    res = runner.launch_job(str(script))
    assert res["ok"] is True
    rec = _record(runner, res)
    assert rec["status"] == "running"
    assert not (runner.JOBS_DIR / (res["job_id"] + ".rc")).exists(), (
        "aucun .rc ne doit exister au moment du spawn : sinon on confondrait "
        "l'acceptation avec la production"
    )


def test_un_script_hors_perimetre_est_refuse(runner, tmp_path):
    """Test negatif : le runner refuse ce qui n'est ni sous C:/tmp ni sous la
    racine, et il le DIT."""
    res = runner.launch_job(r"D:\ailleurs\pas_permis.py")
    assert res["ok"] is False
    assert "under" in res["error"] or "script" in res["error"]


def test_un_script_args_illisible_est_refuse_et_nomme(runner, script):
    res = runner.launch_job(str(script), script_args='--x "guillemet jamais ferme')
    assert res["ok"] is False
    assert "script_args" in res["error"]


# ------------------------------------------- la route doit passer par LUI

def test_la_route_traduit_le_corps_en_parametres_du_runner():
    """Le raccord testable : la traduction corps HTTP -> arguments du runner
    doit vivre dans l'organe du job, appelable sans demarrer le hub.

    Sans elle, chaque appelant re-lit le corps a sa facon et l'un d'eux oublie
    la lane -- ce qui est exactement l'etat mesure.
    """
    mod = importlib.import_module(RUNNER)
    assert hasattr(mod, "params_depuis_corps")
    p = mod.params_depuis_corps({
        "script": "tools/x.py", "online": True, "lane": "ci",
        "script_args": "--once", "rss_cap_mb": 1234,
    })
    assert p["script"] == "tools/x.py"
    assert p["online"] is True
    assert p["lane"] == "ci"
    assert p["script_args"] == "--once"
    assert p["rss_cap_mb"] == 1234


def test_un_corps_minimal_ne_perd_rien_et_n_invente_rien():
    mod = importlib.import_module(RUNNER)
    p = mod.params_depuis_corps({"script": "tools/x.py"})
    assert p["lane"] == ""
    assert p["online"] is False
    assert p["script_args"] == ""
    assert p["rss_cap_mb"] is None

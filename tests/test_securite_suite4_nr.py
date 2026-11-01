"""NR suite 4 : (A) aucun jeton de job sur disque, env de l'enfant, liaison job_id+pid ;
(B) l'observateur ne casse jamais get_secret ; (C) import reel du hub + Route /oauth/token ;
observer_appel cable sur les appels ring <= 3. Assertions booleennes : aucune valeur de jeton
n'est affichee (lancer avec --tb=no)."""
import importlib.util
import py_compile
import sys
from pathlib import Path
from urllib.parse import urlencode

import pytest

from app import forge_dpop as dp
from app import forge_job_runner as jr
from app import forge_oauth_route as orr
from app import forge_secrets as fs
from app import forge_token_exchange as tx

RACINE = Path(__file__).resolve().parent.parent
SECRET = b"k" * 32
URL = "http://testserver/oauth/token"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(orr, "_secret", lambda: SECRET)
    monkeypatch.delenv("NOKIDO_OAUTH_ENFORCE", raising=False)
    dp._jti_vus.clear()
    orr.OBSERVES.clear()
    if hasattr(orr, "LIES"):
        orr.LIES.clear()


# ---------------------------------------------------------------- (A)
def _lancer(monkeypatch, tmp_path):
    """launch_job reel, spawn simule : capture l'env passe a l'enfant."""
    vus = {}

    def faux_spawn(cmd, out, err, online=False, env_extra=None):
        vus["env"] = dict(env_extra or {})
        return {"ok": True, "pid": 4242, "sandbox_user": "x"}

    import app.forge_sandbox_exec as se
    monkeypatch.setattr(se, "spawn_as_sandbox_detached", faux_spawn)
    try:
        import nokido_agent.app.forge_sandbox_exec as se2
        monkeypatch.setattr(se2, "spawn_as_sandbox_detached", faux_spawn)
    except Exception:
        pass
    monkeypatch.setattr(jr, "JOBS_DIR", tmp_path / "jobs")
    script = RACINE / "tools" / "forge_secours_lanceur.py"
    res = jr.launch_job(str(script), jeton_factory=orr.emettre_pour_job)
    return res, vus


def test_A_aucun_fichier_subject_et_jeton_dans_env_enfant(monkeypatch, tmp_path):
    res, vus = _lancer(monkeypatch, tmp_path)
    assert res["ok"] is True
    jobs = tmp_path / "jobs"
    assert not list(jobs.glob("*.subject"))
    jeton = vus["env"].get("NOKIDO_JOB_SUBJECT_TOKEN", "")
    assert bool(jeton) and vus["env"].get("NOKIDO_JOB_ID") == res["job_id"]
    # le jeton n'est dans AUCUN fichier ecrit (wrapper, fiche, ...)
    assert not any(jeton in f.read_text(encoding="utf-8", errors="ignore")
                   for f in jobs.iterdir() if f.is_file())
    assert tx.lire_jeton(jeton, SECRET)["job_id"] == res["job_id"]


def test_A_hub_n_ecrit_plus_de_subject():
    src = (RACINE / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    assert '.subject"' not in src and ".subject'" not in src


def _post(sub, job, pid_appelant, cle=None):
    cle = cle or orr.cle_test()
    corps = urlencode({"grant_type": tx.GRANT_TYPE, "subject_token": sub,
                       "subject_token_type": tx.TYPE_JOB, "job_id": job,
                       "audience": "hub", "scope": "task:status"}).encode()
    return orr.traiter("application/x-www-form-urlencoded", corps,
                       dp.creer_preuve("POST", URL, cle=cle), URL, pid_appelant=pid_appelant)


def test_A_jeton_avec_autre_job_id_refuse():
    sub = orr.emettre_pour_job("job_a", ttl=600)
    statut, corps, _ = _post(sub, "job_b", None)
    assert statut == 400 and corps["error"] == "invalid_grant"


def test_A_liaison_pid():
    sub = orr.emettre_pour_job("job_a", ttl=600)
    orr.lier_pid("job_a", 4242)
    assert _post(sub, "job_a", 4242)[0] == 200
    assert _post(sub, "job_a", 999999)[0] == 400           # autre pid : refus
    st, corps, _ = _post(sub, "job_a", None)                # illisible : refus DIT
    assert st == 400 and bool(corps["error_description"])


# ---------------------------------------------------------------- (B)
def test_B_observateur_qui_leve_ne_casse_pas_get_secret(monkeypatch):
    monkeypatch.setenv("NR_SUITE4_CLE", "valeur-x")
    monkeypatch.delenv("NOKIDO_COFFRE_TEST_DIR", raising=False)
    avant = fs.get_secret("NR_SUITE4_CLE")

    def boom(_k):
        raise RuntimeError("valeur-x")

    monkeypatch.setattr(fs, "observer_lecture_cloisonnee", boom)
    assert (fs.get_secret("NR_SUITE4_CLE") == avant) is True


# ---------------------------------------------------------------- (C)
FICHIERS = ["app/forge_oauth_route.py", "app/forge_secrets.py", "tools/nokido_hub.py",
            "tools/forge_secours_lanceur.py", "app/forge_job_runner.py",
            "app/forge_sandbox_exec.py"]


@pytest.mark.parametrize("f", FICHIERS)
def test_C_py_compile(f, tmp_path):
    py_compile.compile(str(RACINE / f), cfile=str(tmp_path / "x.pyc"), doraise=True)


def _routes(obj, acc):
    for r in getattr(obj, "routes", []) or []:
        acc.append(r)
        _routes(r, acc)
    return acc


def test_C_import_hub_et_route_oauth_token_montee():
    spec = importlib.util.spec_from_file_location("nokido_hub_nr_suite4",
                                                  str(RACINE / "tools" / "nokido_hub.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nokido_hub_nr_suite4"] = mod
    try:
        spec.loader.exec_module(mod)
        assert "nokido_hub_nr_suite4" in sys.modules
        import asyncio
        app = asyncio.run(mod._build_app())          # construit l'application, ne sert rien
        routes = _routes(app, [])
        assert any(getattr(r, "path", "") == "/oauth/token"
                   and "POST" in (getattr(r, "methods", None) or ()) for r in routes) is True
        assert any(getattr(m, "cls", None) is orr.ObservationASGI
                   for m in app.user_middleware) is True
    finally:
        sys.modules.pop("nokido_hub_nr_suite4", None)


# ---------------------------------------------------------------- cablage observer_appel
def test_cablage_observer_appel_ring3_observation_asgi():
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    async def cible(request):
        return JSONResponse({"ok": True})

    app = orr.envelopper_observation(
        Starlette(routes=[Route("/api/task/assign", cible, methods=["POST"])]),
        ring_de=lambda scope: 3)
    r = TestClient(app).post("/api/task/assign")
    assert r.status_code == 200                      # observation : ne bloque pas
    assert len(orr.OBSERVES) == 1                    # sans jeton : aurait refuse, journalise
    orr.OBSERVES.clear()
    app2 = orr.envelopper_observation(
        Starlette(routes=[Route("/x", cible, methods=["POST"])]), ring_de=lambda scope: 5)
    assert TestClient(app2).post("/x").status_code == 200 and not orr.OBSERVES


def test_cablage_hub_present():
    src = (RACINE / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    assert "ObservationASGI" in src

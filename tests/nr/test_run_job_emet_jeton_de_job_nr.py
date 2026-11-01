"""NR : le run_job du hub passe une fabrique de jeton de job a launch_job (owner 29/10, chantier coffre cloisonne).

Mesure du 29/10 (job_9a9e8163b463, vrai run_job) : NOKIDO_JOB_ID ABSENT de l'environnement du job. La fabrique existe
(app/forge_oauth_route.emettre_pour_job, parametre jeton_factory de forge_job_runner.launch_job, tests de la suite 4),
mais l'appel du hub ne la passait pas : l'echange RFC 8693 ne pouvait jamais avoir lieu, et un job devait lire le
secret ring <= 3 au coffre -- une garde branchee sur un signal que personne n'emet.
"""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "app" / "forge_mcp_registry.py"


def _appels_launch_job():
    arbre = ast.parse(SRC.read_text(encoding="utf-8"))
    return [n for n in ast.walk(arbre) if isinstance(n, ast.Call)
            and getattr(n.func, "id", getattr(n.func, "attr", None)) == "launch_job"]


def test_le_run_job_du_hub_passe_la_fabrique_de_jeton():
    appels = _appels_launch_job()
    assert appels, "aucun appel launch_job dans forge_mcp_registry"
    for a in appels:
        kw = {k.arg: k.value for k in a.keywords}
        assert "jeton_factory" in kw, "launch_job appele sans jeton_factory (ligne %d)" % a.lineno
        v = kw["jeton_factory"]
        nom = getattr(v, "id", getattr(v, "attr", ""))
        assert "emettre_pour_job" in nom, "fabrique inattendue ligne %d : %s" % (a.lineno, ast.dump(v)[:80])


def test_la_fabrique_existe_et_prend_un_job():
    import inspect
    import sys
    sys.path.insert(0, str(SRC.parents[1]))
    from app.forge_oauth_route import emettre_pour_job
    assert len(inspect.signature(emettre_pour_job).parameters) >= 1

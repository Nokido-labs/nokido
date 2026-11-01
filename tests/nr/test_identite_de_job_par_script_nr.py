"""NR -- option B (owner 30/10) : chaque job recoit l'identite de SON script, et chaque identite une portee minimale
mesuree sur l'appelant reel ; trusted_script n'est jamais accorde depuis le bac.

Journal d'observation du coffre (30/10) : forge_banc_amelioration lit FORGE_TOKEN_SELF_PATCHER (appels `ask`) et
forge_rss_watcher FORGE_TOKEN_RSS_WATCHER (appels `rag` action=ingest). Table d'identites DANS LE CODE (relue, gouvernee),
jamais dans un fichier de configuration modifiable par un agent. Script inconnu = identite JOB (task:status/assign).
Secret factice : aucun secret reel.
"""
import ast
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE)]
from app import forge_oauth_route as O  # noqa: E402
from app import forge_token_exchange as tx  # noqa: E402

SECRET = b"secret-factice-de-test-0123456789"


def test_portees_minimales_par_identite():
    assert O.POLITIQUE_DEFAUT["SELF_PATCHER"]["scopes"] == ["ask:appel"]
    assert O.POLITIQUE_DEFAUT["RSS_WATCHER"]["scopes"] == ["rag:ingest"]
    assert all(p["ring"] >= 3 for p in O.POLITIQUE_DEFAUT.values())


def test_l_identite_suit_le_script(monkeypatch):
    monkeypatch.setattr(O, "_secret", lambda: SECRET)
    for script, attendu in (("forge_banc_amelioration.py", "SELF_PATCHER"), ("tools/forge_rss_watcher.py", "RSS_WATCHER"),
                            ("C:/tmp/laforge_jobs/inconnu.py", "JOB"), (None, "JOB")):
        ch = tx.lire_jeton(O.emettre_pour_job("job_x", script=script), SECRET)
        assert ch["ident"] == attendu, (script, ch["ident"])


def test_le_lanceur_de_jobs_donne_le_script_a_la_fabrique():
    src = (RACINE / "app" / "forge_job_runner.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "launch_job")
    appels = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "jeton_factory"]
    assert any("script" in {k.arg for k in c.keywords} for c in appels)

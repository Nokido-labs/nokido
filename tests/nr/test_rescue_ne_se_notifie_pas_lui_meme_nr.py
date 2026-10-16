"""NR -- le hook Stop de Claude ne s'ecrit plus a lui-meme et ne resume plus a chaque tour (mesure du 2026-10-14).

Chaine mesuree : hook Stop (tire a CHAQUE fin de tour) -> tools/session_anchor.py -> forge_rescue.py --resync gemini
-> notification de « l'autre agent » = CLAUDE, c'est-a-dire l'emetteur : 18 messages RESCUE non lus en une matinee,
et une entree vide « Session Claude end » par tour dans lessons_learned.md.

Le generateur du prompt de reprise interroge services, NSSM, Docker et la boite M2M : on ne le lance pas ici. On
verrouille la STRUCTURE (la notification est inatteignable avec --sans-notifier), le CHEMIN REEL du hook (copie
lancee dans un dossier temporaire, ancre et pouls frais : il saute resume et resync), et la logique de la fenetre.
"""
import ast
import importlib.util
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESCUE = ROOT / "tools" / "forge_rescue.py"
ANCRE_HOOK = ROOT / "tools" / "session_anchor.py"


def test_avec_sans_notifier_le_hub_n_est_jamais_contacte():
    arbre = ast.parse(RESCUE.read_text(encoding="utf-8"))
    options = [a.value for n in ast.walk(arbre) if isinstance(n, ast.Call)
               and getattr(n.func, "attr", "") == "add_argument" for a in n.args if isinstance(a, ast.Constant)]
    assert "--sans-notifier" in options
    gardes = [n for n in ast.walk(arbre) if isinstance(n, ast.If) and isinstance(n.test, ast.Attribute)
              and n.test.attr == "sans_notifier"]
    assert gardes, "aucune garde `if args.sans_notifier`"
    assert all("HubClient" not in "".join(ast.dump(s) for s in g.body) for g in gardes), \
        "le chemin --sans-notifier atteint encore le hub"
    assert any("HubClient" in "".join(ast.dump(s) for s in g.orelse) for g in gardes), \
        "la notification doit vivre dans la branche SANS l'option"


def test_le_hook_stop_appelle_le_resync_sans_notifier():
    assert '"--resync", "gemini", "--sans-notifier"' in ANCRE_HOOK.read_text(encoding="utf-8")


def _recent_isole(tmp_path: Path, ancre: Path, periode: int):
    """`_recent` du hook, isole : le module s'execute a l'import, on n'en charge que la fonction (source par AST)."""
    src = ANCRE_HOOK.read_text(encoding="utf-8")
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "_recent")
    module = tmp_path / "recent_isole.py"
    module.write_text("from pathlib import Path\nANCRE = Path(%r)\nPERIODE_S = %d\n\n%s\n"
                      % (str(ancre), periode, ast.get_source_segment(src, fn)), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("recent_isole", module)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._recent


def test_la_fenetre_de_30_min(tmp_path):
    ancre = tmp_path / "session_anchor.dernier"
    recent = _recent_isole(tmp_path, ancre, 1800)
    maintenant = time.time()
    assert recent(maintenant) is False, "ancre absente : on agit"
    ancre.write_text("%.0f" % maintenant, encoding="utf-8")
    assert recent(maintenant + 60) is True
    assert recent(maintenant + 4000) is False
    ancre.write_text("illisible", encoding="utf-8")
    assert recent(maintenant) is False, "ancre illisible : on agit, jamais un silence definitif"


def test_le_hook_reel_saute_resume_et_resync_dans_la_fenetre(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "sandbox").mkdir()
    copie = tmp_path / "tools" / "session_anchor.py"
    copie.write_text(ANCRE_HOOK.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "sandbox" / "session_anchor.dernier").write_text("%.0f" % time.time(), encoding="utf-8")
    pouls = json.dumps({"ts": datetime.now().isoformat()})
    for nom in ("multi_llm_daemon", "gemini_poll_daemon"):                 # pouls frais : aucun daemon relance
        (tmp_path / "sandbox" / ("%s.heartbeat" % nom)).write_text(pouls, encoding="utf-8")
    r = subprocess.run([sys.executable, str(copie)], capture_output=True, text=True, errors="replace", timeout=60,
                       cwd=str(tmp_path))
    sortie = r.stdout + r.stderr
    assert "SAUTES" in sortie, sortie
    assert "session_summary" not in sortie and "resync gemini" not in sortie, sortie
    assert "relanc" not in sortie, "un pouls frais ne relance aucun daemon"

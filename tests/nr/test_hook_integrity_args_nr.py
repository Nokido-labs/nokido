# -*- coding: utf-8 -*-
"""NR 2026-11-04 -- hook_integrity_check lisait seulement `command` d'un hook. Le CLI cable desormais
au format {"command": PYTHON, "args": [SCRIPT]} : le controle ne voyait que python.exe,
declarait TOUS les gardes « CABLAGE ABSENT » / « DORMANT » (bash_guard compris, qui bloquait pourtant
dans la meme session) et imprimait ~40 lignes a CHAQUE demarrage (owner : « 16 % de contexte »).

Contrat :
  1. un script passe dans `args` (chemin AVEC espaces) est une cible du hook ;
  2. au demarrage, quand rien n'est mort ni illisible, la sortie tient en UNE ligne ;
  3. un filet TROUE (script absent) reste annonce en clair, ligne par ligne (jamais resume).
"""
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))
import hook_integrity_check as H  # noqa: E402


def _settings(tmp_path, script):
    dossier = tmp_path / "Script python IA"
    dossier.mkdir(exist_ok=True)
    s = dossier / "settings.json"
    s.write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": sys.executable, "args": [str(script)]}]}]}}), encoding="utf-8")
    return s


def _sortie(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        H.main(argv)
    return [l for l in buf.getvalue().splitlines() if l.strip()]


def test_script_dans_args_est_une_cible(tmp_path):
    dossier = tmp_path / "Script python IA"
    dossier.mkdir()
    script = dossier / "garde_fictif.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    rows = H.run_check([str(_settings(tmp_path, script))])
    cibles = {Path(r["cible"]).name for r in rows}
    assert "garde_fictif.py" in cibles, cibles


def test_demarrage_sain_tient_en_une_ligne(tmp_path):
    dossier = tmp_path / "Script python IA"
    dossier.mkdir()
    script = dossier / "garde_fictif.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    lignes = _sortie(["--settings", str(_settings(tmp_path, script))])
    assert len(lignes) == 1, lignes
    assert lignes[0].startswith("[hook-integrity]")


def test_filet_troue_reste_detaille(tmp_path):
    absent = tmp_path / "Script python IA" / "garde_disparu.py"
    lignes = _sortie(["--settings", str(_settings(tmp_path, absent))])
    texte = "\n".join(lignes)
    assert "FILET DE HOOKS TROUE" in texte
    assert "garde_disparu.py" in texte

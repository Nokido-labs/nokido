"""NR — un hook declare dans DEUX settings tire DEUX fois, et le verificateur le DIT.

Mesure 2026-09-19 : 11 hooks etaient declares a la fois dans ~/.claude/settings.json
et dans <projet>/.claude/settings.local.json -- forge_tool_gate, hook_recon_first,
hook_capability_gate, hook_posttool_validate, claude_inbox_tick, claude_precompact,
claude_session_start, forge_directive_audit, claude_session_stop, forge_ci_stop_hook,
et hook_integrity_check LUI-MEME. Il annoncait "60 cablages verifies, tous OK" en
etant aveugle a sa propre duplication : il verifie chaque fichier, jamais le
croisement. Cout mesure : chaque garde s'execute deux fois par appel d'outil, et
chaque sortie de hook est injectee deux fois dans le contexte.

Ce NR garde le CROISEMENT, jamais la fusion : le dedup par fichier de `run_check`
est volontaire (2026-08-29 -- deux settings peuvent cabler le meme script avec des
matchers DIFFERENTS, et fusionner rendrait le second invisible). D'ou la
contre-epreuve `matchers_differents`, qui doit rester SILENCIEUSE.
"""
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
hic = importlib.import_module("hook_integrity_check")


def _settings(chemin, event, matcher, cible):
    chemin.write_text(json.dumps({"hooks": {event: [
        {"matcher": matcher,
         "hooks": [{"type": "command", "command": '"%s"' % cible}]}]}}),
        encoding="utf-8")
    return str(chemin)


def _cible(tmp_path):
    """Une cible REELLE : un doublon sur un fichier mort se confondrait avec un mort."""
    p = tmp_path / "garde_temoin.py"
    p.write_text("x = 1\n", encoding="utf-8")
    return str(p)


def test_meme_hook_dans_deux_settings_est_signale(tmp_path):
    cible = _cible(tmp_path)
    a = _settings(tmp_path / "a.json", "PreToolUse", "Bash", cible)
    b = _settings(tmp_path / "b.json", "PreToolUse", "Bash", cible)

    doublons = hic._doublons(hic.run_check([a, b]))

    assert len(doublons) == 1, "meme event + meme matcher + meme cible = un doublon"
    (event, matcher, vue), fichiers = doublons[0]
    assert (event, matcher) == ("PreToolUse", "Bash")
    assert vue.endswith("garde_temoin.py")
    assert sorted(fichiers) == sorted([a, b]), "les DEUX sources doivent etre nommees"


def test_matchers_differents_ne_sont_PAS_un_doublon(tmp_path):
    """Contre-epreuve : le cas legitime du 2026-08-29 doit rester silencieux.

    Un garde qui crie a faux se fait desarmer -- c'est la regle du depot.
    """
    cible = _cible(tmp_path)
    a = _settings(tmp_path / "a.json", "PreToolUse", "Bash", cible)
    b = _settings(tmp_path / "b.json", "PreToolUse", "PowerShell", cible)

    assert hic._doublons(hic.run_check([a, b])) == []


def test_deux_declarations_dans_LE_MEME_fichier_ne_sont_pas_un_doublon(tmp_path):
    """`run_check` dedup deja par fichier : ne pas recompter ce qu'il a ecarte."""
    cible = _cible(tmp_path)
    a = tmp_path / "a.json"
    a.write_text(json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": '"%s"' % cible}]},
        {"matcher": "Bash", "hooks": [{"type": "command", "command": '"%s"' % cible}]},
    ]}}), encoding="utf-8")

    assert hic._doublons(hic.run_check([str(a)])) == []


def test_le_rapport_NOMME_le_doublon_et_son_cout(tmp_path, capsys):
    """Le chemin REEL : `main`, pas seulement la fonction pure."""
    cible = _cible(tmp_path)
    a = _settings(tmp_path / "a.json", "PreToolUse", "Bash", cible)
    b = _settings(tmp_path / "b.json", "PreToolUse", "Bash", cible)

    assert hic.main(["--settings", a, "--settings", b]) == 0
    sortie = capsys.readouterr().out

    assert "DOUBLON" in sortie, "un doublon silencieux se lit comme un cablage sain"
    assert "EXECUTE 2 fois" in sortie, "dire le COUT, pas seulement le fait"
    assert a in sortie and b in sortie, "nommer les deux sources, sinon rien a corriger"


def test_le_json_porte_les_doublons_sans_faire_basculer_ok(tmp_path, capsys):
    """Observer avant d'enforcer : un gate neuf ne devient pas bloquant d'emblee."""
    cible = _cible(tmp_path)
    a = _settings(tmp_path / "a.json", "PreToolUse", "Bash", cible)
    b = _settings(tmp_path / "b.json", "PreToolUse", "Bash", cible)

    assert hic.main(["--json", "--settings", a, "--settings", b]) == 0
    rapport = json.loads(capsys.readouterr().out)

    assert rapport["ok"] is True, "un doublon n'est pas un trou du filet"
    assert len(rapport["doublons"]) == 1
    assert rapport["doublons"][0]["n_executions"] == 2


def test_une_ligne_de_settings_illisible_ne_devient_pas_un_doublon(tmp_path):
    """Les lignes d'erreur n'ont pas de cle `event` : les compter fabriquerait un faux."""
    a = tmp_path / "a.json"
    a.write_text("{ ceci n'est pas du JSON", encoding="utf-8")
    b = tmp_path / "b.json"
    b.write_text("{ ceci non plus", encoding="utf-8")

    rows = hic.run_check([str(a), str(b)])
    assert rows, "le JSON invalide doit produire des lignes, sinon rien n'est vu"
    assert hic._doublons(rows) == []
    assert hic._recouvrements(rows) == []


def test_matchers_qui_se_recouvrent_sont_signales_A_INSTRUIRE(tmp_path, capsys):
    """La porte que l'egalite des matchers ne tient pas.

    Mesure 2026-09-19 : hook_capability_gate cable `...run|Bash` d'un cote et
    `...run|Bash|PowerShell|playwright` de l'autre. Le second CONTIENT le premier,
    le garde s'affichait deux fois sur un appel Bash, et le test d'egalite ne
    voyait rien. Troisieme etat : ni doublon certain, ni distinct.
    """
    cible = _cible(tmp_path)
    a = _settings(tmp_path / "a.json", "PreToolUse", "mcp__x__run|Bash", cible)
    b = _settings(tmp_path / "b.json", "PreToolUse",
                  "mcp__x__run|Bash|PowerShell|mcp__playwright__.*", cible)

    rows = hic.run_check([a, b])
    assert hic._doublons(rows) == [], "matchers distincts : pas un doublon CERTAIN"

    rec = hic._recouvrements(rows)
    assert len(rec) == 1, "mais le recouvrement possible doit etre NOMME"
    (event, vue), paires = rec[0]
    assert event == "PreToolUse" and vue.endswith("garde_temoin.py")
    assert len(paires) == 2 and {m for _, m in paires} != {""}

    assert hic.main(["--settings", a, "--settings", b]) == 0
    sortie = capsys.readouterr().out
    assert "RECOUVREMENT A INSTRUIRE" in sortie
    assert "matchers DIFFERENTS" in sortie


def test_plusieurs_matchers_dans_UN_SEUL_fichier_ne_sont_pas_un_recouvrement(tmp_path):
    """Contre-epreuve indispensable : bash_guard est cable 3 fois dans le MEME
    fichier (Bash, PowerShell, Monitor). C'est le cas NORMAL du 2026-08-29 --
    le signaler ferait crier le garde a faux, et un garde qui crie a faux se
    fait desarmer.
    """
    cible = _cible(tmp_path)
    a = tmp_path / "a.json"
    a.write_text(json.dumps({"hooks": {"PreToolUse": [
        {"matcher": m, "hooks": [{"type": "command", "command": '"%s"' % cible}]}
        for m in ("Bash", "PowerShell", "Monitor")
    ]}}), encoding="utf-8")

    rows = hic.run_check([str(a)])
    assert len(rows) == 3, "les trois cablages doivent rester VISIBLES"
    assert hic._recouvrements(rows) == []
    assert hic._doublons(rows) == []

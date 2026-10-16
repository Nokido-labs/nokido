"""NR -- le rappel d'une skill arrive au MOMENT ou elle s'applique (tools/forge_skill_hint.py).

Owner 2026-10-14 : 26 skills installees, 4 utilisees. « Le rappel arrive au moment de l'erreur,
pas dans une liste » : un test qui vient d'echouer rappelle forge-systematic-debugging, une URL a
ingerer rappelle forge-veille-rapide. Ce NR tient trois promesses :

  - le rappel part sur le bon signal et se tait sur une sortie saine ;
  - il ne crie qu'une fois par skill, par session et par fenetre (un rappel qui crie a chaque appel
    se fait ignorer, puis desarmer) ;
  - il passe par le CHEMIN REEL : les deux hooks deja cables (firewall PostToolUse, inbox
    UserPromptSubmit) et le drapeau `--verifier`, pas seulement la fonction.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

hint = importlib.import_module("forge_skill_hint")

ECHEC_PYTEST = "\n".join(["tests/nr/test_x.py ..F.", "FAILED tests/nr/test_x.py::test_y - assert 1 == 2",
                          "========= 1 failed, 3 passed in 0.42s ========="])
SAIN_PYTEST = "========= 4 passed in 0.40s ========="
RUN = "mcp__laforge-sovereign-hub__run"


@pytest.fixture
def isole(tmp_path, monkeypatch):
    """Etat et journal du rappel dans tmp : un test ne touche jamais sandbox/."""
    monkeypatch.setattr(hint, "ETAT", tmp_path / "etat")
    monkeypatch.setattr(hint, "JOURNAL", tmp_path / "journal.jsonl")
    return tmp_path


def _skills(lignes):
    return [l.split()[1] for l in lignes]


def test_la_table_reelle_est_conforme():
    assert hint.verifier() == []


def test_un_echec_pytest_rappelle_le_debogage_et_se_journalise(isole):
    lignes = hint.suggerer("PostToolUse", ECHEC_PYTEST, outil=RUN, session="s1")
    assert _skills(lignes) == ["forge-systematic-debugging"]
    journal = [json.loads(l) for l in (isole / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(j["skill"], j["evenement"], j["outil"]) for j in journal] == [
        ("forge-systematic-debugging", "PostToolUse", RUN)]


def test_une_sortie_saine_ne_rappelle_rien(isole):
    assert hint.suggerer("PostToolUse", SAIN_PYTEST, outil=RUN, session="s1") == []
    assert not (isole / "journal.jsonl").exists()


def test_un_outil_hors_liste_ne_rappelle_rien(isole):
    assert hint.suggerer("PostToolUse", ECHEC_PYTEST, outil="Read", session="s1") == []


def test_un_rappel_par_skill_par_session_et_par_fenetre(isole):
    t0 = 1_000_000.0
    assert hint.suggerer("PostToolUse", ECHEC_PYTEST, outil=RUN, session="s1", maintenant=t0)
    assert hint.suggerer("PostToolUse", ECHEC_PYTEST, outil=RUN, session="s1", maintenant=t0 + 60) == []
    assert hint.suggerer("PostToolUse", ECHEC_PYTEST, outil=RUN, session="s2", maintenant=t0 + 60)
    assert hint.suggerer("PostToolUse", ECHEC_PYTEST, outil=RUN, session="s1",
                         maintenant=t0 + hint.RAPPEL_S + 1)


def test_un_job_mort_rappelle_l_autopsie(isole):
    sortie = json.dumps({"ok": True, "job_id": "job_x", "status": "failed", "rc": 1})
    assert _skills(hint.suggerer("PostToolUse", sortie, outil=RUN, session="s1")) == ["forge-workflow-autopsy"]


def test_la_veille_rapide_exige_l_url_et_le_verbe(isole):
    assert "forge-veille-rapide" in _skills(
        hint.suggerer("UserPromptSubmit", "ingère https://exemple.org/doc stp", session="a"))
    assert "forge-veille-rapide" not in _skills(
        hint.suggerer("UserPromptSubmit", "regarde https://exemple.org/doc", session="b"))


def test_des_noms_de_skills_cites_ne_declenchent_rien(isole):
    """Cas reel du 14/10 : l'owner colle la sortie de --preview, qui CITE les skills."""
    colle = ('{"cli": "claude", "slug": "forge-m2m-debat-mesure", "action": "REPLACE"}\n'
             '{"cli": "gemini", "slug": "forge-tdd"}\n{"cli": "claude", "slug": "forge-android"}')
    assert hint.suggerer("UserPromptSubmit", colle, session="colle") == []
    # le meme mot hors d'un nom de skill reste un signal
    assert "forge-tdd" in _skills(hint.suggerer("UserPromptSubmit", "on fait du TDD ici", session="vrai"))


def test_l_inbox_ecrit_en_utf8(monkeypatch):
    import io
    tick = _charger_hook("claude_inbox_tick")
    brut = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(brut, encoding="cp1252"))
    tick._stdout_utf8()
    print("débat →")
    sys.stdout.flush()
    assert "débat →".encode("utf-8") in brut.getvalue()


def test_une_table_illisible_le_dit(tmp_path, capsys):
    mauvaise = tmp_path / "t.json"
    mauvaise.write_text("{pas du json", encoding="utf-8")
    assert hint.charger(mauvaise) == []
    assert "table illisible" in capsys.readouterr().err


def test_un_declencheur_invalide_est_ecarte_et_le_dit(tmp_path, capsys):
    t = tmp_path / "t.json"
    t.write_text(json.dumps({"declencheurs": [
        {"skill": "a", "evenement": "PostToolUse", "un_de": ["("], "pourquoi": "x"},
        {"skill": "b", "evenement": "PostToolUse", "pourquoi": "sans motif"},
        {"skill": "c", "evenement": "PostToolUse", "un_de": ["ok"], "pourquoi": "x"}]}), encoding="utf-8")
    assert [d["skill"] for d in hint.charger(t)] == ["c"]
    err = capsys.readouterr().err
    assert "declencheur 0 ecarte" in err and "declencheur 1 ecarte" in err


def test_verifier_refuse_une_skill_absente_ou_retiree(tmp_path):
    (tmp_path / "skills" / "vivante").mkdir(parents=True)
    (tmp_path / "skills" / "vivante" / "SKILL.md").write_text("---\nname: vivante\n---\n", encoding="utf-8")
    (tmp_path / "skills" / "morte").mkdir()
    (tmp_path / "skills" / "morte" / "SKILL.md").write_text("---\nname: morte\n---\n", encoding="utf-8")
    (tmp_path / "retires.json").write_text(json.dumps({"_doc": "x", "morte": {}}), encoding="utf-8")
    t = tmp_path / "t.json"
    t.write_text(json.dumps({"declencheurs": [
        {"skill": s, "evenement": "UserPromptSubmit", "un_de": ["x"], "pourquoi": "x"}
        for s in ("vivante", "morte", "fantome")]}), encoding="utf-8")
    defauts = hint.verifier(t, tmp_path / "skills", tmp_path / "retires.json")
    assert any(d.startswith("morte : skill RETIREE") for d in defauts)
    assert any(d.startswith("fantome : absente") for d in defauts)
    assert not any(d.startswith("vivante") for d in defauts)


def test_point_d_entree_verifier():
    r = subprocess.run([sys.executable, str(TOOLS / "forge_skill_hint.py"), "--verifier"],
                       capture_output=True, text=True, errors="replace", timeout=60, cwd=str(ROOT))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "skill_triggers : CONFORME" in r.stdout


def _charger_hook(nom):
    spec = importlib.util.spec_from_file_location(nom + "_sous_test", TOOLS / (nom + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("champ", ["tool_output", "tool_response"])
def test_le_firewall_posttooluse_ajoute_le_rappel(isole, capsys, champ):
    fw = _charger_hook("hook_context_firewall")
    fw.DOSSIER_ARCHIVE = isole / "archive"
    rc = fw.traiter({"hook_event_name": "PostToolUse", "tool_name": RUN, champ: ECHEC_PYTEST,
                     "tool_succeeded": True, "session_id": "hook-" + champ})
    assert rc == 0
    sortie = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert "forge-systematic-debugging" in sortie["additionalContext"]
    assert "updatedToolOutput" not in sortie  # sortie courte : rien a reduire, seulement le rappel


def test_le_firewall_reste_muet_sur_une_sortie_saine(isole, capsys):
    fw = _charger_hook("hook_context_firewall")
    assert fw.traiter({"hook_event_name": "PostToolUse", "tool_name": RUN, "tool_output": SAIN_PYTEST,
                       "session_id": "muet"}) == 0
    assert capsys.readouterr().out == ""


def test_l_inbox_userpromptsubmit_rappelle_la_skill(isole, monkeypatch):
    tick = _charger_hook("claude_inbox_tick")
    monkeypatch.setattr(tick, "_PROMPT", "lance une veille approfondie sur les runtimes d'agents")
    monkeypatch.setattr(tick, "_SESSION_ID", "inbox")
    assert "forge-veille-approfondie" in _skills(tick._skills_du_tour())
    monkeypatch.setattr(tick, "_PROMPT", "")
    assert tick._skills_du_tour() == []

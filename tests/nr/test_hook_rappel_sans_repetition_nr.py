"""NR -- P1a economie de contexte (GO owner 22/10) : un rappel de hook deja montre a l'identique n'est pas reinjecte.

Mesure P0 (22/10, tools/forge_contexte_par_source.py) : les injections de hooks pesent 7-8 % du cout de relecture,
et 60-67 % d'entre elles repetent mot pour mot un texte deja dans le contexte ([forge-tool-gate] 81 %,
[capability-gate] 79 %, [langue] 98 %). `claude_inbox_tick._sans_repetition` ne couvrait que [memoire...].

Rien de la reflexion ne se perd : seul un texte IDENTIQUE deja present est retire ; il revient s'il change, apres la
fenetre de rappel, et apres chaque compaction ou /clear. Un REFUS (deny) ne passe jamais par ce filtre.
"""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_hook_rappel as R  # noqa: E402


def _charger(nom):
    spec = importlib.util.spec_from_file_location(nom + "_nr_rappel", ROOT / "tools" / (nom + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


GATE = "[forge-tool-gate] DÉPORT conseillé -> hub:read_function_body (cible Nokido)"
LANGUE = "[langue] Réponds en FRANÇAIS."


def test_identique_retire_change_remontre(tmp_path):
    assert R.filtrer(GATE, "s1", 1000.0, tmp_path) == GATE
    assert R.filtrer(GATE, "s1", 1001.0, tmp_path) is None
    autre = GATE.replace("read_function_body", "query")
    assert R.filtrer(autre, "s1", 1002.0, tmp_path) == autre


def test_deux_rappels_qui_alternent_ne_reviennent_pas_a_chaque_fois(tmp_path):
    autre = GATE.replace("read_function_body", "query")
    R.filtrer(GATE, "s1", 1000.0, tmp_path)
    R.filtrer(autre, "s1", 1001.0, tmp_path)
    assert R.filtrer(GATE, "s1", 1002.0, tmp_path) is None


def test_sections_par_balise_seule_la_changee_revient(tmp_path):
    texte = "[sense] alerte cli_present\n" + LANGUE
    R.filtrer(texte, "s1", 1000.0, tmp_path)
    sortie = R.filtrer("[sense] alerte flap\n" + LANGUE, "s1", 1001.0, tmp_path)
    assert sortie == "[sense] alerte flap"


def test_fenetre_de_rappel_sans_session_et_sessions_independantes(tmp_path):
    R.filtrer(LANGUE, "s1", 1000.0, tmp_path)
    assert R.filtrer(LANGUE, "s1", 1000.0 + R.RAPPEL_S + 1, tmp_path) == LANGUE
    assert R.filtrer(LANGUE, "s2", 1001.0, tmp_path) == LANGUE
    R.filtrer(LANGUE, "", 1000.0, tmp_path)
    assert R.filtrer(LANGUE, "", 1001.0, tmp_path) == LANGUE


def test_oublier_fait_tout_revenir_apres_une_compaction(tmp_path):
    R.filtrer(LANGUE, "s1", 1000.0, tmp_path)
    assert R.oublier("s1", tmp_path) is True
    assert R.filtrer(LANGUE, "s1", 1001.0, tmp_path) == LANGUE


def test_un_etat_illisible_montre_tout(tmp_path):
    R.filtrer(LANGUE, "s1", 1000.0, tmp_path)
    for f in tmp_path.glob("rappels_*.json"):
        f.write_text("{pas du json", encoding="utf-8")
    assert R.filtrer(LANGUE, "s1", 1001.0, tmp_path) == LANGUE


def test_sans_racine_de_donnees_le_filtre_s_ouvre(monkeypatch):
    # cliquet racine_donnees : le dossier d'etat vient de forge_db_path.racine_donnees(), jamais de __file__ ;
    # introuvable -> on montre tout, on ne cache jamais par defaut
    monkeypatch.delenv("LAFORGE_HOOK_RAPPEL_DIR", raising=False)
    monkeypatch.setattr(R, "_racine_etat", lambda: None)
    assert R.filtrer(LANGUE, "s1", 1000.0) == LANGUE
    assert R.filtrer(LANGUE, "s1", 1001.0) == LANGUE
    assert R.oublier("s1") is False


def test_le_contrat_historique_de_claude_inbox_tick_passe_par_le_module(tmp_path):
    tick = _charger("claude_inbox_tick")
    texte = "[memoire:immediate] DETTES\n  - dette_a\n[memoire:proprioceptive] ETAT\n  - score 82/100"
    assert tick._sans_repetition(texte, "s1", 1000.0, tmp_path) == texte
    assert tick._sans_repetition(texte, "s1", 1001.0, tmp_path) is None


def test_session_start_oublie_a_la_compaction_et_au_clear_seulement(tmp_path):
    ss = _charger("claude_session_start")
    for source, attendu in (("compact", True), ("clear", True), ("resume", False), ("startup", False)):
        R.filtrer(LANGUE, "s1", 1000.0, tmp_path)
        ss._oublier_rappels_si_compaction(json.dumps({"session_id": "s1", "source": source}), tmp_path)
        revient = R.filtrer(LANGUE, "s1", 1001.0, tmp_path) == LANGUE
        assert revient is attendu, source
        R.oublier("s1", tmp_path)


def test_capability_gate_le_conseil_identique_ne_revient_pas_et_le_journal_compte_toujours(
        tmp_path, monkeypatch, capsys):
    gate = _charger("hook_capability_gate")
    notes = []
    monkeypatch.setattr(gate, "_journal_charger", lambda: {})
    monkeypatch.setattr(gate, "_journal_noter", lambda emp, t: notes.append(emp))
    monkeypatch.setattr(gate, "promotion_verdict", lambda *a, **k: {"promu": False, "n": 0, "depuis_j": 0})
    # les autres gardes du hook ecrivent dans l'etat REEL du poste : neutres ici, ce test ne mesure que le filtre
    monkeypatch.setattr(gate, "verdict_anti_polling", lambda *a, **k: (False, ""))
    monkeypatch.setattr(gate, "verdict_impulsion", lambda *a, **k: ("ok", ""))
    monkeypatch.setattr(gate, "verdict_depense", lambda *a, **k: (False, ""))
    monkeypatch.setattr(gate, "verdict_compte", lambda *a, **k: (False, ""))
    monkeypatch.setattr(gate, "verdict_ci_en_cours", lambda *a, **k: (False, ""))
    monkeypatch.setattr(gate, "verdict_forme", lambda *a, **k: (False, ""))
    monkeypatch.setenv("LAFORGE_HOOK_RAPPEL_DIR", str(tmp_path))
    ev = {"session_id": "s1", "tool_name": "mcp__laforge-sovereign-hub__run",
          "tool_input": {"action": "shell", "code": "cd C:/depot && git status"}}
    sorties = []
    for _ in range(2):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(ev)))
        assert gate.main() == 0
        sorties.append(capsys.readouterr().out)
    assert "additionalContext" in sorties[0] and "capability-gate" in sorties[0]
    assert "additionalContext" not in sorties[1]
    assert len(notes) == 2   # la sensibilisation (promotion en mur) compte chaque declenchement, montre ou non


def test_forge_tool_gate_point_d_entree_reel(tmp_path):
    ev = {"session_id": "s-nr-rappel", "tool_name": "Read",
          "tool_input": {"file_path": str(ROOT / "tools" / "ci_local.py"), "offset": 1, "limit": 5}}
    import os
    env = dict(os.environ, LAFORGE_HOOK_RAPPEL_DIR=str(tmp_path))
    sorties = []
    for _ in range(2):
        p = subprocess.run([sys.executable, str(ROOT / "tools" / "forge_tool_gate.py")], input=json.dumps(ev),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25, env=env)
        assert p.returncode == 0, p.stderr
        sorties.append(json.loads(p.stdout or "{}").get("hookSpecificOutput", {}))
    if "additionalContext" not in sorties[0]:
        return   # ce Read n'appelle pas de conseil sur ce poste : rien a dedoublonner (le cas est couvert en unitaire)
    assert "additionalContext" not in sorties[1]
    assert "permissionDecision" not in sorties[1]

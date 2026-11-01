"""NR -- lanceur nokido_claude : la session Claude Code part sur la cle API du workspace, jamais en silence sur Max (22/10)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import nokido_claude as L  # noqa: E402


def _coffre(monkeypatch, valeurs):
    from nokido_agent.app import forge_secrets as s
    monkeypatch.setattr(s, "get_secret", lambda k: valeurs.get(k))


def test_la_cle_du_coffre_est_posee_et_le_jeton_oauth_retire(monkeypatch):
    _coffre(monkeypatch, {"ANTHROPIC_API_KEY_ORG": "cle-de-test"})
    env = L.environnement({"ANTHROPIC_AUTH_TOKEN": "oauth", "PATH": "x"})
    assert env["ANTHROPIC_API_KEY"] == "cle-de-test"
    assert "ANTHROPIC_AUTH_TOKEN" not in env and env["PATH"] == "x"


def test_sans_cle_le_lanceur_refuse_sans_lancer(monkeypatch):
    _coffre(monkeypatch, {})
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    lances = []
    monkeypatch.setattr(L.subprocess, "call", lambda *a, **k: lances.append(a) or 0)
    assert L.main([]) == 2 and lances == []


def test_avec_cle_claude_est_lance_avec_les_arguments(monkeypatch):
    _coffre(monkeypatch, {"ANTHROPIC_API_KEY_ORG": "cle-de-test"})
    vus = []
    monkeypatch.setattr(L.subprocess, "call", lambda cmd, env=None: vus.append((cmd, env)) or 0)
    monkeypatch.setattr(L, "agent_bin", lambda n: "claude.exe")
    assert L.main(["--resume"]) == 0
    assert vus[0][0] == ["claude.exe", "--resume"] and vus[0][1]["ANTHROPIC_API_KEY"] == "cle-de-test"


def test_sur_cle_api_le_cache_tient_1h_et_la_compaction_vient_tot(monkeypatch):
    """Mesure 22/10 : sur cle API le cache tombe a 5 min (Max : 1 h) et le contexte montait a 785 k tokens ;
    relire 785 k coute 0,31 $ par tour, le reecrire apres une pause ~3,90 $."""
    _coffre(monkeypatch, {"ANTHROPIC_API_KEY_ORG": "cle-de-test"})
    env = L.environnement({"PATH": "x"})
    assert env["ENABLE_PROMPT_CACHING_1H"] == "1"
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "200k"


def test_un_reglage_explicite_de_l_owner_n_est_pas_ecrase(monkeypatch):
    _coffre(monkeypatch, {"ANTHROPIC_API_KEY_ORG": "cle-de-test"})
    env = L.environnement({"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "400k", "ENABLE_PROMPT_CACHING_1H": "0"})
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "400k" and env["ENABLE_PROMPT_CACHING_1H"] == "0"


# --- mode --boucle : boucle interactive au-dessus de `claude -p` (aucun appel reel) ---
# Livre par CLAUDE_HEADLESS (279044b7c, job_07037d8d), integre par Desktop le 22/10. Raison : le credit promo de
# l'owner couvre l'Agent SDK (claude -p), pas Claude Code interactif (billing_error 400, Console du 22/10).

import json  # noqa: E402
import subprocess  # noqa: E402


def _boucle(monkeypatch, saisies, reponses):
    """Simule input() et subprocess.run ; rend la liste des (cmd, env, kwargs) des appels a claude."""
    _coffre(monkeypatch, {"ANTHROPIC_API_KEY_ORG": "cle-de-test"})
    monkeypatch.setattr(L, "agent_bin", lambda n: "claude.exe")
    it = iter(saisies)

    def _input(invite=""):
        v = next(it)
        if isinstance(v, BaseException):
            raise v
        return v

    monkeypatch.setattr("builtins.input", _input)
    appels = []
    rep = iter(reponses)

    def _run(cmd, env=None, **kw):
        appels.append((cmd, env, kw))
        r = next(rep)
        if isinstance(r, BaseException):
            raise r
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(r), stderr="")

    monkeypatch.setattr(L.subprocess, "run", _run)
    return appels


def test_boucle_sortie_propre_sans_appel(monkeypatch):
    for sortie in ("/exit", EOFError(), KeyboardInterrupt()):
        appels = _boucle(monkeypatch, [sortie], [])
        assert L.main(["--boucle"]) == 0 and appels == []


def test_boucle_premier_tour_puis_resume(monkeypatch, capsys):
    appels = _boucle(
        monkeypatch, ["bonjour", "suite", "/exit"],
        [{"result": "r1", "session_id": "S1", "total_cost_usd": 0.01, "is_error": False},
         {"result": "r2", "session_id": "S1", "total_cost_usd": 0.02, "is_error": False,
          "permission_denials": [{"tool_name": "Bash"}]}])
    assert L.main(["--boucle"]) == 0
    c1, env1, kw1 = appels[0]
    assert c1 == ["claude.exe", "-p", "bonjour", "--output-format", "json", "--permission-mode", "acceptEdits"]
    assert env1["ANTHROPIC_API_KEY"] == "cle-de-test" and env1["ENABLE_PROMPT_CACHING_1H"] == "1"
    assert kw1.get("timeout") is None or kw1["timeout"] > 0
    c2 = appels[1][0]
    assert c2[:3] == ["claude.exe", "-p", "suite"] and c2[-2:] == ["--resume", "S1"]
    out = capsys.readouterr().out
    assert "r1" in out and "r2" in out and "0.03" in out and "Bash" in out


def test_boucle_transmet_les_arguments_et_garde_le_mode_de_l_appelant(monkeypatch):
    appels = _boucle(monkeypatch, ["x", "/exit"], [{"result": "ok", "session_id": "S", "total_cost_usd": 0}])
    assert L.main(["--boucle", "--permission-mode", "plan", "--model", "m"]) == 0
    cmd = appels[0][0]
    assert "--boucle" not in cmd and "--model" in cmd
    assert cmd.count("--permission-mode") == 1 and cmd[cmd.index("--permission-mode") + 1] == "plan"


def test_boucle_erreur_affichee_et_question_reposee(monkeypatch, capsys):
    appels = _boucle(
        monkeypatch, ["a", "b", "/exit"],
        [{"is_error": True, "api_error_status": 400, "result": "billing_error", "session_id": "S"},
         {"result": "ok", "session_id": "S2", "total_cost_usd": 0.0}])
    assert L.main(["--boucle"]) == 0
    assert len(appels) == 2
    assert "billing_error" in capsys.readouterr().out
    assert "--resume" not in appels[1][0]  # tour en erreur : pas de session retenue


def test_boucle_sans_cle_refuse(monkeypatch):
    _coffre(monkeypatch, {})
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert L.main(["--boucle"]) == 2


def test_boucle_lit_la_sortie_de_claude_en_utf8(monkeypatch):
    # Windows : sans encodage explicite, `text=True` decode en cp1252 et une reponse accentuee plante la lecture
    appels = _boucle(monkeypatch, ["é", "/exit"], [{"result": "réponse", "session_id": "S", "total_cost_usd": 0}])
    assert L.main(["--boucle"]) == 0
    kw = appels[0][2]
    assert kw.get("encoding") == "utf-8" and kw.get("errors") == "replace"


def test_boucle_ctrl_c_pendant_un_tour_abandonne_le_tour_pas_la_session(monkeypatch, capsys):
    appels = _boucle(monkeypatch, ["long", "/exit"], [KeyboardInterrupt()])
    assert L.main(["--boucle"]) == 0 and len(appels) == 1
    assert "interrompu" in capsys.readouterr().out

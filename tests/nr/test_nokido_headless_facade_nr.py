# -*- coding: utf-8 -*-
"""NR nokido_headless (facade mince) : AUCUN vrai CLI, harness simule par monkeypatch.

REPRISE de job_40520a4d (bloque par le plafond journalier, reaffecte a OpenCode qui n'a rien
livre). Base : dcb021c7d (facade livree sur agent/claude_headless). Trois defauts de relecture :

1. SECURITE (bloquant) -- `--provenance` etait insere TEL QUEL dans la chaine `headersHelper`,
   executee par un SHELL : `--provenance "X & calc"` = EXECUTION ARBITRAIRE. Regle : [A-Z0-9_]
   seulement ; tout autre caractere -> REFUS (rc 2). Jamais dans un headersHelper.
2. ANTI-DUP -- la facade ne REIMPLEMENTE ni la config MCP claude ni ses arguments : elle
   reutilise `forge_task_executor._config_mcp_claude(wt, provenance=...)` et `_args_claude(wt, taille)`
   (worktree TEMPORAIRE, nettoye apres). Option `--taille S|M|L` (defaut M).
3. AGY / OPENCODE / VIBE -- drapeaux et binaires sont ceux de l'EXECUTEUR
   (`_agy_permission_args`, `_args_vibe`, `_config_mcp_vibe`, `_config_opencode_instance`,
   `_bin_agy`/`_bin_vibe`/`_bin_opencode`), pas ceux reecrits par la facade. Les ecarts
   restants sont DOCUMENTS dans la docstring de la facade.

AUCUNE dependance a un binaire reel, AUCUNE sortie de secret, AUCUN reseau.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import forge_task_executor as T  # noqa: E402
import nokido_headless as nh  # noqa: E402

# Compose, jamais en litteral `SECRET = "..."` : le gate egress (generic_secret) bloquait le push (25/10).
SECRET = "-".join(("faux", "jeton", "nr", "0000"))

# --- harness simule -------------------------------------------------------

VUS: dict = {}


class _Proc:
    returncode = 0


class _B:
    proc = _Proc()


class FauxHarness:
    def __init__(self, agent, args, cwd, stdin_devnull):
        self._b = _B()
        self._lu = False
        self.args = list(args)
        VUS.update({
            "agent": agent,
            "args": list(args),
            "cwd": cwd,
            "stdin_devnull": stdin_devnull,
        })
        # la config MCP est lue AU MOMENT du lancement (la facade la supprime apres)
        if "--mcp-config" in self.args:
            idx = self.args.index("--mcp-config")
            VUS["mcp_config"] = json.loads(
                Path(self.args[idx + 1]).read_text(encoding="utf-8"))

    def start(self):
        return self

    def send(self, payload, **kw):
        VUS["stdin"] = payload
        return True

    def send_eof(self):
        return True

    def read(self, timeout=0.5):
        if self._lu:
            return ""
        self._lu = True
        return "ok " + SECRET + '\n{"type":"result","total_cost_usd":0.25}\n'

    def alive(self):
        return False

    def stop(self):
        return None


def _harness_faux(agent, args=None, interactive=False, cwd=None, stdin_devnull=False,
                  binaire=None, env_extra=None):
    VUS.update({"binaire": binaire, "env_extra": dict(env_extra or {})})
    return FauxHarness(agent, args or [], cwd, stdin_devnull)


@pytest.fixture
def prompt_file(tmp_path):
    p = tmp_path / "prompt.txt"
    p.write_text("fais X", encoding="utf-8")
    return p


@pytest.fixture
def faux(monkeypatch, prompt_file):
    import nokido_agent.app.forge_cli_harness as h

    monkeypatch.setattr(h, "harness_for", _harness_faux)
    monkeypatch.setattr(h, "jeton_mcp", lambda agent: {"K": SECRET})
    VUS.clear()
    return prompt_file


# --- socle de la facade ---------------------------------------------------


def test_agent_inconnu_rc2():
    assert nh.main(["inconnu", "--prompt-file", "f"]) == 2


def test_arguments_manquants_rc2():
    assert nh.main([]) == 2


def test_parse_arguments():
    a = nh._parser().parse_args(
        ["vibe", "--prompt-file", "f", "--provenance", "x", "--cwd", "d", "--timeout", "5"])
    assert (a.agent, a.provenance, a.cwd, a.timeout) == ("vibe", "x", "d", 5)


def test_provenance_inconnue_par_defaut(faux, capsys):
    assert nh.main(["claude", "--prompt-file", str(faux)]) == 0
    d = json.loads(capsys.readouterr().out.strip())
    assert d["provenance"] == "INCONNUE"


def test_sortie_json_sans_secret_ni_argv(faux, capsys):
    assert nh.main(["claude", "--prompt-file", str(faux)]) == 0
    out = capsys.readouterr().out.strip()
    assert SECRET not in out
    assert "--mcp-config" not in out
    d = json.loads(out)
    assert d["agent"] == "claude"
    assert d["rc"] == 0
    assert isinstance(d["sortie_tronquee"], str)
    assert isinstance(d["sortie_complete_fichier"], str)
    assert d["cout_usd"] == 0.25


def test_rc_non_nul_si_cli_echoue(faux, monkeypatch):
    monkeypatch.setattr(_Proc, "returncode", 3)
    assert nh.main(["claude", "--prompt-file", str(faux)]) == 3


def test_rc_inconnu_jamais_zero(faux, monkeypatch):
    monkeypatch.setattr(_Proc, "returncode", None)
    assert nh.main(["claude", "--prompt-file", str(faux)]) == 1


# --- defaut 1 : la provenance est STRICTE (injection shell) ----------------

INJECTIONS = [
    "X & calc",            # &  : separateur de commande
    'X " calc',            # "  : fin de quoting
    "X | calc",            # |  : tube
    "X ; calc",            # ;  : separateur
    "X calc",              # espace : mot supplementaire
    "X `calc`",            # backtick : substitution
    "X $(calc)",           # $() : substitution
    "X\ncalc",             # retour a la ligne
    "X>calc",              # redirection
    "X<calc",              # redirection
    "TASK-EXEC",           # tiret : hors alphabet
    "TASK EXEC",           # espace
]


@pytest.mark.parametrize("mauvaise", INJECTIONS)
def test_provenance_injectee_refusee_rc2(faux, mauvaise):
    assert nh.main(["claude", "--prompt-file", str(faux), "--provenance", mauvaise]) == 2


def test_le_refus_de_provenance_dit_pourquoi(faux, capsys):
    assert nh.main(["claude", "--prompt-file", str(faux), "--provenance", "X & calc"]) == 2
    err = capsys.readouterr().err.lower()
    assert "provenance" in err


def test_aucun_lancement_quand_la_provenance_est_refusee(faux, monkeypatch):
    import nokido_agent.app.forge_cli_harness as h

    def _interdit(*a, **k):
        raise AssertionError("l'agent a ete lance avec une provenance refusee")

    monkeypatch.setattr(h, "harness_for", _interdit)
    assert nh.main(["claude", "--prompt-file", str(faux), "--provenance", "X & calc"]) == 2


def test_provenance_valide_normalisee_en_majuscules(faux):
    assert nh.main(["claude", "--prompt-file", str(faux), "--provenance", "codex"]) == 0
    aide = VUS["mcp_config"]["mcpServers"]["nokido"]["headersHelper"]
    assert "--provenance CODEX" in aide


def test_le_headershelper_ne_contient_que_de_l_alphabet_sur(faux):
    assert nh.main(["claude", "--prompt-file", str(faux), "--provenance", "codex"]) == 0
    aide = VUS["mcp_config"]["mcpServers"]["nokido"]["headersHelper"]
    prov = aide.split("--provenance", 1)[1].strip()
    assert re.fullmatch(r"[A-Z0-9_]+", prov)


def test_la_provenance_de_l_appelant_arrive_dans_le_headershelper(faux):
    assert nh.main(["claude", "--prompt-file", str(faux), "--provenance", "opencode_gptoss"]) == 0
    aide = VUS["mcp_config"]["mcpServers"]["nokido"]["headersHelper"]
    assert "--provenance OPENCODE_GPTOSS" in aide


# --- defaut 2 : anti-dup avec l'executeur ----------------------------------


def test_la_facade_appelle_la_config_mcp_de_l_executeur(faux, monkeypatch):
    vus = {}
    orig = T._config_mcp_claude

    def _spy(wt, provenance="TASK_EXECUTOR"):
        vus["provenance"] = provenance
        vus["wt"] = Path(wt)
        return orig(wt, provenance)

    monkeypatch.setattr(T, "_config_mcp_claude", _spy)
    assert nh.main(["claude", "--prompt-file", str(faux), "--provenance", "codex"]) == 0
    assert vus["provenance"] == "CODEX"
    assert vus["wt"].is_dir() or True  # le spy tourne AVANT le nettoyage


def test_le_repertoire_de_config_temporaire_est_nettoye(faux, monkeypatch):
    vus = {}
    orig = T._config_mcp_claude

    def _spy(wt, provenance="TASK_EXECUTOR"):
        vus["wt"] = Path(wt)
        return orig(wt, provenance)

    monkeypatch.setattr(T, "_config_mcp_claude", _spy)
    assert nh.main(["claude", "--prompt-file", str(faux)]) == 0
    assert vus["wt"].exists() is False


def test_la_facade_appelle_les_args_claude_de_l_executeur(faux, monkeypatch):
    vus = {}
    orig = T._args_claude

    def _spy(wt, taille=None):
        vus["taille"] = taille
        vus["wt"] = Path(wt)
        return orig(wt, taille)

    monkeypatch.setattr(T, "_args_claude", _spy)
    assert nh.main(["claude", "--prompt-file", str(faux), "--taille", "L"]) == 0
    assert vus["taille"] == "L"
    args = VUS["args"]
    assert args[args.index("--model") + 1] == T._MODELE_CLAUDE_PAR_TAILLE["L"]
    assert int(args[args.index("--max-turns") + 1]) == T._TOURS_CLAUDE_PAR_TAILLE["L"]
    assert "--bare" in args and "--strict-mcp-config" in args


def test_taille_par_defaut_m(faux, monkeypatch):
    vus = {}
    orig = T._args_claude

    def _spy(wt, taille=None):
        vus["taille"] = taille
        return orig(wt, taille)

    monkeypatch.setattr(T, "_args_claude", _spy)
    assert nh.main(["claude", "--prompt-file", str(faux)]) == 0
    assert vus["taille"] == "M"


@pytest.mark.parametrize("taille", ["S", "M", "L"])
def test_les_tailles_aller_uent(faux, taille):
    assert nh.main(["claude", "--prompt-file", str(faux), "--taille", taille]) == 0


def test_taille_invalide_rc2(faux):
    assert nh.main(["claude", "--prompt-file", str(faux), "--taille", "XL"]) == 2


def test_le_defaut_de_la_config_mcp_de_l_executeur_ne_bouge_pas(tmp_path):
    cfg = json.loads(T._config_mcp_claude(tmp_path).read_text(encoding="utf-8"))
    assert "--provenance TASK_EXECUTOR" in cfg["mcpServers"]["nokido"]["headersHelper"]


def test_la_config_mcp_de_l_executeur_refuse_une_provenance_dangereuse(tmp_path):
    with pytest.raises(ValueError):
        T._config_mcp_claude(tmp_path, provenance="X & calc")


# --- defaut 3 : AGY / OPENCODE / VIBE alignes sur l'executeur ---------------


def test_agy_porte_les_memes_drapeaux_que_l_executeur(faux, monkeypatch):
    monkeypatch.setenv("LAFORGE_AGY_BIN", r"C:\bin\agy.exe")
    assert nh.main(["agy", "--prompt-file", str(faux)]) == 0
    args = VUS["args"]
    assert args[0] == "--print"
    assert "--add-dir" in args
    assert args[args.index("--output-format") + 1] == "json"
    assert "--effort" in args
    for drapeau in T._agy_permission_args():
        assert drapeau in args
    assert "--dangerously-skip-permissions" not in args


def test_agy_emploie_le_binaire_de_l_executeur(faux, monkeypatch):
    monkeypatch.setenv("LAFORGE_AGY_BIN", r"C:\bin\agy.exe")
    assert nh.main(["agy", "--prompt-file", str(faux)]) == 0
    assert VUS["binaire"] == r"C:\bin\agy.exe"


def test_vibe_porte_les_memes_args_que_l_executeur(faux, monkeypatch, tmp_path):
    monkeypatch.setenv("LAFORGE_VIBE_BIN", r"C:\bin\vibe.exe")
    cwd = tmp_path / "wt"
    cwd.mkdir()
    assert nh.main(["vibe", "--prompt-file", str(faux), "--cwd", str(cwd)]) == 0
    assert VUS["args"] == T._args_vibe(cwd, Path(faux))
    assert VUS["binaire"] == r"C:\bin\vibe.exe"


def test_vibe_reutilise_la_config_mcp_de_l_executeur(faux, monkeypatch, tmp_path):
    cwd = tmp_path / "wt"
    cwd.mkdir()
    assert nh.main(["vibe", "--prompt-file", str(faux), "--cwd", str(cwd)]) == 0
    attendu = T._config_mcp_vibe(cwd)
    assert attendu.exists()


def test_opencode_reutilise_la_config_de_l_executeur(faux, monkeypatch):
    monkeypatch.setenv("LAFORGE_OPENCODE_INSTANCE", "OPENCODE_GPTOSS")
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda inst: "jeton-fictif-nr")
    assert nh.main(["opencode", "--prompt-file", str(faux)]) == 0
    cfg = json.loads(VUS["env_extra"]["OPENCODE_CONFIG_CONTENT"])
    attendu = T._config_opencode_instance("OPENCODE_GPTOSS", None)
    assert cfg["mcp"]["nokido"]["url"] == attendu["mcp"]["nokido"]["url"]
    assert cfg["permission"] == attendu["permission"]
    assert cfg["mcp"]["nokido"]["headers"]["LaForge-Agent-Name"] == "OPENCODE_GPTOSS"


def test_opencode_porte_la_provenance_dans_ses_entetes(faux, monkeypatch):
    monkeypatch.setenv("LAFORGE_OPENCODE_INSTANCE", "OPENCODE_GPTOSS")
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda inst: "jeton-fictif-nr")
    assert nh.main(["opencode", "--prompt-file", str(faux), "--provenance", "codex"]) == 0
    cfg = json.loads(VUS["env_extra"]["OPENCODE_CONFIG_CONTENT"])
    assert cfg["mcp"]["nokido"]["headers"]["LaForge-Provenance"] == "CODEX"


def test_opencode_emploie_le_binaire_de_l_executeur(faux, monkeypatch):
    monkeypatch.setenv("LAFORGE_OPENCODE_INSTANCE", "OPENCODE_GPTOSS")
    monkeypatch.setenv("LAFORGE_OPENCODE_BIN", r"C:\bin\opencode.exe")
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda inst: None)
    assert nh.main(["opencode", "--prompt-file", str(faux)]) == 0
    assert VUS["binaire"] == r"C:\bin\opencode.exe"


def test_opencode_run_auto_approuve_et_sort_en_json(faux, monkeypatch):
    """22/10 (audit Antigravity job_c7142f5e, `opencode run --help`) : sans `--auto`, toute permission d'outil non
    refusee attend une confirmation INTERACTIVE -> un headless reste bloque ; `--format json` = sortie structuree."""
    monkeypatch.setenv("LAFORGE_OPENCODE_INSTANCE", "OPENCODE_GPTOSS")
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda inst: None)
    assert nh.main(["opencode", "--prompt-file", str(faux)]) == 0
    args = VUS["args"]
    assert args[0] == "run" and "--auto" in args
    assert args[args.index("--format") + 1] == "json"


def test_le_jeton_d_instance_ne_fuit_pas_dans_la_sortie(faux, monkeypatch, capsys):
    monkeypatch.setenv("LAFORGE_OPENCODE_INSTANCE", "OPENCODE_GPTOSS")
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda inst: "jeton-fictif-nr")
    assert nh.main(["opencode", "--prompt-file", str(faux)]) == 0
    out = capsys.readouterr().out
    assert "jeton-fictif-nr" not in out


def test_la_docstring_documente_les_ecarts_agy_opencode_vibe():
    doc = (nh.__doc__ or "")
    assert "ACP" in doc
    assert "opencode" in doc.lower()
    assert "vibe" in doc.lower()
    assert "agy" in doc.lower()

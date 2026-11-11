# -*- coding: utf-8 -*-
"""NR RED -- essence CCR = OUTIL + ARGS de l'appel (tour 3 tranche par l'owner le 2026-11-08).

Defaut prouve EN SERVICE le 8/11 23 h 03 (job_03f767454056) : l'essence d'une archive CCR valait
"tool.run.output:commit [REDACTED:key]". Deux causes :
  1. elle etait tiree de la 1re ligne de la SORTIE ; le caviardeur (forge_conv_sanitizer, hex >= 32)
     y prend un sha git pour une cle -> essence vide de sens. On n'assouplit PAS le caviardeur
     (un hex de 40 peut etre un HMAC) : l'essence ne doit plus dependre de la sortie quand l'appel est connu ;
  2. le tour 3 a tranche "outil + args" (run:<cmd> rc ... err), jamais construit.

Contrat (app/forge_mcp_registry.py) :
  _essence_appel(name, args, rc, echec) -> str   fonction de module, deterministe, <= 150 car.
        "<name>:<action> <commande> rc=<rc|?> <echec|succes>" ; commande = code, ou commands joints
        par " ; ", ou path/script + script_args ; "explanation" jamais reprise ; CAVIARDEE
        (redact_tool_output + _redact). FAIL-CLOSED : caviardeur introuvable -> "<name>" seul.
  _plafonner_sortie(result, name, agent, args=None)   transmet l'essence d'appel a l'archivage.
  _archive_blob(text, agent, label, essence_appel=None) indexe essence_appel quand elle est fournie
        (repli : comportement actuel label + 1re ligne) et passe agent= a observer (meta.agent).
  Le dispatcher passe args a _plafonner_sortie (chemin reel).

Aucun acces a la base RAG ; tout tourne en tmp_path.
"""
import importlib
import inspect
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SECRET = "sk-ant-api03-" + "B" * 40
SHA = "cde9abf9f" + "0123456789abcdef0123456789abcde"  # 40 hex, sortie git typique
assert len(SHA) == 40


def _reg():
    return importlib.import_module("nokido_agent.app.forge_mcp_registry")


@pytest.fixture()
def racine(tmp_path, monkeypatch):
    r = tmp_path / "donnees"
    (r / "sandbox" / "ccr").mkdir(parents=True)
    monkeypatch.setenv("NOKIDO_DATA_DIR", str(r))
    monkeypatch.delenv("LAFORGE_CONTEXT_LEDGER_OBS", raising=False)
    monkeypatch.setenv("FORGE_TOOL_OUTPUT_CAP", "12000")
    monkeypatch.setenv("FORGE_TOOL_OUTPUT_CAP_SUCCES", "6000")
    return r


def _registre(racine):
    reg = _reg()
    soi = reg.ToolRegistry.__new__(reg.ToolRegistry)
    soi.root = racine
    return soi


def _lignes(r):
    conn = sqlite3.connect(str(r / "sandbox" / "context_ledger.db"))
    try:
        return conn.execute("SELECT uri, essence, meta FROM context_ledger").fetchall()
    finally:
        conn.close()


def test_essence_appel_outil_action_commande_rc():
    e = _reg()._essence_appel("run", {"action": "shell", "code": "git log --oneline -3",
                                      "explanation": "ne doit pas apparaitre"}, 0, False)
    assert e.startswith("run:shell git log --oneline -3"), e
    assert "rc=0" in e and "succes" in e
    assert "apparaitre" not in e
    assert len(e) <= 150


def test_essence_appel_commands_et_rc_inconnu():
    e = _reg()._essence_appel("run", {"action": "shell", "commands": ["pytest -q tests/nr", "git status"]},
                              None, True)
    assert "pytest -q tests/nr ; git status" in e, e
    assert "rc=?" in e and "echec" in e


def test_essence_appel_script_et_arguments():
    e = _reg()._essence_appel("run", {"action": "run_job", "script": "C:/tmp/mesure_aa.py",
                                      "script_args": "--fenetre 24h"}, 1, True)
    assert "run_job C:/tmp/mesure_aa.py --fenetre 24h" in e, e
    assert "rc=1" in e


def test_essence_appel_caviardee_et_bornee():
    e = _reg()._essence_appel("run", {"action": "shell", "code": f"curl -H 'x-api-key: {SECRET}' " + "z" * 300},
                              0, False)
    assert SECRET not in e, "secret de la commande recopie dans l'index"
    assert len(e) <= 150


def test_essence_appel_commande_longue_garde_rc_et_statut():
    """Relecture 8/11 : la troncature a 150 car. coupait la QUEUE, donc rc et statut,
    l'information la plus utile a la selection. Le corps se tronque, jamais le suffixe."""
    e = _reg()._essence_appel("run", {"action": "shell", "code": "pytest -q " + "tests/nr/x.py " * 30}, 2, True)
    assert len(e) <= 150, len(e)
    assert e.startswith("run:shell pytest -q"), e
    assert e.endswith("rc=2 echec"), e


def test_essence_appel_fail_closed_sans_caviardeur(monkeypatch):
    import builtins
    reg = _reg()
    vrai_import = builtins.__import__

    def import_sans_caviardeur(nom, *a, **k):
        if "semantic_firewall" in nom or "conv_sanitizer" in nom:
            raise ImportError("caviardeur indisponible (NR)")
        return vrai_import(nom, *a, **k)

    monkeypatch.setattr(builtins, "__import__", import_sans_caviardeur)
    e = reg._essence_appel("run", {"action": "shell", "code": f"echo {SECRET}"}, 0, False)
    assert e == "run", e


def test_plafonner_indexe_l_appel_pas_le_sha_de_la_sortie(racine):
    soi = _registre(racine)
    sortie = f"commit {SHA}\n" + "ligne de log\n" * 1000
    _reg().ToolRegistry._plafonner_sortie(soi, sortie, "run", "CLAUDE",
                                          args={"action": "shell", "code": "git log -200"})
    lignes = _lignes(racine)
    assert len(lignes) == 1, lignes
    _uri, essence, meta = lignes[0]
    assert essence.startswith("run:shell git log -200"), essence
    assert "[REDACTED" not in essence, essence
    assert json.loads(meta or "{}").get("agent") == "CLAUDE", meta


def test_plafonner_json_commands_porte_le_rc_de_l_entree(racine):
    soi = _registre(racine)
    res = json.dumps([{"stdout": "E\n" * 8000, "stderr": "", "exit_code": 1}])
    _reg().ToolRegistry._plafonner_sortie(soi, res, "run", "CLAUDE",
                                          args={"action": "shell", "commands": ["pytest -q"]})
    essence = _lignes(racine)[0][1]
    assert "pytest -q" in essence and "rc=1" in essence and "echec" in essence, essence


def test_compat_sans_args_garde_le_repli(racine):
    soi = _registre(racine)
    _reg().ToolRegistry._plafonner_sortie(soi, "premiere ligne utile\n" + "x\n" * 5000, "run", "CLAUDE")
    essence = _lignes(racine)[0][1]
    assert essence.startswith("tool.run.output:premiere ligne utile"), essence


def test_dispatcher_transmet_args():
    src = inspect.getsource(_reg().ToolRegistry)
    assert "self._plafonner_sortie(result, name, agent, args=args)" in src, \
        "le chemin reel n'alimente pas l'essence d'appel"

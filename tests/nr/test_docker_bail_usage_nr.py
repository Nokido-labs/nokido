# -*- coding: utf-8 -*-
"""NR — l'usage de la prothese Docker prolonge son BAIL.

Defaut mesure le 2026-09-05 : `ensure_daemon()` sort en `already_up` **sans toucher
`docker.wanted`** quand Docker tourne deja. Personne ne prolongeait donc le bail
pendant l'usage : passe TTL (900 s) + grace (900 s), `forge_docker_keeper` relachait
Docker au milieu d'une veille, puis un consommateur le redemandait — la dent de scie.

Le meme drapeau porte DEUX sens — « lance-le » et « je m'en sers encore » — et un seul
etait emis. Meme famille que `llama.wanted`, ou un signal a deux sens a produit les deux
pannes opposees (veto permanent d'un cote, 73 arrets de l'autre).

Rappel de cadrage (owner) : Docker est une PROTHESE, pas un organe. Ce test ne garde pas
la sante de Docker — il garde le fait que ses CONSOMMATEURS declarent leur usage.
"""
import ast
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

agent = pytest.importorskip("forge_docker_agent")


def test_declarer_usage_rafraichit_le_drapeau(tmp_path, monkeypatch):
    flag = tmp_path / "docker.wanted"
    monkeypatch.setattr(agent, "WANT_FLAG", flag)
    monkeypatch.setattr(agent, "daemon_up", lambda: True)
    # Ne pas ecrire dans la base de signaux de prod : l'emission est un effet de bord
    # legitime en runtime, jamais dans un test.
    faux = types.ModuleType("forge_signal_coupling")
    faux.emit_signal = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "forge_signal_coupling", faux)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_signal_coupling", faux)

    assert agent.declarer_usage("test") is True
    assert flag.exists(), "l'usage n'a pas prolonge le bail"
    premier = flag.read_text(encoding="utf-8")
    assert agent.declarer_usage("test") is True
    assert flag.read_text(encoding="utf-8") >= premier


def test_un_bail_ne_survit_pas_a_une_prothese_morte(tmp_path, monkeypatch):
    """Le defaut paye : le bail restait frais pendant que le moteur mourait.

    Mesure 2026-09-05 — `declarer_usage` prolongeait le drapeau a chaque crawl servi
    tandis que Docker mourait quelques minutes plus tard ; le drapeau restant frais,
    le keeper relancait a chaque mort. Chacun des deux mecanismes etait correct
    isolement ; ensemble ils bouclaient. Prolonger un bail sur un moteur A TERRE,
    c'est demander un LANCEMENT en croyant prolonger — deux actes distincts.
    """
    flag = tmp_path / "docker.wanted"
    monkeypatch.setattr(agent, "WANT_FLAG", flag)
    monkeypatch.setattr(agent, "daemon_up", lambda: False)
    assert agent.declarer_usage("test") is False
    assert not flag.exists(), "bail pose alors que la prothese est morte"


def test_declarer_usage_ne_leve_jamais(tmp_path, monkeypatch):
    """Une declaration ratee ne doit pas casser le travail qu'elle accompagne."""
    monkeypatch.setattr(agent, "daemon_up", lambda: True)
    monkeypatch.setattr(agent, "WANT_FLAG", tmp_path / "interdit" / "x" / "docker.wanted")
    monkeypatch.setattr(agent.Path, "mkdir",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("ACL")))
    assert agent.declarer_usage("test") is False


def test_le_chemin_crawl4ai_declare_son_usage():
    """Garde structurel : le tier 1 servi appelle `declarer_usage`.

    Verifie par AST DANS la fonction, pas par presence dans le fichier : c'est la
    lecon de `forge_docker_keeper`, ou une amorce enfouie dans une branche rare
    faisait croire que la dependance etait satisfaite.
    """
    src = (ROOT / "app" / "forge_crawl_tool.py").read_text(encoding="utf-8",
                                                           errors="replace")
    arbre = ast.parse(src)
    cibles = [n for n in ast.walk(arbre)
              if isinstance(n, ast.FunctionDef) and n.name == "crawl_url_detail"]
    assert cibles, "crawl_url_detail introuvable : le NR ne prouve plus rien"
    appels = [x for x in ast.walk(cibles[0])
              if isinstance(x, ast.Call) and getattr(x.func, "id", "") == "declarer_usage"]
    assert appels, "le crawl servi par crawl4ai ne declare pas son usage"

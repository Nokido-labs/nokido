"""NR RED -- choix owner du 9/11 : le gate [untested] AVERTIT honnetement.

Mesure : le commit 565458754 (sujet contenant « wip ») a affiche « [gate][untested] REFUS » et il est PASSE :
`.githooks/prepare-commit-msg` sort toujours en 0 (doctrine des hooks : seuls les secrets bloquent). Le message
mentait. Defaut cache : sur ce « refus », `_prepare_msg` sortait AVANT `_strip_agent_signatures`.

Contrat (tools/forge_git_gate.py) :
  _untested_gate(txt) -> str | None : None si sujet propre, Untested-Ack ou NOKIDO_ALLOW_UNTESTED=1 ; sinon la ligne
      `Untested-Warn: <mot> (avertissement du gate, non assume)` et un message stderr qui dit AVERTISSEMENT, jamais REFUS.
  _prepare_msg(path) -> 0 : ajoute la ligne Untested-Warn au message (l'avertissement reste dans l'historique, il ne
      passe pas en silence) et applique TOUJOURS le retrait des signatures.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_git_gate as G  # noqa: E402


def test_sujet_propre_rien(monkeypatch):
    monkeypatch.delenv("NOKIDO_ALLOW_UNTESTED", raising=False)
    assert G._untested_gate("fix(x): correctif teste\n") is None


def test_wip_avertit_sans_dire_refus(monkeypatch, capsys):
    monkeypatch.delenv("NOKIDO_ALLOW_UNTESTED", raising=False)
    r = G._untested_gate("fix(x): merger controle le wip\n\ncorps\n")
    sortie = capsys.readouterr()
    texte = sortie.out + sortie.err
    assert r == "Untested-Warn: wip (avertissement du gate, non assume)", r
    assert "AVERTISSEMENT" in texte and "REFUS" not in texte, texte
    assert "Untested-Ack" in texte


def test_aveu_et_echappatoire_rien(monkeypatch):
    monkeypatch.delenv("NOKIDO_ALLOW_UNTESTED", raising=False)
    assert G._untested_gate("wip: x\n\nUntested-Ack: reseau non verifie\n") is None
    monkeypatch.setenv("NOKIDO_ALLOW_UNTESTED", "1")
    assert G._untested_gate("wip: x\n") is None


def test_prepare_msg_trace_et_strip_toujours(tmp_path, monkeypatch):
    monkeypatch.delenv("NOKIDO_ALLOW_UNTESTED", raising=False)
    appels = []
    monkeypatch.setattr(G, "_strip_agent_signatures", lambda t: appels.append(t) or t)
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("chore(a): preservation orphelin tache wip\n", encoding="utf-8")
    assert G._prepare_msg(str(msg)) == 0
    assert appels, "le retrait des signatures est saute sur un sujet « wip »"
    assert "Untested-Warn: wip" in msg.read_text(encoding="utf-8")

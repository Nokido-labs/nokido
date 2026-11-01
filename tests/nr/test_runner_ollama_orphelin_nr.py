"""NR 30/10 -- dette runner_ollama_fuite_angle_mort_triple_2026-07-26 (96 jours).

Mesure du 26/07 : apres un ollama_unload, /api/ps ne declare plus aucun modele mais le runner llama-server (enfant
d'ollama.exe) VIT avec 5,59 Go. _reguler_runners_ollama le voyait et ne faisait que le SIGNALER (« rien a decharger,
jamais tue ») : la fuite echappait aux trois regulateurs. Desormais le verdict NOMME l'orphelin, et l'arret -- par la
primitive existante _tuer_llama_pid -- ne s'execute que sur LAFORGE_RUNNER_ORPHELIN_TUER=1 (observer avant d'enforcer ;
armer = decision owner). Conditions inchangees : propriete Nokido PROUVEE, /api/ps LISIBLE et vide, aucune connexion,
grace ecoulee.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app"), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_resource_manager as RM  # noqa: E402

PID = 4242


def _cas(monkeypatch, arme: bool, modeles=(), interrupteur=None):
    # l'interrupteur REEL (sandbox/runner_orphelin_tuer.switch, arme par l'owner le 30/10) ne doit pas fuir ici
    monkeypatch.setattr(RM, "_INTERRUPTEUR_RUNNER_ORPHELIN", interrupteur or Path("Z:/absent/runner.switch"))
    if arme:
        monkeypatch.setenv("LAFORGE_RUNNER_ORPHELIN_TUER", "1")
    else:
        monkeypatch.delenv("LAFORGE_RUNNER_ORPHELIN_TUER", raising=False)
    monkeypatch.setattr(RM, "_audit_lifecycle", lambda *a, **k: None)
    tues = []
    out = {"tues": [], "signales": [], "graces": [], "epargnes": []}
    ident = {"preuve": next(iter(RM._LANCEURS_NOKIDO)), "identite": "NokidoOllama"}
    now = 10_000.0
    RM._reguler_runners_ollama({PID: {"rss_mo": 5590, "ppid": 1}}, {PID: ident}, {}, {PID: now - 3600}, now, 60,
                               list(modeles), None, out, kill=lambda p: tues.append(p) or True)
    return out, tues


def test_orphelin_signale_et_nomme_sans_arret_si_non_arme(monkeypatch):
    out, tues = _cas(monkeypatch, arme=False)
    assert tues == [] and out["tues"] == []
    assert any("ORPHELIN" in s["raison"] and "LAFORGE_RUNNER_ORPHELIN_TUER" in s["raison"] for s in out["signales"])


def test_orphelin_arrete_quand_l_owner_arme(monkeypatch):
    out, tues = _cas(monkeypatch, arme=True)
    assert tues == [PID]
    assert out["tues"] and out["tues"][0]["ok"] is True and "ORPHELIN" in out["tues"][0]["raison"]


def test_l_interrupteur_fichier_arme_sans_variable(monkeypatch, tmp_path):
    switch = tmp_path / "runner_orphelin_tuer.switch"
    switch.write_text("1\n", encoding="utf-8")
    out, tues = _cas(monkeypatch, arme=False, interrupteur=switch)
    assert tues == [PID]
    switch.write_text("0", encoding="utf-8")
    out, tues = _cas(monkeypatch, arme=False, interrupteur=switch)
    assert tues == []


def test_api_ps_illisible_reste_une_abstention_meme_arme(monkeypatch):
    monkeypatch.setenv("LAFORGE_RUNNER_ORPHELIN_TUER", "1")
    monkeypatch.setattr(RM, "_audit_lifecycle", lambda *a, **k: None)
    out = {"tues": [], "signales": [], "graces": [], "epargnes": []}
    ident = {"preuve": next(iter(RM._LANCEURS_NOKIDO)), "identite": "NokidoOllama"}
    RM._reguler_runners_ollama({PID: {"rss_mo": 5590}}, {PID: ident}, {}, {PID: 0.0}, 10_000.0, 60, None, None, out,
                               kill=lambda p: True)
    assert out["tues"] == [] and any("ILLISIBLE" in s["raison"] for s in out["signales"])

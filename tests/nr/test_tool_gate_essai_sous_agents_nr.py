# -*- coding: utf-8 -*-
"""NR — exception d'ESSAI aux sous-agents Claude, armee par l'OWNER, bornee et mesuree (owner 17/10 : « a tester et
mesurer si ca bouffe pas tout le quota, l'exception doit exister pour test, avec des appels le plus economique
possible » ; « essai mesure exceptionnel »).

La regle du 2026-09-06 (« jamais un sous-agent Claude ») reste la regle par defaut. L'exception n'existe que si
l'interrupteur d'essai est present -- dans ~/.claude/hooks/, chemin de POLITIQUE que l'agent ne peut pas ecrire
(1.quater) : un garde dont l'agent tient l'interrupteur ne garde rien. Bornes : date d'expiration, budget d'appels
(compte dans le journal de mesure depuis l'armement), modeles ECONOMES explicites (jamais `inherit`, donc jamais Opus
par defaut), types listes. Chaque appel admis laisse une ligne de mesure.
"""
import datetime
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _gate(monkeypatch, tmp_path, essai=None, lignes=0):
    spec = importlib.util.spec_from_file_location("forge_tool_gate_nr_essai", ROOT / "tools" / "forge_tool_gate.py")
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    interrupteur = tmp_path / "hooks" / "nokido_essai_sous_agents.json"
    journal = tmp_path / "sandbox" / "essai_sous_agents.jsonl"
    if essai is not None:
        interrupteur.parent.mkdir(parents=True)
        interrupteur.write_text(json.dumps(essai), encoding="utf-8")
    if lignes:
        journal.parent.mkdir(parents=True)
        journal.write_text("".join(json.dumps({"ts": essai["arme_le"], "model": "haiku"}) + "\n" for _ in range(lignes)),
                           encoding="utf-8")
    monkeypatch.setattr(g, "_chemin_essai_sous_agents", lambda: interrupteur)
    monkeypatch.setattr(g, "_chemin_journal_essai", lambda: journal)
    return g, journal


def _essai(**k):
    maintenant = datetime.datetime.now()
    e = {"decision": "owner 17/10 essai mesure exceptionnel",
         "arme_le": (maintenant - datetime.timedelta(minutes=1)).isoformat(timespec="seconds"),
         "expire": (maintenant + datetime.timedelta(hours=2)).isoformat(timespec="seconds"),
         "budget": 2, "modeles": ["haiku"], "types": ["Explore"]}
    e.update(k)
    return e


def _agent(g, **args):
    a = {"subagent_type": "Explore", "model": "haiku", "prompt": "verifier sur alpha", "description": "essai"}
    a.update(args)
    return g.decide("claude", "CLAUDE", "Agent", a, ring=1, session="s1")


def test_sans_interrupteur_la_regle_du_06_09_tient(monkeypatch, tmp_path):
    g, _j = _gate(monkeypatch, tmp_path)
    d = _agent(g)
    assert d["action"] == "block" and "REFUSE" in d["reason"], d


def test_un_essai_arme_admet_l_appel_econome_et_le_mesure(monkeypatch, tmp_path):
    g, journal = _gate(monkeypatch, tmp_path, _essai())
    d = _agent(g)
    assert d["action"] != "block", d
    lignes = [json.loads(l) for l in journal.read_text(encoding="utf-8").splitlines()]
    assert len(lignes) == 1 and lignes[0]["model"] == "haiku" and lignes[0]["subagent_type"] == "Explore", lignes
    assert lignes[0]["session"] == "s1" and lignes[0]["prompt_car"] == len("verifier sur alpha")


def test_jamais_opus_ni_inherit_ni_modele_absent(monkeypatch, tmp_path):
    g, _j = _gate(monkeypatch, tmp_path, _essai())
    for args in ({"model": "opus"}, {"model": "inherit"}, {"model": ""}, {"model": None}):
        d = _agent(g, **args)
        assert d["action"] == "block" and "modele" in d["reason"].lower(), (args, d)


def test_budget_epuise_expire_ou_type_non_liste_refuses(monkeypatch, tmp_path):
    g, _j = _gate(monkeypatch, tmp_path, _essai(), lignes=2)
    d = _agent(g)
    assert d["action"] == "block" and "budget" in d["reason"].lower(), d
    passe = (datetime.datetime.now() - datetime.timedelta(minutes=5)).isoformat(timespec="seconds")
    g2, _j2 = _gate(monkeypatch, tmp_path / "b", _essai(expire=passe))
    d2 = _agent(g2)
    assert d2["action"] == "block" and "expir" in d2["reason"].lower(), d2
    g3, _j3 = _gate(monkeypatch, tmp_path / "c", _essai())
    d3 = _agent(g3, subagent_type="general-purpose")
    assert d3["action"] == "block" and "type" in d3["reason"].lower(), d3


def test_un_interrupteur_illisible_ferme(monkeypatch, tmp_path):
    g, _j = _gate(monkeypatch, tmp_path)
    p = tmp_path / "hooks" / "nokido_essai_sous_agents.json"
    p.parent.mkdir(parents=True)
    p.write_text("{pas du json", encoding="utf-8")
    monkeypatch.setattr(g, "_chemin_essai_sous_agents", lambda: p)
    d = _agent(g)
    assert d["action"] == "block", d


def test_l_interrupteur_est_un_chemin_de_politique_que_l_agent_ne_peut_ecrire():
    spec = importlib.util.spec_from_file_location("forge_tool_gate_nr_essai_pol", ROOT / "tools" / "forge_tool_gate.py")
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    cible = str(g._chemin_essai_sous_agents())
    assert g._is_policy_path({"file_path": cible}), cible
    d = g.decide("claude", "CLAUDE", "Write", {"file_path": cible, "content": "{}"}, ring=1, session="s1")
    assert d["action"] == "block", d

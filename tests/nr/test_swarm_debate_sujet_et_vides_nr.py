# -*- coding: utf-8 -*-
"""NR — titre et fichier du debat swarm derives du sujet effectif, et reponse vide exclue/remplacee.

Defauts mesures le 8/11 (swarm job_346b1dc1aa6f, sujet « contexte servi ») :
1) Le titre du rapport reste « Organes Nokido -> agents bas-niveau ? » (sujet par defaut)
   meme quand un autre sujet est passe.
   Correctif : titre et nom du fichier derives du sujet effectif.
2) openrouter_free et nvidia_nim ont rendu une reponse VIDE, comptee comme une participation.
   Correctif : une reponse vide ou reduite aux espaces est un ECHEC du participant (cause « vide »),
   remplace par un remplacant, et jamais compte au quorum.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_swarm_debate as S


def test_derivation_titre_et_fichier_sujet_effectif(tmp_path):
    """Le titre et le fichier de sortie doivent refleter le sujet passe."""
    # Cas par defaut : preserve swarm_debate_organ_tiers.md
    titre_defaut, out_defaut = S.deriver_titre_et_fichier("Organes Nokido -> agents bas-niveau ?", root=tmp_path)
    assert titre_defaut == "Organes Nokido -> agents bas-niveau ?"
    assert out_defaut.name == "swarm_debate_organ_tiers.md"

    # Cas sujet personnalise : slugifie le nom de fichier et garde le titre
    sujet_test = "contexte servi et memoire transitoire"
    titre, out_file = S.deriver_titre_et_fichier(sujet_test, root=tmp_path)
    assert titre == sujet_test
    assert out_file.name == "swarm_debate_contexte_servi_et_memoire_transitoire.md"


def test_reponse_vide_est_un_echec_dans_ask_one(monkeypatch):
    """Une reponse ok:True mais texte vide ou espaces est un echec (cause 'vide')."""
    async def _faux_ask(prov, prompt, **kw):
        if prov == "openrouter_free":
            return {"ok": True, "text": "   "}
        if prov == "nvidia_nim":
            return {"ok": True, "text": ""}
        return {"ok": True, "text": "Reponse argumentee valide"}

    import nokido_agent.app.forge_agent_proxy as P
    monkeypatch.setattr(P, "ask", _faux_ask)

    # Test openrouter_free avec texte blanc
    role, prov, txt, bon = asyncio.run(S._ask_one("ROLE1", "openrouter_free", "Tache"))
    assert bon is False, "une reponse d'espaces ne doit jamais etre lue ok=True"
    assert "vide" in txt.lower(), f"motif attendu contenant 'vide', recu: {txt}"

    # Test nvidia_nim avec texte vide
    role, prov, txt, bon = asyncio.run(S._ask_one("ROLE2", "nvidia_nim", "Tache"))
    assert bon is False, "une reponse vide ne doit jamais etre lue ok=True"
    assert "vide" in txt.lower(), f"motif attendu contenant 'vide', recu: {txt}"


def test_reponse_vide_remplacee_et_jamais_dans_le_quorum(monkeypatch):
    """Dans _round, un participant qui rend vide est remplace et jamais compte au quorum."""
    async def _faux_ask_one(role, prov, task):
        if prov in ("openrouter_free", "nvidia_nim"):
            return (role, prov, "[KO: vide]", False)
        if prov == "groq":
            return (role, prov, "Position Groq solide", True)
        if prov == "cohere":
            return (role, prov, "Position Cohere en remplacement", True)
        return (role, prov, f"Position {prov}", True)

    monkeypatch.setattr(S, "_ask_one", _faux_ask_one)
    monkeypatch.setattr(S, "SPECIALISTS", [
        ("ARCHITECTE", "groq"),
        ("SRE", "openrouter_free"),
    ])

    # 1. Sans remplacant : seul groq est dans ok
    ok = asyncio.run(S._round("Tache", "R1", remplacants=[]))
    provis = [p for _, p, _, _ in ok]
    assert provis == ["groq"], f"openrouter_free ne doit pas etre compte, recu: {provis}"

    # 2. Avec remplacant 'cohere' : SRE est remplace par cohere
    ok_remplace = asyncio.run(S._round("Tache", "R1", remplacants=["cohere"]))
    provis_remp = [p for _, p, _, _ in ok_remplace]
    assert "openrouter_free" not in provis_remp
    assert provis_remp == ["groq", "cohere"], f"cohere aurait du remplacer openrouter_free, recu: {provis_remp}"


def test_main_ecrit_titre_et_fichier_du_sujet_effectif(monkeypatch, tmp_path):
    """main(argv) ecrit un markdown contenant le titre effectif dans le fichier effectif."""
    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "SPECIALISTS", [("Role1", "groq")])

    async def _faux_round(task, label, **kw):
        return [("Role1", "groq", "Texte tour", True)]

    async def _faux_synth(answers, instr):
        return "Synthese test"

    monkeypatch.setattr(S, "_round", _faux_round)
    monkeypatch.setattr(S, "_synth", _faux_synth)

    # Lancement avec --sujet
    sujet = "contexte servi"
    rc = asyncio.run(S.main(["--sujet", sujet]))
    assert rc == 0

    cible = tmp_path / "docs" / "swarm_debate_contexte_servi.md"
    assert cible.exists(), f"Le fichier {cible} aurait du etre cree"
    contenu = cible.read_text(encoding="utf-8")
    assert "# Débat Swarm — contexte servi" in contenu

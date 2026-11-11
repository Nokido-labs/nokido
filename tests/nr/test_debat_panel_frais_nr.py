# -*- coding: utf-8 -*-
"""NR — repli sur sonder_panel quand aucune mesure de capacite n'est fraiche, et objectif courant au RAG.

Defauts mesures le 8/11 (debat job_0fb1de9e3807, quorum 0) :
1) panel_pour lit provider_scores ; les scores etaient perimes ou de statut 'transport' -> panel vide, quorum 0.
   Correctif : si aucun participant n'est eligible avec une mesure <= frais_s, repli sur sonder_panel
   (pre-vol par la capacite) au lieu de rendre un panel vide. 'transport' != capacite.
2) run_debate passait une requete en dur 'transient state blackboard' a _rag_context quel que soit l'objectif.
   Correctif : passer l'objectif courant.
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_debate_job as D


def test_transport_ne_vaut_pas_capacite_dans_preflight(monkeypatch):
    """Une mesure 'transport' (ping catalogue) ne prouve pas la capacite : elle doit etre INELIGIBLE."""
    from datetime import datetime
    maintenant_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    class FakeConn:
        def execute(self, q):
            return self
        def fetchall(self):
            # statut transport frais
            return [("ollama_local", "transport", "B", 12.0, maintenant_str)]
        def close(self):
            pass

    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: FakeConn())
    pf = D.preflight_providers(frais_s=86400.0)
    assert pf["lisible"] is True
    assert pf["eligibles"] == [], "transport ne doit JAMAIS etre eligible"
    detail = pf["detail"][0]
    assert detail["etat"] == "INELIGIBLE"
    assert "transport" in (detail["motif"] or "")


def test_panel_pour_repli_sonder_panel_si_aucun_eligible(monkeypatch):
    """Quand preflight n'a aucun eligible frais, panel_pour se rabat sur sonder_panel."""
    monkeypatch.setattr(D, "preflight_providers", lambda *a, **k: {
        "lisible": True, "raison": None, "eligibles": [],
        "detail": [{"provider": "p1", "etat": "INCONNU", "statut": "ok", "grade": "A", "ttft_ms": 10, "age_s": 999999, "motif": "perime"}]
    })

    sonde_appele = []

    async def _faux_sonder(roles, remplacants=None, minimum=2, question="OK"):
        sonde_appele.append((roles, remplacants, minimum))
        return [("Proposeur", "groq"), ("Analyste", "mistral")], []

    monkeypatch.setattr(D, "sonder_panel", _faux_sonder)

    parts, pf = D.panel_pour("Mon objectif metier")
    assert len(sonde_appele) == 1, "sonder_panel aurait du etre appele en repli"
    assert len(parts) >= 2, "le panel reconstruit doit contenir au moins 2 participants"
    assert parts[0][0] == "Proposeur" and parts[0][1] == "groq"
    assert parts[1][0] == "Analyste" and parts[1][1] == "mistral"
    # Verification que les prompts de roles sont injectes depuis _ROLES
    assert "PROPOSEUR" in parts[0][2]
    assert "ANALYSTE" in parts[1][2]


def test_run_debate_passe_objectif_courant_au_rag(monkeypatch):
    """run_debate ne doit plus passer le fossile 'transient state blackboard' a _rag_context."""
    requetes_rag = []

    def _faux_rag(query: str) -> str:
        requetes_rag.append(query)
        return "(contexte rag teste)"

    monkeypatch.setattr(D, "_rag_context", _faux_rag)
    monkeypatch.setattr(D, "panel_pour", lambda obj, **k: (
        [("P1", "groq", "Role P1"), ("P2", "mistral", "Role P2")],
        {"lisible": True, "eligibles": [{"provider": "groq"}, {"provider": "mistral"}]}
    ))

    async def _faux_turn(prov, prompt, max_tokens=520):
        # Reponse structuree pour eviter le blocage de synthese
        return "AXE: architecture | admis | solide", True

    monkeypatch.setattr(D, "_turn", _faux_turn)

    objectif_test = "Verifier la resilience des organes face a un crash memoire"
    r = asyncio.run(D.run_debate(objectif_test, "Contrainte test", None, 1))

    assert len(requetes_rag) == 1
    assert requetes_rag[0] == objectif_test, (
        "L'objectif courant doit etre passe a _rag_context, recu : %r" % requetes_rag[0]
    )
    assert "transient state blackboard" not in requetes_rag[0]

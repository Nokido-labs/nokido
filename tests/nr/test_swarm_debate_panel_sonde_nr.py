"""NR 3/11 — le debat swarm SONDE son panel avant le tour 1 et ne se tait plus sur un echec.

Mesure du 3/11 (debat de geometrie, job_63ef8e4b14fc puis job_2170a5338f6f) : mistral 403 (hors palier),
cerebras 402 (paiement requis), `groq:<modele>` « Provider inconnu » -- tous passes par le pre-vol
(resolve_provider_panel sans etat des disjoncteurs) ; `_round` filtrait les echecs SANS les dire ; 2 runs a procedure
INVALIDE, dont un ou le defenseur de la these n'a jamais parle.

Contrats :
  1. `sonder_panel` garde un fournisseur seulement s'il REPOND (texte non vide) ; un muet est remplace par un
     remplacant lui aussi sonde, jamais deux roles sur le meme remplacant ; rend aussi les ecartes avec leur motif.
  2. Moins de `minimum` roles vivants -> `ValueError` (fail-closed), jamais un debat boiteux.
  3. `_round` journalise chaque echec (role, fournisseur, motif) au lieu de l'avaler.
"""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

D = pytest.importorskip("forge_swarm_debate")

VIVANTS = {"groq", "cohere", "gemini", "openrouter_free"}


def _faux_ask(prov, prompt, **kw):
    async def _f():
        if prov in VIVANTS:
            return {"ok": True, "text": "OK"}
        if prov == "cerebras":
            return {"ok": False, "text": "", "error": "Error code: 402 payment_required"}
        return {"ok": False, "text": "", "error": "Provider '%s' inconnu" % prov}
    return _f()


@pytest.fixture(autouse=True)
def ask_simule(monkeypatch):
    import nokido_agent.app.forge_agent_proxy as P
    monkeypatch.setattr(P, "ask", _faux_ask)


def test_les_muets_sont_remplaces_par_des_vivants_sondes():
    roles = [("A", "groq"), ("B", "cerebras"), ("C", "mistral"), ("D", "cohere"), ("E", "groq:llama")]
    panel, ecartes = asyncio.run(D.sonder_panel(roles, remplacants=["gemini", "openrouter_free", "cerebras"],
                                                minimum=4))
    provs = [p for _, p in panel]
    assert dict(panel)["A"] == "groq" and dict(panel)["D"] == "cohere"
    assert set(provs) <= VIVANTS
    assert len(provs) == len(set(provs)), "deux roles sur le meme remplacant"
    motifs = dict(ecartes)
    assert "402" in motifs["cerebras"] and "inconnu" in motifs["groq:llama"]


def test_fail_closed_sous_le_minimum():
    with pytest.raises(ValueError):
        asyncio.run(D.sonder_panel([("A", "groq"), ("B", "cerebras"), ("C", "mistral")], remplacants=[],
                                   minimum=3))


def test_round_journalise_les_echecs(monkeypatch, capsys):
    monkeypatch.setattr(D, "SPECIALISTS", [("A", "groq"), ("B", "cerebras")])
    ok = asyncio.run(D._round("sujet", "R1"))
    out = capsys.readouterr().out
    assert [p for _, p, _, _ in ok] == ["groq"]
    assert "cerebras" in out and "402" in out

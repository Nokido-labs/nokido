"""NR -- les 7 lecteurs du jeton maitre ont une identite au registre (etape 3 du chantier jeton maitre, 22/10).

Aucun repli n'est retire ici : on declare seulement les identites, le semis vient apres.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REGISTRE = Path(__file__).resolve().parents[2] / "config" / "agent_identities.json"
# EPISTEMIC (owner 26/10) : la soif deposait ses enquetes de code sous FORGE_TOKEN_SERVICES+repli_statique,
# vue ring 4 par le hub -> « GATE_DENIED: ring 4 <= requis 3 » sur l'outil task (logs/epistemic_daemon.log 20:17:51).
NOMS = ["GOAP", "A2A", "ACP", "ORCHESTRATE", "SELF_PATCHER", "MULTI_LLM", "WATCHDOG", "EPISTEMIC"]
CLES_OBLIGATOIRES = {"ring", "kind", "actor", "surface", "mailbox", "audience", "aliases",
                     "channel", "transport", "machine"}


def _agents() -> dict:
    return json.loads(REGISTRE.read_text(encoding="utf-8"))["agents"]


@pytest.mark.parametrize("nom", NOMS)
def test_identite_presente_ring_et_schema(nom):
    a = _agents()
    assert nom in a, f"{nom} absente du registre"
    e = a[nom]
    assert isinstance(e["ring"], int) and 2 <= e["ring"] <= 4
    assert CLES_OBLIGATOIRES <= set(e), f"cles manquantes: {CLES_OBLIGATOIRES - set(e)}"
    assert e["pourquoi"].strip(), "le lecteur (fichier:ligne) doit etre cite"
    assert ".py:" in e["pourquoi"]


def test_aucune_entree_ne_porte_de_valeur_de_jeton():
    interdits = ("token", "secret", "jeton_valeur", "password", "bearer", "api_key")
    for nom, e in _agents().items():
        for cle, val in e.items():
            # tpm_jkt = empreinte PUBLIQUE de cle (RFC 7638), pas un secret.
            if cle in ("pourquoi", "motif", "_note", "jeton_direct") or cle.endswith("_jkt"):
                continue
            assert not any(i in cle.lower() for i in interdits), f"{nom}.{cle}"
            assert not (isinstance(val, str) and len(val) >= 40 and " " not in val
                        and val.replace("-", "").replace("_", "").isalnum()), f"{nom}.{cle} ressemble a un jeton"

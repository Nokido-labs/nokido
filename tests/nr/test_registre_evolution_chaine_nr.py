"""NR -- le registre d'evolution est CHAINE : une entree reecrite, supprimee ou alteree se DETECTE.

Veille RSI 26/09 (primitive P7) : exo -- « the only thing it can't muck with is an event log which provides a
canonical history » ; darwin-godel-machine garde un paquet de preuves a somme de controle, echecs compris.
Cadre owner (bb architecture_rules/p1_auto_amelioration_cadre_rsi_owner_0925) : un historique de preuve
IMMUABLE que l'organisme ne reecrit jamais. Mesure : sandbox/evolution/evolution_experiences.jsonl (942
lignes) etait un JSONL en append, sans chaine -- rien ne distinguait une ligne reecrite d'une ligne ecrite.
Patron repris de tools/forge_memory_ledger._append (prev + contenu -> sha256), sans dupliquer le module.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def AL(tmp_path, monkeypatch):
    m = importlib.import_module("forge_autonomous_loops")
    monkeypatch.setattr(m, "_EVOLUTION_LEDGER", tmp_path / "evolution_experiences.jsonl")
    monkeypatch.setattr(m, "_ensure_ledger_migrated", lambda: None)
    return m


def _poser(AL, n):
    for i in range(n):
        AL.record_evolution_experience({"kind": "test", "status": "PENDING_CANDIDATE", "n": i,
                                        "parent_commit": "t"})


def test_une_chaine_intacte_se_verifie(AL):
    _poser(AL, 3)
    r = AL.verifier_chaine_evolution()
    assert r["ok"] is True and r["chainees"] == 3 and r["rupture"] is None


def test_une_entree_alteree_rompt_la_chaine(AL):
    _poser(AL, 3)
    p = Path(AL._EVOLUTION_LEDGER)
    lignes = p.read_text(encoding="utf-8").splitlines()
    e = json.loads(lignes[1])
    e["status"] = "PROMOTED"                        # l'organisme reecrit son propre historique
    lignes[1] = json.dumps(e, ensure_ascii=False)
    p.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    r = AL.verifier_chaine_evolution()
    assert r["ok"] is False and r["rupture"] == 2


def test_une_entree_supprimee_rompt_la_chaine(AL):
    _poser(AL, 3)
    p = Path(AL._EVOLUTION_LEDGER)
    lignes = p.read_text(encoding="utf-8").splitlines()
    p.write_text("\n".join([lignes[0], lignes[2]]) + "\n", encoding="utf-8")
    assert AL.verifier_chaine_evolution()["ok"] is False


def test_les_lignes_heritees_ancrent_la_chaine_sans_etre_reecrites(AL):
    p = Path(AL._EVOLUTION_LEDGER)
    heritee = json.dumps({"kind": "ancien", "exp_id": "x"}, ensure_ascii=False)
    p.write_text(heritee + "\n", encoding="utf-8")
    _poser(AL, 2)
    lignes = p.read_text(encoding="utf-8").splitlines()
    assert lignes[0] == heritee                                             # jamais reecrite
    assert json.loads(lignes[1])["prev_hash"] == hashlib.sha256(heritee.encode("utf-8")).hexdigest()
    r = AL.verifier_chaine_evolution()
    assert r["ok"] is True and r["heritees"] == 1 and r["chainees"] == 2

"""NR : un candidat AWAITING_OWNER DECIDE par l'owner sort de l'attente (30/10).

Mesure du 30/10 (job_17808359299a) : `rapport()` listait encore `20261029_232657_0.patch` en `awaiting_owner` alors
que son gain (0,630) etait INTEGRE (forge_rag_engine.requete_fts, decision owner « juge du travail fourni ») : aucune
ligne du registre ne savait porter une decision, donc une attente durait toujours et affichait une decision fantome.
La decision est un MAILLON du registre chaine (verifier_registre reste ok), jamais une reecriture.
"""
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE / "tools"), str(RACINE / "app"), str(RACINE)]
import forge_banc_amelioration as B  # noqa: E402


def _registre(tmp_path):
    reg = tmp_path / "rappel_lexical" / "registre.jsonl"
    B.consigner_banc(reg, "rappel_lexical", "AWAITING_OWNER", 0.63, "max", "banc:t:0", "diff", 0.57,
                     extra={"patch": "a.patch"})
    return reg


def test_une_decision_sort_le_candidat_de_l_attente(tmp_path):
    reg = _registre(tmp_path)
    assert B.rapport(tmp_path)["rappel_lexical"]["awaiting_owner"] == ["a.patch"]
    ligne = B.decider(reg, "a.patch", "integre", "f330cb061")
    assert ligne["statut"] == "DECIDE_OWNER" and ligne["decision"] == "integre" and ligne["preuve"] == "f330cb061"
    assert B.rapport(tmp_path)["rappel_lexical"]["awaiting_owner"] == []
    from forge_bench_takehome import verifier_registre
    assert verifier_registre(reg)["ok"] is True


def test_decision_inconnue_ou_sans_attente_refusee(tmp_path):
    reg = _registre(tmp_path)
    with pytest.raises(ValueError):
        B.decider(reg, "a.patch", "peut-etre", "x")
    with pytest.raises(ValueError):
        B.decider(reg, "absent.patch", "rejete", "x")
    B.decider(reg, "a.patch", "rejete", "motif")
    with pytest.raises(ValueError):
        B.decider(reg, "a.patch", "integre", "x")   # deja decide : pas de seconde decision silencieuse


def test_le_drapeau_cli_traverse_main(tmp_path, monkeypatch, capsys):
    reg = _registre(tmp_path)
    monkeypatch.setattr(B, "BANCS", tmp_path)
    assert B.main(["--cible", "rappel_lexical", "--decider", "a.patch", "--decision", "integre",
                   "--preuve", "f330cb061"]) == 0
    assert json.loads(capsys.readouterr().out)["statut"] == "DECIDE_OWNER"
    assert B.rapport(tmp_path)["rappel_lexical"]["awaiting_owner"] == []
    assert reg.exists()

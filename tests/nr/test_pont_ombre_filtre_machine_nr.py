"""NR -- pont ombre : filtre MACHINE (decision owner 18/10, elargissement RSI n°2).

Mesure du 18/10 : les 15 dossiers A_TRAITER retenus etaient TOUS des ECART_DOC_CODE
(module decrit dans un doc d'intention, absent du code) -- une decision owner, pas un candidat
que le juge sait evaluer. Le pont ne retient plus qu'une LISTE BLANCHE de traitements
producibles par machine ; les traitements owner sortent vers une file owner, dite.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_autonomous_loops as al  # noqa: E402


def _triage(dossier, treatment, verdict="A_TRAITER", ts="2026-10-18T10:00:00", **extra):
    return {"kind": "triage", "dossier": dossier, "treatment": treatment, "ts": ts,
            "organ": "o", "reexamen": {"verdict": verdict}, **extra}


def test_un_ecart_doc_code_n_est_jamais_retenu_par_le_pont():
    reg = [_triage("doc1", "ECART_DOC_CODE"), _triage("doc1", "ECART_DOC_CODE", ts="2026-10-18T11:00:00")]
    assert al.selectionner_dossier_ombre(reg) is None


def test_une_mutation_code_jugee_reste_retenue_meme_moins_recurrente():
    reg = [_triage("doc1", "ECART_DOC_CODE"), _triage("doc1", "ECART_DOC_CODE", ts="2026-10-18T11:00:00"),
           _triage("mut1", "MUTATION_CODE_JUGEE")]
    sel = al.selectionner_dossier_ombre(reg)
    assert sel and sel["dossier"] == "mut1"


def test_traitement_inconnu_ou_absent_n_est_pas_retenu():
    # liste BLANCHE : une valeur inattendue ne tombe pas du cote « jugeable » par defaut
    reg = [_triage("x", "TRAITEMENT_NEUF"), _triage("y", None)]
    assert al.selectionner_dossier_ombre(reg) is None


def test_la_file_owner_recoit_les_ecarts_doc_code_au_dernier_reexamen():
    reg = [_triage("doc1", "ECART_DOC_CODE",
                   reexamen={"verdict": "A_TRAITER", "par_cible": {"forge_x.py": "ECART_CONFIRME"}}),
           _triage("doc2", "ECART_DOC_CODE", verdict="RESOLU"),
           _triage("mut1", "MUTATION_CODE_JUGEE")]
    file = al.file_owner_ombre(reg)
    assert [d["dossier"] for d in file] == ["doc1"]
    assert file[0]["treatment"] == "ECART_DOC_CODE"
    assert file[0]["cibles"] == ["forge_x.py"]


def test_la_file_owner_suit_le_dernier_reexamen():
    reg = [_triage("doc1", "ECART_DOC_CODE"),
           _triage("doc1", "ECART_DOC_CODE", verdict="RESOLU", ts="2026-10-18T12:00:00")]
    assert al.file_owner_ombre(reg) == []

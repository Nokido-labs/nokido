"""NR 29/10 soir -- forge_banc_amelioration.rapport() appelait meilleur_prouve SANS le juge courant : apres
l'enrichissement du corpus (juge different), le rapport affichait encore le 1,0 de l'ANCIEN juge alors que le juge
actuel mesure 0,576 -- et ce chiffre perime a fait dire « corpus sature » (faux). L'execution filtrait deja par le
juge (job_1a73a9186e99) ; le rapport suit desormais le DERNIER juge consigne."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "app"), str(ROOT)]

import forge_banc_amelioration as B  # noqa: E402


def test_le_rapport_suit_le_dernier_juge(tmp_path):
    reg = tmp_path / "juge_ancrage_swarm" / "registre.jsonl"
    ancien, courant = {"corpus": "aaa"}, {"corpus": "bbb"}
    B.consigner_banc(reg, "juge_ancrage_swarm", "REFERENCE", 1.0, "max", "ref", reference=ancien)
    B.consigner_banc(reg, "juge_ancrage_swarm", "REFERENCE", 0.576, "max", "ref", reference=courant)
    B.consigner_banc(reg, "juge_ancrage_swarm", "GARDE_ROUGE", None, "max", "candidat", reference=courant)
    r = B.rapport(tmp_path)["juge_ancrage_swarm"]
    assert r["meilleur_prouve"] == 0.576


def test_registre_sans_reference_inchange(tmp_path):
    reg = tmp_path / "cible" / "registre.jsonl"
    B.consigner_banc(reg, "cible", "REFERENCE", 0.8, "max", "ref")
    assert B.rapport(tmp_path)["cible"]["meilleur_prouve"] == 0.8

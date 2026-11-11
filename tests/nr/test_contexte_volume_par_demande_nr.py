"""NR 5/11 (owner, tokens) : volume rendu par les outils entre deux messages de l'owner, base du seuil de budget."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import forge_contexte_par_source as C  # noqa: E402


def _resultat(taille):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x" * taille}]}}


def _ecrire(chemin, entrees):
    chemin.write_text("".join(json.dumps(e) + "\n" for e in entrees), encoding="utf-8")


ENTREES = [
    {"type": "user", "message": {"content": "premiere demande"}},
    _resultat(100),
    _resultat(300),
    {"type": "user", "message": {"content": "<task-notification>pas une demande</task-notification>"}},
    _resultat(100),
    {"type": "user", "isMeta": True, "message": {"content": "contexte injecte"}},
    {"type": "user", "message": {"content": [{"type": "text", "text": "deuxieme demande"}]}},
    _resultat(50),
]


def test_les_retours_d_outil_sont_comptes_par_demande_de_l_owner():
    r = C.volume_par_demande(ENTREES)
    assert r["demandes"] == 2
    assert r["max"] == 500 + 3 * 2  # guillemets JSON de chaque contenu
    assert r["total"] == 500 + 50 + 4 * 2


def test_une_transcription_sans_demande_rend_zero_sans_planter():
    assert C.volume_par_demande([])["demandes"] == 0


def test_le_drapeau_traverse_le_point_d_entree_et_accepte_un_dossier(tmp_path, capsys):
    _ecrire(tmp_path / "s1.jsonl", ENTREES)
    assert C.main([str(tmp_path), "--par-demande"]) == 0
    sortie = capsys.readouterr().out
    assert "s1.jsonl" in sortie and "demandes 2" in sortie
    assert "ENSEMBLE" in sortie

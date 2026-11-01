"""NR -- finitions du secours (recette reelle 29/10 11 h 21, cli_swarm_ptr_20261029_110707.json) :
« 2512 » de `ministral-8b-2512` compte comme chiffre a ancrer (identifiant, pas une mesure) ; et l'ancien
`synthese_motif` (« synthese vide… ») reste dans le JSON apres une integration reussie. tmp_path, aucun hub."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "app")]

import pytest  # noqa: E402

import forge_cli_swarm as S  # noqa: E402


@pytest.fixture(autouse=True)
def _seuil_substance_neutre(monkeypatch):
    """29/10 : textes factices courts ; le garde de substance a ses NR (test_secours_texte_complet_nr)."""
    monkeypatch.setattr(S, "SYNTHESE_MIN_CAR", 0)


def test_nombre_colle_a_un_identifiant_non_compte():
    """`ministral-8b-2512`, `gpt-oss:120b`, `qwen2.5-coder` : pas des chiffres a ancrer."""
    assert S._chiffres("membre ministral-8b-2512 et gpt-oss-120b") == []


def test_mesure_isolee_toujours_comptee():
    """Une mesure isolee reste comptee (garde du juge intacte)."""
    assert S._chiffres("gain de 2512 tokens") == ["2512"]


def test_integration_reussie_retire_l_ancien_motif(monkeypatch, tmp_path):
    """Integration reussie -> synthese_motif obsolete retire."""
    monkeypatch.setattr(S, "_statut_tache", lambda *_a: (_ for _ in ()).throw(AssertionError("pas de hub")))
    res = tmp_path / "r.json"
    res.write_text(json.dumps({"task": "c", "answers": [], "synthese_motif": "synthese vide par x"}), encoding="utf-8")
    txt = tmp_path / "t.txt"
    txt.write_text("- mecanisme sans chiffre", encoding="utf-8")
    assert S.main(["--integrer-secours", str(res), "t", "--texte", str(txt)]) == 0
    assert "synthese_motif" not in json.loads(res.read_text(encoding="utf-8"))

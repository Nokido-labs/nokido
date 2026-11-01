"""NR -- `--integrer-secours ... --texte <fichier>` : le LANCEUR fournit le texte, le job ne lit aucun statut hub.

Recette reelle 29/10 11 h 19 : `--integrer-secours` depuis un job -> « GATE_DENIED: ring 4 <= requis 3 » sur `task status`
(la lecture du statut est aussi reservee au ring <= 3). Garde conservee : le lanceur (ring 1-3) lit le statut et ecrit le
texte dans un fichier ; le job n'applique que les gardes. Faux hub qui leve au moindre appel, tmp_path."""
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


def _interdit(*_a, **_k):
    raise AssertionError("aucun appel hub attendu avec --texte")


def test_texte_du_lanceur_integre_sans_hub(monkeypatch, tmp_path):
    """Texte fourni -> gardes appliquees, synthese ecrite, aucun appel au statut hub ; chiffre invente retire."""
    monkeypatch.setattr(S, "_statut_tache", _interdit)
    res = tmp_path / "res.json"
    res.write_text(json.dumps({"task": "consigne avec 34055 relus", "answers": []}), encoding="utf-8")
    txt = tmp_path / "texte.txt"
    txt.write_text("- pool chaud : 34055 relus\n- gain invente de 42 %", encoding="utf-8")
    rc = S.main(["--integrer-secours", str(res), "tache_x", "--agent", "CLAUDE_HEADLESS", "--texte", str(txt)])
    d = json.loads(res.read_text(encoding="utf-8"))
    assert rc == 0 and d["synthese_par"] == "executeur:CLAUDE_HEADLESS"
    assert "34055" in d["synthesis"] and "42 %" not in d["synthesis"].split("[juge")[0]
    assert d["secours_integre"]["task_id"] == "tache_x"


def test_texte_absent_rien_ecrit(monkeypatch, tmp_path):
    """Fichier texte introuvable -> rc non nul, JSON inchange."""
    monkeypatch.setattr(S, "_statut_tache", _interdit)
    res = tmp_path / "res.json"
    res.write_text(json.dumps({"task": "c", "answers": []}), encoding="utf-8")
    rc = S.main(["--integrer-secours", str(res), "t", "--texte", str(tmp_path / "absent.txt")])
    assert rc != 0 and "synthesis" not in json.loads(res.read_text(encoding="utf-8"))

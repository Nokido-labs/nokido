"""NR -- 7/11 : une instance OpenCode dont le principal est Ollama Cloud n'est pas candidate au repli quand le registre
partage marque OLLAMA_CLOUD epuise (quota mensuel) et qu'aucun repli n'est disponible. Cause des reaffectations
MISTRAL du 7/11 : voir rendu_reaffectation_mistral_20261107.md (harness vivant, pas endormi)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    sys.path.insert(0, str(_p))

import forge_task_executor as T  # noqa: E402


def _inst(monkeypatch, cfg, indispo):
    monkeypatch.setattr(T, "_instances_opencode", lambda: {"OPENCODE_X": cfg})
    monkeypatch.setattr(T, "_modele_hors_quota", lambda f, m, *a, **k: None)
    monkeypatch.setattr(T, "surface_est_indisponible",
                        lambda a, *x, **k: "mensuel" if (indispo and a == "OLLAMA_CLOUD") else None)


def test_principal_ollama_cloud_epuise_au_registre_sans_repli(monkeypatch):
    _inst(monkeypatch, {"modele": "ollama_cloud/glm-4.6"}, True)
    assert T._opencode_hors_quota("OPENCODE_X")


def test_principal_ollama_cloud_sain_reste_eligible(monkeypatch):
    _inst(monkeypatch, {"modele": "ollama_cloud/glm-4.6"}, False)
    assert T._opencode_hors_quota("OPENCODE_X") is None


def test_ollama_local_non_disqualifie_quand_cloud_epuise(monkeypatch):
    _inst(monkeypatch, {"modele": "ollama/qwen3:8b"}, True)
    assert T._opencode_hors_quota("OPENCODE_X") is None


def test_effet_vide_n_est_pas_un_succes():
    assert T._statut_livraison(True, "") == "A_REVOIR"
    assert T._statut_livraison(True, "   ") == "A_REVOIR"


def test_effet_compteurs_illisibles_n_est_pas_un_succes():
    assert T._statut_livraison(True, "commits produits : ILLISIBLE (x) ; fichiers non commites : 0") == "A_REVOIR"


def test_reponse_texte_pure_reste_succes():
    assert T._statut_livraison(True, "Voici la reponse : 42.") == "SUCCESS"


def test_autre_fournisseur_inchange(monkeypatch):
    _inst(monkeypatch, {"modele": "zai/glm-4.5-flash", "repli_ollama_cloud": "gpt-oss:20b"}, True)
    assert T._opencode_hors_quota("OPENCODE_X") is None

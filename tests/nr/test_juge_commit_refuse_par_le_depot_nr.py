"""NR -- un commit d'executeur REFUSE par le depot (hook pre-commit, gate qualite) n'est pas une livraison reussie.

Mesure 24/10 : le worktree claude_headless etait bloque par le gate qualite du pre-commit (QualityGateError, pylint
< 7) depuis 19:22 ; 4 delegations CLAUDE_HEADLESS sont sorties « OK » / done avec « commits produits : 0 » et 31 a 40
fichiers non commites. Le juge ne nommait que le refus du SCORECARD (test_juge_scorecard_refuse_nr) ; le pointer_ref de
la reponse exemptait _non_livre. Un commit refuse, echoue ou impossible est un ECHEC NOMME, quel que soit le pointeur.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
EFFET = "[effet observe] commits produits : 0 (d539466bc..d539466bc) ; fichiers non commites : 31"
REPONSE = '{"intent": "OK_DONE", "pointer_ref": "tests/nr/test_capture_agy_verif_nr.py"}'


def _module(monkeypatch):
    spec = importlib.util.spec_from_file_location("juge_commit_refuse_nr", RACINE / "tools" / "forge_task_executor.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "_effet_observe", lambda workdir, avant: EFFET)
    monkeypatch.setattr(m, "_contenu_livre", lambda workdir, avant, autorises=None: None)
    monkeypatch.setattr(m, "_artefact_declare_absent", lambda reponse, workdir: None)
    monkeypatch.setattr(m, "_artefact_non_produit", lambda reponse, workdir, avant: None)
    return m


@pytest.mark.parametrize("note", [
    "commit executeur REFUSE rc=1 : [gate][quality][warn] QualityGateError: Gate failed for tools/x.py",
    "commit executeur REFUSE rc=1 (commit RED abc1234 livre, code non committe) : QualityGateError",
])
def test_un_commit_refuse_par_le_depot_n_est_pas_un_succes(monkeypatch, tmp_path, note):
    m = _module(monkeypatch)
    ok, effet, _ = m._juger_livraison(True, "%s\n[executeur] %s" % (REPONSE, note), str(tmp_path), ("d539466bc", 0))
    assert ok is False and "[COMMIT REFUSE]" in effet, effet


def test_un_commit_reussi_n_est_pas_marque(monkeypatch, tmp_path):
    m = _module(monkeypatch)
    monkeypatch.setattr(m, "_effet_observe", lambda workdir, avant: EFFET.replace("produits : 0", "produits : 1"))
    detail = "%s\n[executeur] commit executeur de 2 fichier(s) : fix(x): y" % REPONSE
    ok, effet, _ = m._juger_livraison(True, detail, str(tmp_path), ("d539466bc", 0))
    assert "[COMMIT REFUSE]" not in effet, effet

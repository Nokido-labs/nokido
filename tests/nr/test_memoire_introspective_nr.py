"""Non-regression : le rappel [memoire:introspective] sert le module du SUJET.

Defaut mesure le 2026-11-05 : a chaque tour, le rappel rendait quatre modules sans
rapport (`forge_broker_local.py - organe module_organ`). Trois causes lues dans le code :
la cle racine `module_organ` de la carte prise pour un organe (et `tally`, `provenance`
pour des listes de modules), un mot retenu des qu'il est SOUS-CHAINE du nom, et les
quatre premiers rendus dans l'ordre du fichier, sans rang.

Hermetique : carte factice, rien n'est lu du recensement reel.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[2] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import forge_memoire_active as mem  # noqa: E402


@pytest.fixture()
def carte(tmp_path, monkeypatch):
    """Pose une carte factice a l'emplacement lu par le rappel."""
    monkeypatch.setattr(mem, "SANDBOX", tmp_path)
    (tmp_path / "workspace").mkdir()

    def _poser(data):
        (tmp_path / "workspace" / "organ_map_full.json").write_text(json.dumps(data), encoding="utf-8")

    return _poser


def _forme_reelle(modules):
    return {"module_organ": modules, "tally": {"Memoire": 1}, "provenance": {"regle": "x"},
            "generated_at": "2026-11-05", "generator": "test"}


def test_organe_reel_et_racines_ignorees(carte):
    carte(_forme_reelle({"forge_memoire_active.py": "Memoire (hippocampe/RAG)"}))
    vus, _ = mem._introspective("la memoire active")
    assert len(vus) == 1
    assert "organe Memoire (hippocampe/RAG)" in repr(vus[0])
    assert "module_organ" not in repr(vus)


def test_cles_de_recensement_ne_sont_pas_des_modules(carte):
    carte({"module_organ": {"forge_x.py": "Infra"}, "tally": {"Memoire": 1}, "provenance": {"regle": "x"}})
    vus, _ = mem._introspective("Memoire regle provenance")
    assert vus == []


def test_sous_chaine_ne_suffit_plus(carte):
    carte(_forme_reelle({"forge_marchepied.py": "Infra", "forge_eventbus_replay.py": "Infra"}))
    vus, note = mem._introspective("comment marche event")
    assert vus == []
    assert note


def test_mot_commun_a_trop_de_modules_ne_designe_rien(carte):
    carte(_forme_reelle({f"forge_truc{i}_local.py": "Infra" for i in range(40)}))
    vus, note = mem._introspective("le modele local")
    assert vus == []
    assert note


def test_rang_independant_de_l_ordre_du_fichier(carte):
    modules = {"forge_budget_divers.py": "Infra", "forge_autre_chose.py": "Infra",
               "forge_budget_volume.py": "Immunite"}
    carte(_forme_reelle(modules))
    vus, _ = mem._introspective("le budget de volume")
    assert "forge_budget_volume.py" in repr(vus[0])
    assert "forge_budget_divers.py" in repr(vus[1])
    assert "forge_autre_chose" not in repr(vus)


def test_module_nomme_passe_en_tete_meme_si_ses_mots_sont_communs(carte):
    modules = {f"forge_truc{i}_local.py": "Infra" for i in range(40)}
    modules["forge_cible_local.py"] = "SNC"
    carte(_forme_reelle(modules))
    vus, _ = mem._introspective("regarde forge_truc7_local.py puis le local")
    assert "forge_truc7_local.py" in repr(vus[0])


def test_accents_et_pluriels_rejoignent_le_nom_du_module(carte):
    carte(_forme_reelle({"forge_memoire_active.py": "Memoire", "forge_garde_tokens.py": "Immunite"}))
    vus, _ = mem._introspective("la mémoire et les gardes")
    texte = repr(vus)
    assert "forge_memoire_active.py" in texte
    assert "forge_garde_tokens.py" in texte


def test_limite_respectee(carte):
    carte(_forme_reelle({f"forge_budget_m{i}.py": "Infra" for i in range(6)}))
    vus, _ = mem._introspective("budget", limit=4)
    assert len(vus) == 4


@pytest.mark.parametrize("forme", [
    {"Memoire": ["forge_budget_volume.py"]},
    [{"organe": "Memoire", "module": "forge_budget_volume.py"}],
])
def test_formes_anciennes_toujours_lues(carte, forme):
    carte(forme)
    vus, _ = mem._introspective("le budget de volume")
    assert len(vus) == 1
    assert "organe Memoire" in repr(vus[0])


@pytest.mark.parametrize("prompt", [
    "<task-notification>\n<task-id>x</task-id>\n<summary>Monitor stream ended</summary></task-notification>",
    "[SYSTEM NOTIFICATION - NOT USER INPUT]\nThis is an automated background-task event",
    "<system-reminder>\n[SYSTEM NOTIFICATION - NOT USER INPUT]\n</system-reminder>\n<task-notification>",
])
def test_notification_systeme_n_est_pas_une_intention(monkeypatch, prompt):
    """Mesure du 2026-11-05 : le hook prenait la notification pour le sujet du tour."""
    outils = str(Path(__file__).resolve().parents[2] / "tools")
    if outils not in sys.path:
        sys.path.insert(0, outils)
    import claude_inbox_tick as tick

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": prompt, "session_id": "s"})))
    assert tick._intention() == ""
    assert tick._PROMPT == ""


def test_demande_de_l_owner_reste_une_intention(monkeypatch):
    outils = str(Path(__file__).resolve().parents[2] / "tools")
    if outils not in sys.path:
        sys.path.insert(0, outils)
    import claude_inbox_tick as tick

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": "et le débat ?", "session_id": "s"})))
    assert tick._intention() == "et le débat ?"
    assert tick._PROMPT == "et le débat ?"


def test_carte_absente_se_declare(tmp_path, monkeypatch):
    monkeypatch.setattr(mem, "SANDBOX", tmp_path)
    vus, note = mem._introspective("budget")
    assert vus == []
    assert "illisible" in note

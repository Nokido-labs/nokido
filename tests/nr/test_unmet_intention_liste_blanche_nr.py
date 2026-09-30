"""NR -- le capteur d'intentions non tenues ne lit que les DOCS D'INTENTION (liste blanche).

MESURE 2026-09-25 (P1, re-examen du tri) : 105 « ecarts doc/code » confirmes venaient de 53 sources,
en majorite PAS des docs d'intention -- un journal de conversation archive `.aider.chat.history.md`,
une liste de candidats de propriete intellectuelle, des SKILL.md, des notes `memory/`. Le capteur
parcourait TOUS les `.md` et n'en ecartait que quelques-uns (archive, wiki, launch) : une liste NOIRE,
ou tout fichier inattendu tombe du cote « intention ». Une MENTION n'est pas une intention.

Sa propre docstring (doctrine owner du 22/08) nomme ce qu'est un doc d'intention : MANIFESTO, specs/,
roadmap, plan. On le lit par liste BLANCHE ; le reste est ecarte et le NOMBRE ecarte est dit. Sur le
depot : 33 docs d'intention suivis pour 633 `.md`.

Noms de modules neutres a dessein : ce test ne recopie aucune liste produite par le capteur.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

DOCS = {
    # docs d'intention : leurs modules absents SONT des intentions non tenues
    "MANIFESTO.md": "forge_absent_manifeste.py",
    "docs/specs/orchestrateur_spec.md": "forge_absent_spec.py",
    "docs/roadmap_flotte.md": "forge_absent_roadmap.py",
    "docs/PLAN_REFACTO.md": "forge_absent_plan_prefixe.py",
    "docs/portail_plan.md": "forge_absent_plan_suffixe.py",
    # mentions : jamais des intentions
    ".aider.chat.history.md": "forge_absent_journal.py",
    "docs/ip/IP_TRIAGE_CANDIDATS.md": "forge_absent_triage.py",
    "docs/skills/nokido/SKILL.md": "forge_absent_skill.py",
    "memory/roadmap_note_de_session.md": "forge_absent_note.py",
    "docs/CLAUDE_PLANNING_MODE.md": "forge_absent_planning.py",
    "docs/archive/ancien_PLAN.md": "forge_absent_archive.py",
    "docs/COMMUNICATIONS.md": "forge_absent_comm.py",
}
INTENTIONS = {"forge_absent_manifeste.py", "forge_absent_spec.py", "forge_absent_roadmap.py",
              "forge_absent_plan_prefixe.py", "forge_absent_plan_suffixe.py"}


@pytest.fixture
def AL(tmp_path, monkeypatch):
    m = importlib.import_module("forge_autonomous_loops")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "forge_present.py").write_text("x = 1\n", encoding="utf-8")
    for rel, module in DOCS.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"Cible : `{module}` et `app/forge_present.py`.\n", encoding="utf-8")
    monkeypatch.setattr(m, "ROOT", tmp_path)
    monkeypatch.setattr(m, "_ABSENTS_CACHE", {})  # cache 60 s partage : jamais celui d'un autre test
    return m


def test_seuls_les_docs_d_intention_produisent_une_intention(AL):
    trouves = {e["module"] for e in AL._modules_absents_des_docs()}
    assert trouves == INTENTIONS


def test_un_module_present_n_est_jamais_une_intention(AL):
    assert "forge_present.py" not in {e["module"] for e in AL._modules_absents_des_docs()}


def test_une_ancienne_experience_nee_d_une_mention_n_est_pas_resolue(AL):
    # Les ~105 experiences ouvertes par l'ancienne liste noire : leur module n'est plus retenu, mais
    # RIEN n'a ete resolu -- elles n'etaient pas des intentions. RESOLU serait un faux calme.
    lot = [{"target_module": "forge_absent_journal.py", "source_doc": ".aider.chat.history.md"},
           {"target_module": "forge_absent_triage.py", "source_doc": "docs/ip/IP_TRIAGE_CANDIDATS.md"}]
    r = AL._reexaminer("unmet_intention", lot)
    assert r["verdict"] == "MENTION_HORS_INTENTION"
    assert set(r["par_cible"].values()) == {"MENTION_HORS_INTENTION"}


def test_une_intention_reelle_reste_a_traiter(AL):
    r = AL._reexaminer("unmet_intention", [{"target_module": "forge_absent_spec.py",
                                             "source_doc": "docs/specs/orchestrateur_spec.md"}])
    assert r["verdict"] == "A_TRAITER"


@pytest.mark.parametrize("chemin, attendu", [
    ("MANIFESTO.md", True),
    ("docs/specs/x.md", True),
    ("docs/ROADMAP_GLOBALE_2026-09-06.md", True),
    ("docs/roadmap_plan_cognitif_2026-09-13.md", True),
    ("docs/nokido_hybrid_architecture_plan.md", True),
    ("docs/CLAUDE_PLANNING_MODE.md", False),        # « planning » n'est pas le MOT plan
    ("docs/SPRINT_FUTUR_PLANNER_LOCAL.md", False),
    (".aider.chat.history.md", False),
    ("docs/ip/IP_TRIAGE_CANDIDATS.md", False),
    ("memory/roadmap_centralisation_clients_2026-06-12.md", False),  # note de session
    ("docs/wiki/03-Architecture_plan.md", False),
    ("docs/passation_plan.md", False),
    ("docs/specs/notes.txt", False),
])
def test_la_liste_blanche(AL, chemin, attendu):
    assert AL._est_doc_d_intention(chemin) is attendu

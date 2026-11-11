"""NR étape 2 (owner 9/11, Nokido orchestrateur). Mesure : `job_e98ab2cf` (OPENCODE_GLM) a livré avec
« repli sur le modele par defaut » -- ce n'était pas GLM -- et sans contexte servi : 2 fichiers altérés, statut done.

Contrat : `forge_task_executor.garde_livraison_contexte(desc, consigne_servie, rendu, modele_demande) -> (ok, cause)`,
appelée par `_juger_livraison` ; une livraison n'est jamais acceptée sur un repli de modèle non déclaré ni quand des
documents cités n'ont pas été servis. Causes nommées, jamais un refus muet.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as FE  # noqa: E402

DESC_DOC = "Copie sandbox/workspace/archives/rapport_x.md vers docs/."
SERVIE = DESC_DOC + "\n[CONTEXTE SERVI par Nokido]\n[source: fichier sha256:abc car 0-10/10]\n..."


def test_repli_de_modele_non_declare_refuse():
    ok, cause = FE.garde_livraison_contexte(DESC_DOC, SERVIE, "rendu : [repli sur le modele par defaut] fait", "glm-4.6")
    assert ok is False and cause == "MODELE_REPLI_NON_DECLARE"


def test_documents_cites_non_servis_refuse(tmp_path, monkeypatch):
    monkeypatch.setattr(FE, "ROOT", tmp_path)
    doc = tmp_path / "sandbox" / "workspace" / "archives" / "rapport_x.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("contenu a servir", encoding="utf-8")
    ok, cause = FE.garde_livraison_contexte(DESC_DOC, DESC_DOC, "fait", "glm-4.6")
    assert ok is False and cause == "CONTEXTE_NON_SERVI"


def test_livraison_conforme_acceptee():
    assert FE.garde_livraison_contexte(DESC_DOC, SERVIE, "fait", "glm-4.6") == (True, "")


def test_sans_document_ni_modele_demande_neutre():
    assert FE.garde_livraison_contexte("Corrige tools/x.py fonction f.", "Corrige tools/x.py fonction f.", "fait", "") == (True, "")


def test_document_a_produire_n_exige_pas_d_etre_servi(tmp_path, monkeypatch):
    """9/11 relecture : « RENDU : creer docs/enquetes/x.md » cite un document qui n'existe pas encore -- rien a
    servir, la livraison ne doit pas etre refusee pour CONTEXTE_NON_SERVI (sinon toute tache de rapport echoue)."""
    monkeypatch.setattr(FE, "ROOT", tmp_path)
    desc = "Enquete. RENDU : creer docs/enquetes/x_inexistant_20261109.md (tableau)."
    assert FE.garde_livraison_contexte(desc, desc, "fait", "glm-4.6") == (True, "")


def test_branche_dans_le_juge_commun():
    src = (ROOT / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
    debut = src.index("def _juger_livraison(")
    fin = src.index("\ndef ", debut + 10)
    assert "garde_livraison_contexte(" in src[debut:fin]

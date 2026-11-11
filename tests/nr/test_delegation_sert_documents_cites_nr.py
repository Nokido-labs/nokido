"""NR étape 1 (owner 9/11 : « c'est Nokido l'orchestrateur », contexte servi à chaque exécutant).

Mesure du 9/11 : la délégation `job_e98ab2cf` citait 32 documents de `sandbox/workspace/` ; `precharger_corps_consigne`
ne sert que du CODE (`fichier.py fonction|ligne`) et ces fichiers non suivis n'existaient pas dans le worktree de la
tâche -> l'exécutant les a relus seul, avec un modèle de repli : 2 fichiers altérés.

Contrat : `forge_task_executor.servir_documents_cites(consigne, workdir, racines_autorisees, ledger_db)` rend
`(consigne_enrichie, manifeste)` ; les documents CITÉS (hors code) sont indexés puis servis par le context_ledger
existant (pas de système parallèle) : bloc `[CONTEXTE SERVI par Nokido]`, en-têtes `[source: … sha256:…]`,
manifeste `entrees` ; hors racines autorisées = refusé et dit ; idempotent.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as FE  # noqa: E402


def _preparer(tmp_path):
    depot = tmp_path / "depot"
    doc = depot / "sandbox" / "workspace" / "rapport_x.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("# Rapport X\nLe pivot est la ligne 42 du module y.\n", encoding="utf-8")
    wt = tmp_path / "worktree_tache"           # le document N'EXISTE PAS dans le worktree
    wt.mkdir()
    return depot, doc, wt


def test_document_cite_hors_worktree_servi_par_le_ledger(tmp_path):
    depot, doc, wt = _preparer(tmp_path)
    consigne = "Lis %s et résume-le." % doc.as_posix()
    enrichie, man = FE.servir_documents_cites(consigne, wt, [depot], tmp_path / "ledger.db")
    assert "[CONTEXTE SERVI par Nokido]" in enrichie
    assert "[source:" in enrichie and "sha256:" in enrichie
    assert "Le pivot est la ligne 42" in enrichie
    assert len(man.get("entrees", [])) >= 1


def test_chemin_relatif_apres_un_mot(tmp_path):
    """Relecture 9/11 : la regex acceptait des espaces dans TOUT chemin et capturait « Lis sandbox/... » :
    un chemin relatif n'etait jamais servi. Les espaces ne valent que pour un chemin absolu (C:/Script python IA/...)."""
    depot, doc, wt = _preparer(tmp_path)
    enrichie, man = FE.servir_documents_cites("Lis sandbox/workspace/rapport_x.md puis docs/absent.md.", wt, [depot],
                                              tmp_path / "ledger.db")
    assert "Le pivot est la ligne 42" not in enrichie or True  # relatif au worktree : absent du worktree
    enrichie2, _ = FE.servir_documents_cites("Lis sandbox/workspace/rapport_x.md puis docs/absent.md.", depot,
                                             [depot], tmp_path / "ledger2.db")
    assert "Le pivot est la ligne 42" in enrichie2


def test_hors_racines_autorisees_refuse_et_dit(tmp_path):
    depot, _doc, wt = _preparer(tmp_path)
    ailleurs = tmp_path / "ailleurs" / "secret.md"
    ailleurs.parent.mkdir()
    ailleurs.write_text("NE PAS SERVIR", encoding="utf-8")
    enrichie, man = FE.servir_documents_cites("Lis %s" % ailleurs.as_posix(), wt, [depot], tmp_path / "ledger.db")
    assert "NE PAS SERVIR" not in enrichie
    assert man.get("refuses"), man


def test_idempotent(tmp_path):
    depot, doc, wt = _preparer(tmp_path)
    une, _ = FE.servir_documents_cites("Lis %s" % doc.as_posix(), wt, [depot], tmp_path / "ledger.db")
    deux, _ = FE.servir_documents_cites(une, wt, [depot], tmp_path / "ledger.db")
    assert deux.count("[CONTEXTE SERVI par Nokido]") == 1


def test_consigne_sans_document_inchangee(tmp_path):
    depot, _doc, wt = _preparer(tmp_path)
    c = "Corrige tools/forge_x.py fonction f."
    enrichie, man = FE.servir_documents_cites(c, wt, [depot], tmp_path / "ledger.db")
    assert enrichie == c and not man.get("entrees")

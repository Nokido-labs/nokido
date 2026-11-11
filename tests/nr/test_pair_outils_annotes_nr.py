"""NR 3/11 — chaque outil du connecteur des pairs porte `title` et ses indications (MCP ToolAnnotations).

Mesure du 3/11 : 0/14 outils annotes. Exigence du repertoire Anthropic (claude_docs:claude.com/docs/connectors/
building/review-criteria.md, submission.md) : « Every tool must include a `title` and the applicable hint » ; ces
indications pilotent les permissions automatiques de Claude (lecture seule = sans confirmation a chaque appel).
Dossier : docs/DOSSIER_REPERTOIRE_ANTHROPIC.md.
"""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

P = pytest.importorskip("forge_pair_mcp")

LECTURE = {"etat_corps", "point_ssot", "recherche_rag", "journal_commits", "derniere_capsule", "lire_document",
           "suivre", "lire_reponses", "lire_annexe", "lire_vivant"}
DEPOTS = {"proposer_fait", "deposer_fragment", "envoyer_message", "soumettre_tache"}


def _outils(oauth=False):
    return asyncio.run(P.construire_serveur(oauth=oauth).list_tools())


def test_la_table_couvre_les_14_outils_et_eux_seuls():
    assert set(P.ANNOTATIONS_OUTILS) == LECTURE | DEPOTS


def test_chaque_outil_expose_a_un_titre_et_ses_indications():
    outils = _outils()
    assert outils, "aucun outil expose"
    for t in outils:
        a = t.annotations
        assert t.title and a is not None and a.title == t.title, t.name
        assert a.readOnlyHint is (t.name in LECTURE), t.name
        assert a.openWorldHint is False, t.name
        if t.name in DEPOTS:
            # depot ADDITIF (rien d'efface, rien d'ecrase) : non destructif, mais jamais lecture seule
            assert a.destructiveHint is False, t.name
        assert len(t.name) <= 64


def test_un_outil_sans_annotation_casse_la_construction(monkeypatch):
    table = dict(P.ANNOTATIONS_OUTILS)
    table.pop("etat_corps")
    monkeypatch.setattr(P, "ANNOTATIONS_OUTILS", table)
    with pytest.raises(KeyError):
        P.construire_serveur(oauth=False)

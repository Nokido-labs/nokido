# -*- coding: utf-8 -*-
"""NR — les fiches memoire entrent dans un palier VECTORISABLE, et rien d'autre.

Contexte mesure le 2026-09-04 : 776 fiches, 73 citees par l'index, ~700
atteignables par rien. La jonction les a rendues LISIBLES ; l'ingestion les rend
RETROUVABLES. Sans elle, la jonction n'aurait fait que deplacer le probleme.

Le point unique qui decide de tout est le DOMAINE. `forge_tier_guard` refuse par
RAISE(IGNORE) la vectorisation des paliers froids ; le palier se deduit de
(source, domain). Avec un mauvais domaine, les 2 465 chunks partaient en
REFUSED_BY_POLICY : presents, jamais vectorises, et personne ne l'aurait vu —
c'est exactement la confusion qui faisait annoncer 736 272 chunks « en dette »
la ou 109 053 attendaient vraiment.

Proprietes gardees :

1. Le domaine choisi mene bien au palier `laforge-memory`, qui est vectorisable.
2. L'ingesteur ne reimplemente NI le chunking NI l'ecriture : il delegue au
   pipeline canonique. Toute logique dupliquee ici serait une seconde verite.
3. Le plan de deduplication est VERIFIE avant une passe de masse — sans l'index
   d'expression, 776 documents lisent 24,9 Go chacun, soit ~19 To.
4. Le dry-run est le defaut.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))

import forge_memory_ingest as ing  # noqa: E402
from forge_memory_availability import VECTORISABLES, tier  # noqa: E402


def test_le_domaine_choisi_est_vectorisable():
    """PROPRIETE 1 : sans ce palier, tout part en REFUSED_BY_POLICY.

    On interroge `tier()`, qui est un miroir VERIFIE du CASE du trigger — pas
    une liste recopiee a la main.
    """
    palier = tier("memory:une_fiche", ing.DOMAINE)
    assert palier == "laforge-memory", (
        "domaine %r -> palier %r : les fiches seraient refusees par forge_tier_guard"
        % (ing.DOMAINE, palier))
    assert palier in VECTORISABLES


def test_un_mauvais_domaine_serait_refuse():
    """Contre-epreuve : la propriete precedente doit pouvoir echouer.

    Un test qui passe quel que soit le domaine ne mesure rien.
    """
    assert tier("memory:x", "gitingest") not in VECTORISABLES
    assert tier("memory:x", "longmemeval") not in VECTORISABLES


def test_l_ingesteur_delegue_au_pipeline_canonique():
    """PROPRIETE 2 : aucun chunking ni INSERT maison."""
    source = (ROOT / "tools" / "forge_memory_ingest.py").read_text(encoding="utf-8")
    assert "from nokido_agent.app.forge_ingest_pipeline import" in source, "le pipeline canonique n'est pas utilise"
    assert "process_document" in source and "store_chunks" in source
    code = "\n".join(l for l in source.splitlines() if not l.lstrip().startswith("#"))
    assert "INSERT INTO rag_chunks" not in code.upper(), "ecriture directe en base"
    assert "def chunk" not in code, "chunking reimplemente au lieu d'etre delegue"


def test_le_plan_de_dedup_est_verifie_avant_la_masse():
    """PROPRIETE 3 : une passe de 776 documents ne part pas a l'aveugle.

    `store_chunks` deduplique par une EXPRESSION json_extract. Sans l'index
    d'expression, le plan est un SCAN de 24,9 Go — par document.
    """
    source = (ROOT / "tools" / "forge_memory_ingest.py").read_text(encoding="utf-8")
    corps = source[source.find("def ingerer("):]
    i_plan = corps.find("_verifier_le_plan")
    i_boucle = corps.find("for i, f in enumerate")
    assert i_plan > 0, "aucune verification du plan de dedup"
    assert i_boucle > 0
    assert i_plan < i_boucle, "le plan est verifie APRES l'ingestion : trop tard"
    assert "return 3" in corps, "un plan en SCAN doit interrompre, pas avertir"


def test_le_dry_run_est_le_defaut():
    source = (ROOT / "tools" / "forge_memory_ingest.py").read_text(encoding="utf-8")
    assert "def ingerer(appliquer: bool = False" in source
    assert '"--appliquer"' in source


def test_le_resume_de_la_fiche_alimente_le_prefixe():
    """La description du frontmatter devient le `doc_summary` de chaque chunk.

    Sans elle, un chunk pris au milieu d'une fiche est un paragraphe sans
    adresse — mesure du 03/09 : le prefixe contextuel ne couvrait que 6,7 % du
    code, la ou il sert le plus.
    """
    source = (ROOT / "tools" / "forge_memory_ingest.py").read_text(encoding="utf-8")
    assert "doc_summary=resume" in source, "le resume n'alimente pas le prefixe contextuel"
    front = ing._frontmatter('---\nname: x\ndescription: "un resume"\n---\ncorps\n')
    assert front.get("description") == "un resume"


def test_frontmatter_absent_ne_casse_rien():
    """Les fiches les plus anciennes n'ont pas de frontmatter — et ce sont
    justement celles que personne ne retrouve. Les exiger les exclurait."""
    assert ing._frontmatter("pas de frontmatter du tout") == {}

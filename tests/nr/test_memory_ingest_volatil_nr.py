# -*- coding: utf-8 -*-
"""NR — le chemin VOLATIL de l'ingestion memoire.

MEMORY.md et les index thematiques sont REGENERES a chaque compaction. Les
faire passer par le chemin ordinaire empile des versions et fait servir du
perime par le lexical. Ces tests figent les trois decisions qui l'empechent,
chacune payee par une mesure du 2026-09-04.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))

mi = pytest.importorskip("forge_memory_ingest")


class _Chunk:
    """Substitut minimal de RefinedChunk (le pipeline reel n'est pas requis ici)."""

    def __init__(self, texte: str) -> None:
        self.id = "rp_ancien"
        self.text = texte
        self.meta: dict = {}


def test_TOUTE_fiche_memoire_est_revisable():
    """Le contrat a change le 2026-09-04, quelques heures apres sa premiere version.

    Le chemin volatil avait d'abord ete reserve a `MEMORY.md` et aux index, au
    motif qu'eux seuls sont « regeneres ». La preuve du contraire est venue le
    jour meme : une fiche corrigee (« CI rouge » -> « [RESOLU] ») reingeree a
    rendu « 0 chunks ecrits, deja presentes » — la correction n'entrait pas, et
    le lexical continuait de servir l'etat revolu.

    Corriger une fiche n'est pas l'exception : c'est la consigne owner du 12/08
    (« rien n'est supprime, on marque [PERIME]/[RESOLU] »). Toute fiche est donc
    revisable, et toutes passent par le chemin qui REMPLACE.
    """
    assert mi._est_volatil("MEMORY.md")
    assert mi._est_volatil("index_reflexes_et_doctrine.md")
    assert mi._est_volatil("gotcha_quelque_chose_2026-09-04.md")
    assert not mi._est_volatil("MEMORY.md.bak")


def test_l_id_volatil_ne_depend_QUE_de_la_position():
    """Le defaut repare : l'id du pipeline vaut md5(source:i:texte[:50]).

    Inserer une ligne EN TETE de l'index decale tous les `i` ET les 50 premiers
    caracteres de chaque chunk : tous les ids changent, donc INSERT OR REPLACE
    n'ecrase rien et l'ancienne version SURVIT a cote de la neuve.
    """
    src = "memory:MEMORY"
    v1 = mi._stabiliser([_Chunk("texte tout a fait initial"), _Chunk("second bloc")], src)
    ids_v1 = [c.id for c in v1]
    # Meme source, memes positions, contenus ENTIEREMENT differents.
    v2 = mi._stabiliser([_Chunk("contenu integralement reecrit"), _Chunk("autre chose")], src)
    assert [c.id for c in v2] == ids_v1, "un id volatil doit dependre de la position seule"
    # Une source differente ne doit pas collisionner.
    autre = mi._stabiliser([_Chunk("texte tout a fait initial")], "memory:index_x")
    assert autre[0].id != ids_v1[0]


def test_l_empreinte_volatile_couvre_le_texte_ENTIER():
    """Second defaut : `_text_fingerprint` ne hache que les 200 PREMIERS chars.

    Un chunk dont seul le corps change garde son empreinte, donc la dedup le
    SAUTE : le lexical sert l'ancienne version en croyant s'etre mis a jour.
    Meme famille que `INSERT OR IGNORE INTO rag_fts`, deja paye.
    """
    tete = "T" * 250  # au-dela des 200 caracteres regardes par le pipeline
    a = mi._stabiliser([_Chunk(tete + "corps ORIGINAL")], "memory:MEMORY")[0]
    b = mi._stabiliser([_Chunk(tete + "corps MODIFIE")], "memory:MEMORY")[0]
    assert a.meta["fingerprint"] != b.meta["fingerprint"], (
        "une modification hors des 200 premiers caracteres doit changer l'empreinte"
    )
    # et l'empreinte est bien celle du texte complet
    attendu = hashlib.md5((tete + "corps MODIFIE").encode("utf-8")).hexdigest()
    assert b.meta["fingerprint"] == attendu


def test_le_superseding_n_indexe_PAS_sur_une_colonne_constante():
    """Garde executable sur le piege de planification mesure ce jour.

    `active` vaut 1 pour les 2 035 609 lignes. Mettre `active = 1` dans le WHERE
    fait choisir `idx_rag_chunks_active` a SQLite — un index sans aucun pouvoir
    discriminant, qui EVINCE `idx_rag_source`. Mesure : 14,716 s contre 0,000 s
    pour les 16 memes lignes.

    Le piege est qu'un plan `SEARCH ... USING INDEX` a l'air sain : il dit
    « USING INDEX » et balaie quand meme toute la table.
    """
    src = Path(mi.__file__).read_text(encoding="utf-8", errors="replace")
    corps = src.split("def _superseder_les_anciens", 1)
    assert len(corps) == 2, "fonction de superseding introuvable"
    corps = corps[1].split("\ndef ", 1)[0]
    # On ne regarde que le SQL, pas les commentaires qui CITENT le motif
    # (un detecteur qui se lit lui-meme, defaut deja paye trois fois le 04/09).
    sql = "\n".join(
        l for l in corps.splitlines()
        if not l.lstrip().startswith("#") and "SELECT" in l or "WHERE" in l and not l.lstrip().startswith("#")
    )
    assert not re.search(r"WHERE[^\"]*active\s*=\s*1", sql), (
        "filtrer active=1 en SQL detourne le planificateur vers un index constant"
    )
    assert "WHERE source = ?" in corps, "le filtre doit porter sur la colonne qui SELECTIONNE"


def test_le_retrait_du_lexical_accompagne_la_desactivation():
    """Marquer `active=0` ne suffit PAS a retirer un chunk du lexical.

    Le trigger `rag_chunks_fts_au` ne se declenche que sur
    UPDATE OF text, source, domain — pas sur `active`. Un chunk desactive
    resterait donc CHERCHABLE. La desactivation doit etre accompagnee du verbe
    'delete' de FTS5 external-content.
    """
    corps = Path(mi.__file__).read_text(encoding="utf-8", errors="replace")
    corps = corps.split("def _superseder_les_anciens", 1)[1].split("\ndef ", 1)[0]
    assert "'delete'" in corps, "le retrait du FTS manque : le perime resterait cherchable"
    assert "active = 0" in corps, "la desactivation doit rester tracee (rien n'est supprime)"
    assert "superseded_by" in corps, "un chunk desactive doit nommer ce qui le remplace"


def test_l_index_et_les_moc_sont_INCLUS_dans_la_collecte():
    """MEMORY.md etait exclu ('index, pas fiche') : il n'etait servi par rien."""
    corps = Path(mi.__file__).read_text(encoding="utf-8", errors="replace")
    assert 'if f.name != "MEMORY.md"' not in corps, "MEMORY.md ne doit plus etre exclu"
    assert 'FICHES.glob("*.md")' in corps

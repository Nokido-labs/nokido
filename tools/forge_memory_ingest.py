#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_memory_ingest.py — les fiches memoire entrent dans l'hippocampe.

Suite de `forge_memory_junction.py` : la jonction a rendu les 776 fiches
LISIBLES par le corps, ce script les rend RETROUVABLES. Sans lui la jonction
n'aurait fait que deplacer un probleme d'un dossier a l'autre — 73 fiches
citees par l'index, ~700 atteignables par rien.

## Ce module n'invente aucun pipeline

Tout existe deja et fait mieux qu'un ingesteur maison :

    forge_ingest_pipeline.process_document   chunking semantique, prefixe
                                             contextuel, empreinte, role_hint
    forge_ingest_pipeline.store_chunks       ecriture GOUVERNEE (open_writer)

Ce fichier n'est qu'un ADAPTATEUR DE SOURCE : il lit les fiches, en tire un
resume, et appelle le pipeline. Toute logique de chunking ou d'ecriture ecrite
ici serait une seconde verite a maintenir.

## Le palier, qui decide de tout

`forge_tier_guard` refuse par RAISE(IGNORE) la vectorisation des paliers froids.
Le palier se deduit de (source, domain) — copie fidele dans
`forge_memory_availability.tier` :

    domain in ("autonomous", "episodic_memory", "longterm_memory", "rag")
        -> "laforge-memory"  ->  VECTORISABLE

D'ou `domain_hint="episodic_memory"`. Avec un autre domaine les fiches seraient
ingerees puis REFUSED_BY_POLICY : presentes en lexical, invisibles au vectoriel,
et personne ne l'aurait vu — c'est exactement la confusion qui a fait annoncer
736 272 chunks « en dette » ce matin la ou 109 053 attendaient vraiment.

## Pourquoi c'est sur de lancer sur 776 documents

`store_chunks` deduplique par `json_extract(meta,'$.fingerprint')`. Cette
expression etait NON INDEXABLE — un balayage de 24,9 Go PAR DOCUMENT, soit
~19 To pour cette passe. L'index d'expression `idx_rag_fingerprint` a depuis ete
pose, et le plan le confirme :

    SEARCH rag_chunks USING INDEX idx_rag_fingerprint (<expr>=?)

VERIFIER CE PLAN avant toute ingestion de masse : c'est la difference entre
quelques minutes et un incident.

Usage :  LAFORGE_PYTHON tools/forge_memory_ingest.py [--appliquer] [--limite N]
"""
from __future__ import annotations

__FORGE_COLOR__ = "memoire/hippocampe"

import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FICHES = ROOT / "memory"
sys.path.insert(0, str(ROOT))

# Palier vectorisable — cf. forge_memory_availability.VECTORISABLES.
DOMAINE = "episodic_memory"

# --- Sources VOLATILES : regenerees, pas ecrites une fois -------------------
# MEMORY.md et les index thematiques sont reecrits a chaque compaction. Les
# ingerer par le chemin ordinaire EMPILE des versions, pour deux raisons
# mesurees dans forge_ingest_pipeline :
#
#   1. l'id vaut md5("{source}:{i}:{chunk_text[:50]}") — inserer une ligne EN
#      TETE decale tous les `i`, donc tous les ids changent, donc
#      INSERT OR REPLACE n'ecrase rien et l'ancienne version SURVIT ;
#   2. la dedup compare `_text_fingerprint` = md5 des 200 PREMIERS caracteres.
#      Un chunk dont seul le CORPS change garde son empreinte : il est SAUTE.
#      Le lexical sert alors l'ancienne version en croyant s'etre mis a jour —
#      exactement le defaut deja paye sur `INSERT OR IGNORE INTO rag_fts`.
#
# Remede LOCAL a cet adaptateur (ne pas toucher au pipeline partage) :
# id derive de la POSITION seule, empreinte sur le texte ENTIER. Le trigger
# `rag_chunks_fts_bi` supprime alors du FTS l'entree `id = new.id` avant de
# reinserer — le lexical suit sans orphelin.
# Mesure 2026-09-04, APRES coup : le chemin volatil avait ete reserve a
# `MEMORY.md` et aux index, au motif qu'eux seuls sont « regeneres ». C'est
# FAUX pour le corpus memoire, et la preuve est venue le jour meme — une fiche
# corrigee (« CI rouge » -> « [RESOLU] ») a ete reingeree et le pipeline a rendu
# « 0 chunks ecrits, deja presentes » : la correction n'entrait pas, et le
# lexical continuait de servir l'etat revolu.
#
# La cause est la meme que pour l'index : `_text_fingerprint` ne hache que les
# 200 PREMIERS caracteres. Une fiche dont on corrige le CORPS garde donc son
# empreinte et se fait SAUTER. Or corriger une fiche n'est pas l'exception,
# c'est la consigne owner du 12/08 : « rien n'est supprime, on marque [PERIME]
# / [RESOLU] avec un pointeur vers ce qui remplace ».
#
# Donc TOUTE fiche memoire est revisable, et toutes passent par ce chemin :
# id derive de la POSITION seule, empreinte sur le texte ENTIER, chunks de la
# version precedente desactives et retires du FTS.
def _est_volatil(nom: str) -> bool:
    return nom.endswith(".md")

_RX_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def _frontmatter(texte: str) -> dict:
    m = _RX_FRONT.match(texte)
    if not m:
        return {}
    champs = {}
    for ligne in m.group(1).splitlines():
        if ligne.startswith((" ", "\t")) or ":" not in ligne:
            continue
        cle, _, val = ligne.partition(":")
        champs[cle.strip()] = val.strip().strip('"').strip("'")
    m_type = re.search(r"^\s+type:\s*(\S+)", m.group(1), re.M)
    if m_type:
        champs["type"] = m_type.group(1)
    return champs


def _stabiliser(chunks, source: str) -> list:
    """Rend les chunks d'une source volatile ECRASABLES d'une version a l'autre.

    Sans cela une reecriture de l'index ajoute une couche au lieu de remplacer
    la precedente. L'historique n'est pas perdu pour autant : il vit au ledger
    (`tools/forge_memory_ledger.py`, sha chaines + contenu + recover()), qui est
    le registre autoritaire. Le RAG porte l'etat COURANT, le ledger le passe.
    """
    import hashlib

    for i, c in enumerate(chunks):
        c.id = "mem_" + hashlib.md5(("%s:%d" % (source, i)).encode()).hexdigest()[:12]
        # Empreinte sur le texte ENTIER, pas sur ses 200 premiers caracteres :
        # un corps modifie DOIT passer la dedup, sinon la mise a jour est muette.
        c.meta["fingerprint"] = hashlib.md5(c.text.encode("utf-8")).hexdigest()
        c.meta["volatil"] = True
    return chunks


def _superseder_les_anciens(source: str, ids_courants: set, conn=None) -> int:
    """Desactive tout chunk de `source` qui n'appartient PAS a la version courante.

    Couvre deux cas d'un seul geste, la ou un filtre sur l'indice de chunk n'en
    couvrait qu'un :
      - l'index RETRECIT      -> les chunks au-dela de la nouvelle longueur ;
      - la CLE d'id CHANGE    -> les anciens `rp_*` d'une ingestion precedente,
        qui sans cela cohabiteraient avec les `mem_*` et doubleraient la source.

    Rien n'est supprime (consigne owner du 12/08) : `active=0` +
    `superseded_by` nomme la source qui remplace. Mais marquer ne suffit pas —
    le trigger `rag_chunks_fts_au` ne se declenche que sur UPDATE OF
    text/source/domain, donc un chunk desactive resterait CHERCHABLE en lexical.
    On le retire donc aussi du FTS par le verbe 'delete' de FTS5
    external-content, la forme qu'emploient les triggers eux-memes.

    Rend le nombre de chunks retires, ou -1 si la primitive d'ecriture manque.

    La primitive vit desormais dans `forge_rag_truth.retirer_versions_anterieures`
    (2026-10-01), partagee avec `forge_ingest_llms_txt` : une seule regle de retrait
    pour les deux ingesteurs, pas deux qui divergent. Le plan d'execution (pas de
    `active = 1` dans le WHERE, mesure du 2026-09-04) y est documente.
    """
    try:
        from nokido_agent.app.forge_rag_truth import retirer_versions_anterieures
    except Exception as exc:
        print("   [!] forge_rag_truth indisponible (%s) — anciens NON traites" % type(exc).__name__)
        return -1
    n = retirer_versions_anterieures(source, ids_courants, conn=conn)
    if n < 0:
        print("   [!] open_writer indisponible — anciens NON traites")
    return n


def _verifier_le_plan(db_path) -> tuple:
    """Le plan de la dedup passe-t-il par l'index ? Rend (ok, plan).

    Sans ce controle, une passe de 776 documents peut relancer le balayage de
    24,9 Go par document. On ne le suppose pas : on le lit.
    """
    import sqlite3
    try:
        c = sqlite3.connect("file:%s?mode=ro" % Path(db_path).as_posix(), uri=True, timeout=20)
        q = "SELECT id FROM rag_chunks WHERE json_extract(meta,'$.fingerprint') = ? LIMIT 1"
        plan = " | ".join(r[3] for r in c.execute("EXPLAIN QUERY PLAN " + q, ("x",)))
        c.close()
    except Exception as exc:
        return None, "plan illisible : %s" % type(exc).__name__
    return ("USING INDEX" in plan and "SCAN rag_chunks" not in plan), plan


def ingerer(appliquer: bool = False, limite: int = 0, fichier: str = "") -> int:
    try:
        from nokido_agent.app.forge_ingest_pipeline import DB_PATH, process_document, store_chunks
    except Exception as exc:
        print("NO_VERDICT — pipeline d'ingestion indisponible : %s: %s" % (type(exc).__name__, exc))
        return 2

    if not FICHES.is_dir():
        print("NO_VERDICT — %s invisible. La jonction est-elle en place "
              "(tools/forge_memory_junction.py) ?" % FICHES)
        return 2

    ok_plan, plan = _verifier_le_plan(DB_PATH)
    print("plan de dedup : %s" % plan)
    if ok_plan is False:
        print("\n[!] la dedup BALAIE la table : une passe de masse lirait 24,9 Go "
              "par document. Poser l'index d'expression avant d'ingerer.")
        return 3
    if ok_plan is None:
        print("\n[!] plan non lisible — on n'ingere pas en masse sans savoir ce que ca coute.")
        return 3

    # MEMORY.md et les index thematiques sont INCLUS : l'index porte des faits
    # (les resumes de fiches) et doit se retrouver comme le reste. Il passe par
    # le chemin volatil, qui remplace au lieu d'empiler.
    fiches = sorted(FICHES.glob("*.md"))
    if fichier:
        # Ciblage explicite. Indispensable au reflexe de fin de session : le
        # compacteur reecrit MEMORY.md, il faut pouvoir reingerer CE fichier
        # seul plutot que de repasser sur 776 fiches inchangees.
        vises = [f for f in fiches if f.name == fichier]
        if not vises:
            print("NO_VERDICT — %s introuvable dans %s" % (fichier, FICHES))
            return 2
        fiches = vises
    if limite:
        fiches = fiches[:limite]
    print("fiches a ingerer : %d  (domaine=%s -> palier laforge-memory, VECTORISABLE)"
          % (len(fiches), DOMAINE))
    if not appliquer:
        print("\n[dry-run] rien n'est ecrit. Ajouter --appliquer pour ingerer.")
        for f in fiches[:5]:
            front = _frontmatter(f.read_text(encoding="utf-8", errors="replace"))
            print("   %-52s type=%-10s resume=%s"
                  % (f.name[:52], front.get("type", "?"), (front.get("description") or "")[:40]))
        return 0

    total_chunks = 0
    illisibles = []
    vides = []
    debut = time.monotonic()
    for i, f in enumerate(fiches, 1):
        try:
            texte = f.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            illisibles.append("%s (%s)" % (f.name, type(exc).__name__))
            continue
        front = _frontmatter(texte)
        # La description du frontmatter sert de `doc_summary` : c'est elle que
        # le prefixe contextuel posera en tete de CHAQUE chunk. Une fiche dont
        # les chunks portent son sujet se retrouve ; sans cela un chunk du
        # milieu est un paragraphe sans adresse.
        resume = front.get("description") or ""
        source = "memory:%s" % f.stem
        volatil = _est_volatil(f.name)
        try:
            chunks = process_document(
                texte,
                source=source,
                domain_hint=DOMAINE,
                role_hint=front.get("type") or "memory",
                author="claude",
                doc_summary=resume,
            )
            if volatil:
                chunks = _stabiliser(chunks, source)
            n = store_chunks(chunks)
            if volatil:
                retires = _superseder_les_anciens(source, {c.id for c in chunks})
                if retires > 0:
                    print("   [volatil] %s : %d chunk(s) de l'ancienne version "
                          "desactives et retires du lexical" % (f.name, retires))
        except Exception as exc:
            illisibles.append("%s (ingestion: %s)" % (f.name, type(exc).__name__))
            continue
        if not n:
            vides.append(f.name)
        total_chunks += n or 0
        if i % 100 == 0:
            print("   %d/%d fiches, %d chunks, %.0f s"
                  % (i, len(fiches), total_chunks, time.monotonic() - debut))

    print("\nfiches traitees : %d" % len(fiches))
    print("chunks ecrits   : %d" % total_chunks)
    print("deja presentes  : %d (dedup par empreinte — une seconde passe est sans effet)"
          % len(vides))
    print("illisibles      : %d %s" % (len(illisibles), illisibles[:3]))
    print("duree           : %.0f s" % (time.monotonic() - debut))
    print("\nLes chunks partent en PENDING : le palier les autorise, mais le vecteur")
    print("est pose par la chaine d'embedding, pas ici. Verifier ensuite avec")
    print("forge_memory_availability.compteurs().")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Ingere les fiches memoire dans le RAG")
    p.add_argument("--appliquer", action="store_true", help="ecrit reellement (defaut : dry-run)")
    p.add_argument("--limite", type=int, default=0, help="n'ingerer que les N premieres")
    p.add_argument("--fichier", default="", help="ne traiter que ce fichier (ex: MEMORY.md)")
    a = p.parse_args(argv)
    return ingerer(appliquer=a.appliquer, limite=a.limite, fichier=a.fichier)


if __name__ == "__main__":
    sys.exit(main())

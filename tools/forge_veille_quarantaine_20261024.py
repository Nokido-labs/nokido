"""Quarantaine des 7 chaines de veille du 24/10 (search_results_json = 0 resultat, contenu non source).

RIEN n'est supprime : biblio_raw -> status='rejected' + rejection_reason ; rag_chunks -> active=0 +
retraction_status. Chaque ligne est rattachee a SA chaine par la fenetre [store.started_at, store.done_at]
(arrondie a la seconde) ; biblio_raw n'a pas d'identifiant de chaine (triggered_by_idea_id = 'veille_active').
UPDATE rag_chunks : cible par `id`, `+active` dans le WHERE (pas d'index utilisable sur active seul).
Usage : python tools/forge_veille_quarantaine_20261024.py [--apply]   (sans --apply : comptage seul)
"""
from __future__ import annotations

__FORGE_COLOR__ = "digestif/veille : quarantaine des chaines de veille du 24/10, rien supprime"  # organe declare le 2026-10-25 (gate anatomie, CI 7991f0daa)

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CHAINES = ("wj_28a43f91f4", "wj_d97c3c8150", "wj_27d38b0692", "wj_ea1bf12b7c",
           "wj_f8a63dfee0", "wj_b3c76cf691", "wj_704354dfb6")
MOTIF = "non source: veille a 0 resultat de recherche (SearXNG muet/moteurs bloques), contenu fabrique"
RETRACTION = "quarantine_non_source_20261024"


def _sec(iso: str) -> str:
    t = datetime.fromisoformat(iso).astimezone(timezone.utc)
    return t.strftime("%Y-%m-%d %H:%M:%S")


def main(apply: bool) -> dict:
    from nokido_agent.app.forge_db_path import open_writer

    conn = open_writer(timeout=30.0)
    maintenant = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rapport = {}
    for ch in CHAINES:
        row = conn.execute("SELECT started_at, done_at FROM agent_chain_nodes "
                           "WHERE chain_id=? AND step_name='store'", (ch,)).fetchone()
        if not row or not row[0] or not row[1]:
            rapport[ch] = {"erreur": "fenetre store illisible"}
            continue
        debut, fin = _sec(row[0]), _sec(row[1])
        bib = [r[0] for r in conn.execute(
            "SELECT id FROM biblio_raw WHERE triggered_by_idea_id='veille_active' "
            "AND created_at BETWEEN ? AND ?", (debut, fin))]
        urls = [r[0] for r in conn.execute(
            "SELECT url FROM biblio_raw WHERE id IN (%s)" % ",".join("?" * len(bib)), bib)] if bib else []
        chunks = []
        if urls:
            # fenetre d'ingestion : de l'etape ingest au store (secondes arrondies)
            ing = conn.execute("SELECT started_at FROM agent_chain_nodes WHERE chain_id=? AND step_name='ingest'",
                               (ch,)).fetchone()
            d0 = _sec(ing[0]) if ing and ing[0] else debut
            chunks = [r[0] for r in conn.execute(
                "SELECT id FROM rag_chunks WHERE ingested_at BETWEEN ? AND ? AND +active=1 AND source IN (%s)"
                % ",".join("?" * len(urls)), (d0, fin, *urls))]
        if apply:
            motif = "%s | chaine %s | %s" % (MOTIF, ch, maintenant)
            for i in bib:
                conn.execute("UPDATE biblio_raw SET status='rejected', rejection_reason=?, updated_at=? WHERE id=?",
                             (motif, maintenant, i))
            for i in chunks:
                conn.execute("UPDATE rag_chunks SET active=0, retraction_status=? WHERE id=? AND +active=1",
                             (RETRACTION, i))
        rapport[ch] = {"biblio_raw": len(bib), "rag_chunks": len(chunks), "applique": apply}
    for ch, r in rapport.items():
        print(ch, r)
    return rapport


if __name__ == "__main__":
    main("--apply" in sys.argv)

"""tools/forge_rag_dedup_hash.py — dedup des chunks RAG par hash, ARCHIVE puis supprime.

P2 roadmap. Mesure 2026-07-31 : 1112 groupes de hash dupliques = 4806 chunks en
trop. Le SSoT annoncait 1067, la mesure dit 1112 -- c'est le chiffre reel qui
pilote.

CE QUE SONT CES DOUBLONS (regarde avant d'agir) : des fichiers de TEMPLATE ingeres
des centaines de fois sous des chemins differents -- 445 copies du meme
`mcp_server.py`, 267 du meme README. Les 1109 groupes « multi-sources » ne sont donc
PAS de l'attribution multiple qu'on perdrait : ce sont des copies du meme depot
modele. Un exemplaire suffit.

REVERSIBILITE — le moteur RAG ne filtre pas sur la colonne `active` (verifie), et le
seul mecanisme reversible existant est `meta.injection_flagged`, dont la semantique
est « injection detectee » : le detourner pour dire « doublon » polluerait le
diagnostic d'injection. On applique donc le pattern deja employe par la retention du
corps : ARCHIVE-NOT-PURGE. Les lignes partent dans `rag_chunks_dedup_archive` AVANT
d'etre supprimees ; la restauration est un INSERT INTO ... SELECT.

CHOIX DE L'EXEMPLAIRE GARDE : celui qui porte un embedding d'abord, puis le plus
consulte, puis le rowid le plus bas. Verifie AVANT ecriture : sur les 1112 groupes,
zero cas ou le garde perdrait un vecteur que seul un doublon portait. Les
`access_count` des doublons sont AGREGES sur le garde (12 acces en jeu) : la
popularite mesuree ne doit pas disparaitre avec la ligne.

FTS : les DEUX tables sont nettoyees. `rag_chunks_fts` est celle que le moteur lit,
`rag_fts` reste servie ailleurs ; une ligne FTS orpheline sert un texte dont le chunk
n'existe plus. `INSERT OR IGNORE` ne met jamais a jour une table FTS -- ici on ne fait
que DELETE, mais la lecon vaut d'etre rappelee au prochain lecteur.

Usage :
  dry-run (defaut, n'ecrit RIEN) : run action=trusted_script path=tools/forge_rag_dedup_hash.py
  execution                      : ... script_args="--apply"
  restauration                   : ... script_args="--restore"
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ARCHIVE = "rag_chunks_dedup_archive"

# Le garde : embedding d'abord, puis le plus consulte, puis le plus ancien rowid.
# `created_at` est ECARTE volontairement comme critere : c'est la date d'INGESTION,
# pas celle de l'evenement (piege paye le 2026-07-29, verdict artefactuel bati
# dessus). Le rowid est un ordre stable qui ne pretend rien dire d'autre.
_RANK = """
SELECT id, hash,
       ROW_NUMBER() OVER (PARTITION BY hash
         ORDER BY (embedding IS NULL), COALESCE(access_count,0) DESC, rowid) AS rn
FROM rag_chunks
WHERE hash IS NOT NULL
  AND hash IN (SELECT hash FROM rag_chunks WHERE hash IS NOT NULL
               GROUP BY hash HAVING COUNT(*) > 1)
"""


def _doublons(conn) -> list:
    """ids des exemplaires EN TROP (rn > 1). Le rn = 1 de chaque groupe est garde."""
    return [r[0] for r in conn.execute(f"SELECT id FROM ({_RANK}) WHERE rn > 1")]


def rapport(conn) -> dict:
    g = conn.execute("""SELECT COUNT(*), SUM(n-1) FROM
        (SELECT COUNT(*) n FROM rag_chunks WHERE hash IS NOT NULL
         GROUP BY hash HAVING n > 1)""").fetchone()
    perte_vec = conn.execute(f"""
        SELECT COUNT(*) FROM (
          SELECT hash,
                 MAX(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) AS grp,
                 MAX(CASE WHEN rn = 1 AND embedding IS NOT NULL THEN 1 ELSE 0 END) AS gard
          FROM (SELECT r.rn, c.hash, c.embedding FROM ({_RANK}) r
                JOIN rag_chunks c ON c.id = r.id)
          GROUP BY hash) WHERE grp = 1 AND gard = 0""").fetchone()[0]
    return {"groupes": g[0] or 0, "chunks_en_trop": g[1] or 0,
            "groupes_ou_le_garde_perdrait_son_vecteur": perte_vec}


def restaurer() -> dict:
    from nokido_agent.app.forge_db_path import open_writer, write_retry

    with open_writer() as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (ARCHIVE,)
        ).fetchone():
            return {"ok": False, "raison": f"pas de table {ARCHIVE} — rien a restaurer"}
        n = conn.execute(f"SELECT COUNT(*) FROM {ARCHIVE}").fetchone()[0]
        cols = ",".join(r[1] for r in conn.execute("PRAGMA table_info(rag_chunks)"))
        write_retry(lambda c: c.execute(
            f"INSERT OR IGNORE INTO rag_chunks ({cols}) SELECT {cols} FROM {ARCHIVE} a "
            f"WHERE NOT EXISTS (SELECT 1 FROM rag_chunks WHERE id = a.id)"))
        return {"ok": True, "restaures": n,
                "note": "l'archive est CONSERVEE ; la supprimer est une decision distincte"}


def main() -> int:
    from nokido_agent.app.forge_db_path import open_writer, write_retry

    apply = "--apply" in sys.argv
    if "--restore" in sys.argv:
        print(restaurer())
        return 0

    with open_writer() as conn:
        av = rapport(conn)
        print(f"AVANT : {av['groupes']} groupes, {av['chunks_en_trop']} chunks en trop")
        if av["groupes_ou_le_garde_perdrait_son_vecteur"]:
            # Un dedup qui fait perdre des vecteurs rend le corpus MOINS trouvable
            # qu'avant : c'est l'inverse du but. On s'arrete plutot que d'abimer.
            print("ARRET : %d groupe(s) perdraient leur embedding — ne pas supprimer"
                  % av["groupes_ou_le_garde_perdrait_son_vecteur"])
            return 2
        ids = _doublons(conn)
        print(f"a supprimer : {len(ids)} chunks (garde = 1 par hash)")
        if not apply:
            print("DRY-RUN — rien ecrit. Ajouter --apply pour executer.")
            return 0

        # write_retry ouvre SA PROPRE connexion et la passe a l'operation : les
        # lambdas prennent donc `c` en parametre. Une lambda sans argument leve
        # TypeError au premier appel -- attrape ici parce que l'ARCHIVE precede
        # toute suppression, donc l'echec n'a rien detruit.
        cols = ",".join(r[1] for r in conn.execute("PRAGMA table_info(rag_chunks)"))
        write_retry(lambda c: c.execute(
            f"CREATE TABLE IF NOT EXISTS {ARCHIVE} AS SELECT {cols} FROM rag_chunks WHERE 0"))

        lot, arch, agr, sup, fts = 400, 0, 0, 0, 0
        for i in range(0, len(ids), lot):
            paquet = ids[i:i + lot]
            q = ",".join("?" * len(paquet))
            # 1. ARCHIVE d'abord — jamais l'inverse.
            arch += write_retry(lambda c: c.execute(
                f"INSERT INTO {ARCHIVE} ({cols}) SELECT {cols} FROM rag_chunks "
                f"WHERE id IN ({q})", paquet)).rowcount
            # 2. La popularite du doublon revient au garde (sinon elle disparait).
            agr += write_retry(lambda c: c.execute(f"""
                UPDATE rag_chunks SET access_count = COALESCE(access_count,0) + (
                  SELECT COALESCE(SUM(a.access_count),0) FROM {ARCHIVE} a
                  WHERE a.hash = rag_chunks.hash AND a.id IN ({q}))
                WHERE hash IN (SELECT hash FROM {ARCHIVE} WHERE id IN ({q}))
                  AND id NOT IN ({q})""", paquet * 3)).rowcount
            # 3. FTS : une ligne orpheline sert un texte dont le chunk n'existe plus.
            for t in ("rag_chunks_fts", "rag_fts"):
                try:
                    fts += write_retry(lambda c, t=t: c.execute(
                        f"DELETE FROM {t} WHERE chunk_id IN ({q})", paquet)).rowcount
                except Exception as e:
                    # Schemas FTS heterogenes (l'une porte chunk_id, l'autre non) :
                    # on le DIT au lieu de laisser croire a un nettoyage complet.
                    print(f"  [fts] {t} non nettoyee : {type(e).__name__}: {str(e)[:70]}")
            sup += write_retry(lambda c: c.execute(
                f"DELETE FROM rag_chunks WHERE id IN ({q})", paquet)).rowcount
            print(f"  lot {i//lot + 1}: archives={arch} supprimes={sup}", flush=True)

        ap = rapport(conn)
        print(f"APRES : {ap['groupes']} groupes, {ap['chunks_en_trop']} chunks en trop")
        print(f"archives={arch} agregations_acces={agr} lignes_fts={fts} supprimes={sup}")
        print(f"restauration : --restore (table {ARCHIVE})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Index TRIGRAM sur le code et les logs — trouver `ErrConnectionReset` par fragment.

BM25 cherche des MOTS. Il ne trouve pas une SOUS-CHAINE : chercher `ConnectionReset`
ne ramene pas `ErrConnectionReset`, et chercher `rfc9110` ne ramene pas
`rfc:rfc9110`. Sur de la prose c'est sans importance ; sur du code et des logs,
c'est precisement ce qu'on cherche — un nom de variable, un code d'erreur, un
identifiant tronque.

PERIMETRE : code et logs UNIQUEMENT (choix owner du 2026-09-03). Un index trigram
pese 3 a 4 fois le texte source ; l'appliquer aux 2 M chunks engagerait des dizaines
de Go pour un gain quasi nul sur la prose, que le FTS standard sert deja bien.

`source` et `domain` sont INDEXES ici — contrairement a `rag_fts`, qui les declare
UNINDEXED et rend donc 0 sur un `MATCH 'source:...'`. C'est ce zero qui a fait
conclure a tort « aucune RFC ingeree » le 2026-09-03.

Construction par SHADOW + SWAP, comme `forge_self_correction.rebuild_fts_index` :
la table de production n'est remplacee qu'au RENAME final, soit quelques ms de lock.

Usage :
    python tools/forge_fts_trigram.py             # mesure : volume, cout estime
    python tools/forge_fts_trigram.py --apply     # construit
    python tools/forge_fts_trigram.py --bench     # trigram vs BM25 sur identifiants
"""

__FORGE_COLOR__ = "digestif/indexation-rag"

import shutil
import sqlite3
import sys
import time
from pathlib import Path

# Marge disque exigee. Mesure 2026-09-03 : une construction sans garde a fait
# passer le WAL a 33,97 Go pour 30 Go libres — a quelques minutes de saturer le
# volume, ce qui aurait corrompu la base en pleine ecriture ET couche le hub.
# Un outil qui peut remplir un disque doit se surveiller lui-meme.
MARGE_GO = 15.0
CHECKPOINT_TOUS = 20        # lots ; sinon le WAL croit sans borne en autocommit

ROOT = Path(__file__).resolve().parents[1]
TABLE = "rag_code_trigram"
SHADOW = TABLE + "_build"
LOT = 5000

# Ce qui merite un trigram : on y cherche des fragments exacts.
EXTS = (".py", ".ts", ".js", ".tsx", ".jsx", ".rs", ".go", ".c", ".h", ".cpp",
        ".java", ".rb", ".sh", ".ps1", ".sql", ".toml", ".yml", ".yaml", ".json",
        ".ini", ".cfg", ".log")


def _db():
    for c in (Path("%NOKIDO_DATA%\embeddings.db"), ROOT / "RAG" / "embeddings.db"):
        if c.exists():
            return c
    return None


def _libre_go(chemin) -> float:
    try:
        return shutil.disk_usage(Path(chemin).anchor).free / 1e9
    except OSError:
        return -1.0          # ILLISIBLE : ne pas lire comme « il y a de la place »


def _checkpoint(conn, db):
    """Tronque le WAL et rend l'espace libre restant."""
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error as e:
        print("   [wal] checkpoint refuse (%s) — le WAL va continuer de croitre"
              % type(e).__name__, file=sys.stderr)
    return _libre_go(db)


def _trigram_disponible(conn) -> str:
    """Rend "" si disponible, sinon la RAISON. Ne jamais supposer une capacite."""
    if sqlite3.sqlite_version_info < (3, 34, 0):
        return "SQLite %s < 3.34 (tokenizer trigram absent)" % sqlite3.sqlite_version
    try:
        conn.execute("CREATE VIRTUAL TABLE temp._trig_probe "
                     "USING fts5(x, tokenize='trigram')")
        conn.execute("DROP TABLE temp._trig_probe")
    except sqlite3.Error as e:
        return "%s: %s" % (type(e).__name__, e)
    return ""


def _eligibles(conn, plafond=None):
    """Chunks de code/log, en DEUX PASSES.

    Passe 1 : (id, source, domain) seulement — colonnes etroites, l'index
    `idx_rag_source` les couvre. Passe 2 : le TEXTE, uniquement pour les ids
    retenus, via la clef primaire.

    La v1 lisait `text` de TOUS les chunks pour filtrer sur `source` : elle
    rapatriait les 22,8 Go pour n'en garder que quelques pourcents, et a dépassé
    le cap d'appel. C'est le motif exact paye le 2026-09-03 sur la jointure FTS —
    reproduit dans l'outil ecrit pour l'eviter. Ne JAMAIS charger le contenu pour
    decider de sa pertinence quand un champ etroit suffit.
    """
    retenus = []
    cur = conn.execute("SELECT id, source, domain FROM rag_chunks")
    while True:
        lot = cur.fetchmany(50000)
        if not lot:
            break
        for cid, src, dom in lot:
            s = (src or "").lower()
            if s.endswith(EXTS) or "/log" in s or s.startswith("laforge_code"):
                retenus.append((str(cid), src or "", dom or "general"))
                if plafond and len(retenus) >= plafond:
                    break
        if plafond and len(retenus) >= plafond:
            break

    out = []
    for i in range(0, len(retenus), 900):
        part = retenus[i:i + 900]
        ph = ",".join("?" * len(part))
        textes = dict(conn.execute(
            "SELECT id, text FROM rag_chunks WHERE id IN (%s)" % ph,
            [r[0] for r in part]))
        for cid, src, dom in part:
            t = textes.get(cid)
            if t:
                out.append((cid, t, src, dom))
    return out


def construire(appliquer=False, plafond=None):
    db = _db()
    if db is None:
        print("[trigram] aucune base joignable", file=sys.stderr)
        return 3
    conn = sqlite3.connect(str(db), isolation_level=None, timeout=180)
    conn.execute("PRAGMA busy_timeout=180000")

    raison = _trigram_disponible(conn)
    if raison:
        print("[trigram] INDISPONIBLE — %s" % raison, file=sys.stderr)
        return 4
    print("[trigram] SQLite %s, tokenizer disponible" % sqlite3.sqlite_version)

    t0 = time.time()
    lignes = _eligibles(conn, plafond)
    octets = sum(len(t or "") for _, t, _, _ in lignes)
    print("[trigram] %d chunk(s) de code/log, %.1f Mo de texte (scan en %.1f s)"
          % (len(lignes), octets / 1e6, time.time() - t0))
    # 3-4x etait une estimation OPTIMISTE : un index trigram indexe chaque
    # position de caractere. Sur du code (identifiants longs, ponctuation dense)
    # le facteur observe est nettement superieur, et le WAL transitoire peut
    # depasser la taille finale. On annonce donc une fourchette large, et on
    # surveille l'espace PENDANT la construction plutot que de s'y fier.
    print("[trigram] index attendu : ~%.1f a %.1f Go (3 a 10x le texte selon la "
          "densite ; le WAL transitoire peut faire davantage)"
          % (octets * 3 / 1e9, octets * 10 / 1e9))
    print("[trigram] disque : %.0f Go libres" % _libre_go(db))
    if not appliquer:
        print("[trigram] DRY-RUN. Relancer avec --apply pour construire.")
        return 0
    if not lignes:
        print("[trigram] rien a indexer.")
        return 0

    libre = _libre_go(db)
    print("[trigram] disque : %.0f Go libres (marge exigee %.0f)" % (libre, MARGE_GO))
    if libre >= 0 and libre < MARGE_GO * 2:
        print("[trigram] REFUS : %.0f Go libres, il en faut au moins %.0f pour "
              "construire sans risque." % (libre, MARGE_GO * 2), file=sys.stderr)
        return 5

    t1 = time.time()
    conn.execute("DROP TABLE IF EXISTS %s" % SHADOW)
    conn.execute("CREATE VIRTUAL TABLE %s USING fts5("
                 "chunk_id UNINDEXED, text, source, domain, tokenize='trigram')"
                 % SHADOW)
    for i in range(0, len(lignes), LOT):
        conn.executemany(
            "INSERT INTO %s (chunk_id, text, source, domain) VALUES (?,?,?,?)"
            % SHADOW, lignes[i:i + LOT])
        n_lot = i // LOT
        if n_lot % CHECKPOINT_TOUS == 0:
            libre = _checkpoint(conn, db)
            print("   %d/%d — %.0f Go libres" % (min(i + LOT, len(lignes)),
                                                 len(lignes), libre), flush=True)
            # ABANDON PROPRE plutot que saturation : la shadow est jetee, la
            # table de production n'a jamais ete touchee (le swap vient apres).
            if 0 <= libre < MARGE_GO:
                conn.execute("DROP TABLE IF EXISTS %s" % SHADOW)
                _checkpoint(conn, db)
                print("[trigram] ABANDON : plus que %.0f Go libres. Shadow jetee, "
                      "production intacte. Reduire le perimetre (--limite) ou "
                      "liberer de l'espace." % libre, file=sys.stderr)
                return 6
        elif n_lot % 5 == 0:
            print("   %d/%d" % (min(i + LOT, len(lignes)), len(lignes)), flush=True)
    # SWAP : la production n'est remplacee qu'ici, quelques ms.
    conn.execute("DROP TABLE IF EXISTS %s_old" % TABLE)
    existe = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                          (TABLE,)).fetchone()
    if existe:
        conn.execute("ALTER TABLE %s RENAME TO %s_old" % (TABLE, TABLE))
    conn.execute("ALTER TABLE %s RENAME TO %s" % (SHADOW, TABLE))
    conn.execute("DROP TABLE IF EXISTS %s_old" % TABLE)
    libre = _checkpoint(conn, db)
    print("[trigram] construit en %.1f s — %.0f Go libres" % (time.time() - t1, libre))

    # Verification PAR L'EFFET : une sous-chaine se retrouve-t-elle vraiment ?
    temoin = conn.execute("SELECT text FROM %s LIMIT 1" % TABLE).fetchone()
    if temoin and temoin[0]:
        mot = next((w for w in temoin[0].split() if len(w) >= 9), None)
        if mot:
            frag = mot[2:8]
            n = len(list(conn.execute(
                "SELECT rowid FROM %s WHERE %s MATCH ? LIMIT 5"
                % (TABLE, TABLE), ('"%s"' % frag,))))
            print("[trigram] preuve : fragment %r retrouve dans %d chunk(s)"
                  % (frag, n))
            if not n:
                print("[trigram] ATTENTION : le fragment n'est PAS retrouve —"
                      " l'index existe mais ne sert pas.", file=sys.stderr)
                return 2
    return 0


def bench():
    """Trigram vs BM25 sur des fragments d'identifiants. Le gain se MESURE."""
    db = _db()
    conn = sqlite3.connect("file:%s?mode=ro" % str(db).replace("\\", "/"), uri=True)
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (TABLE,)).fetchone():
        print("[bench] %s absent — construire d'abord (--apply)" % TABLE,
              file=sys.stderr)
        return 3
    fragments = ["onnection", "ingest_pip", "hunk_id", "9110", "orge_rag", "sandbox"]
    print("%-14s %10s %10s" % ("fragment", "trigram", "BM25(rag_fts)"))
    for f in fragments:
        try:
            a = len(list(conn.execute("SELECT rowid FROM %s WHERE %s MATCH ? LIMIT 200"
                                      % (TABLE, TABLE), ('"%s"' % f,))))
        except sqlite3.Error as e:
            a = "ERR:%s" % type(e).__name__
        try:
            b = len(list(conn.execute(
                "SELECT rowid FROM rag_fts WHERE rag_fts MATCH ? LIMIT 200", (f,))))
        except sqlite3.Error as e:
            b = "ERR:%s" % type(e).__name__
        print("%-14s %10s %10s" % (f, a, b))
    print("\nLe trigram trouve la SOUS-CHAINE ; BM25 exige le mot entier. Un ecart"
          " nul signifierait que le trigram n'apporte rien sur ce corpus.")
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--bench" in argv:
        return bench()
    plafond = None
    if "--limite" in argv:
        plafond = int(argv[argv.index("--limite") + 1])
    return construire("--apply" in argv, plafond)


if __name__ == "__main__":
    raise SystemExit(main())

"""Chaque base indexee POUR SES PROPRES requetes — pas selon un modele generique.

Un index utile n'est pas un index « en plus » : c'est celui que l'optimiseur RETIENT
pour les requetes que le code emet REELLEMENT. Cet outil confronte les deux :

    requetes SQL trouvees dans app/ et tools/   ->   EXPLAIN QUERY PLAN sur la base
                                                     -> SCAN ? sur quelle table ?
                                                     -> quelle colonne au WHERE ?

Il ne devine pas une « bonne pratique » : il rapporte les balayages MESURES et la
colonne qui les cause. `EXPLAIN QUERY PLAN` ne lit aucune donnee (planification
seule), donc l'audit est sur, rapide, et ne peut pas mettre le hub a terre — ce que
trois balayages ont deja fait sur cette base.

CE QUI A MOTIVE L'OUTIL (2026-09-03). `forge_ingest_pipeline.store_chunks`
dedupliquait par `WHERE json_extract(meta,'$.fingerprint') IN (...)` : une
EXPRESSION, qu'aucun index ne sert. Plan = `SCAN rag_chunks`, soit 22,8 Go balayes
PAR DOCUMENT ingere — 180,7 Go lus mesures sur une seule campagne. Un index
d'expression l'a supprime en 105 s. Rien ne garantit que les 42 autres bases n'ont
pas leur equivalent, et personne ne le saurait : le defaut ne leve aucune erreur, il
se contente d'etre lent.

TROIS ETATS, JAMAIS DEUX. Une requete assemblee par f-string n'est pas analysable :
elle est rapportee `NON_ANALYSABLE`, jamais « saine ». Un scanner qui compte comme
sain ce qu'il n'a pas pu lire surestime sa couverture.

Usage :
    python tools/forge_db_index_advisor.py               # toutes les bases
    python tools/forge_db_index_advisor.py --base RAG/embeddings.db
    python tools/forge_db_index_advisor.py --min-lignes 50000
"""

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "digestif/indexation-rag"

import ast
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SORTIE = ROOT / "sandbox" / "db_index_advisor.json"
# En deca, un balayage complet est sans consequence : indexer coute plus que ca ne
# rapporte. Le seuil est un choix explicite, pas une constante magique.
MIN_LIGNES = 20000

# Ce que l'audit N'A PAS PU examiner. Un scanner qui ecarte en silence surestime
# sa couverture : le dénominateur voyage avec le resultat.
ECARTES = {"fichiers_illisibles": 0, "tables_non_mesurables": 0,
           "requetes_hors_schema": 0}


def _bases():
    """Reutilise l'enumeration du census plutot que de la reecrire (anti-dup)."""
    sys.path.insert(0, str(ROOT))
    from nokido_agent.tools.forge_savoir_census import bases
    return bases()


def _requetes_du_code():
    """Litteraux SQL de app/ et tools/. Rend (sql, fichier, ligne, analysable)."""
    out = []
    for zone in ("app", "tools"):
        for f in (ROOT / zone).glob("*.py"):
            try:
                src = f.read_text(encoding="utf-8", errors="replace")
                arbre = ast.parse(src)
            except (OSError, SyntaxError):
                ECARTES["fichiers_illisibles"] += 1
                continue
            for n in ast.walk(arbre):
                # Une f-string (JoinedStr) porte des trous : le SQL n'est pas
                # connu statiquement. On le DIT au lieu de l'ignorer.
                if isinstance(n, ast.JoinedStr):
                    brut = "".join(v.value for v in n.values
                                   if isinstance(v, ast.Constant)
                                   and isinstance(v.value, str))
                    if re.search(r"\bFROM\s+\w+", brut, re.I):
                        out.append((brut, f.name, getattr(n, "lineno", 0), False))
                    continue
                if isinstance(n, ast.Constant) and isinstance(n.value, str):
                    s = n.value
                    if re.match(r"\s*SELECT\b", s, re.I) and re.search(
                            r"\bFROM\s+\w+", s, re.I) and "%s" not in s:
                        out.append((s, f.name, getattr(n, "lineno", 0), True))
    return out


def _tables_grosses(conn, seuil):
    """(table -> borne sup de lignes). MAX(rowid), jamais COUNT(*) : un COUNT sur
    une grosse table balaie tout, et c'est ce qui a mis le hub a terre deux fois."""
    out = {}
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        if t.startswith("sqlite_") or re.search(r"_(data|idx|docsize|config|content)$", t):
            continue
        try:
            n = conn.execute('SELECT MAX(rowid) FROM "%s"' % t).fetchone()[0] or 0
        except sqlite3.Error:
            # Table virtuelle ou illisible : hors perimetre du comptage, mais
            # COMPTEE — « je n'ai pas pu mesurer » n'est pas « elle est petite ».
            ECARTES["tables_non_mesurables"] += 1
            continue
        if n >= seuil:
            out[t] = n
    return out


def _balaie_la_table(plan, table):
    """`SCAN t` seul = parcours de la TABLE (le defaut). `SCAN t USING ... INDEX`
    = parcours d'un INDEX, souvent couvrant : c'est deja une optimisation.

    Ne pas les distinguer faisait declarer « non retenu » un index qui faisait
    exactement son travail — mesure 2026-09-03 sur
    `idx_rag_chunks_json_extract_meta_ingested_a`.
    """
    m = re.search(r"\bSCAN\s+%s\b(?P<suite>[^|]*)" % re.escape(table), plan, re.I)
    if not m:
        return False
    return "INDEX" not in m.group("suite").upper()


def _est_virtuelle(conn, table):
    """Une table FTS5 ne s'indexe PAS : `CREATE INDEX` y est refuse, et un
    « SCAN » sur un `MATCH` est son fonctionnement NORMAL, pas un defaut. Les
    confondre produirait des conseils impossibles a appliquer — un conseiller qui
    recommande l'invalide se fait desarmer au premier essai."""
    r = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                     (table,)).fetchone()
    return bool(r and r[0] and re.search(r"CREATE\s+VIRTUAL\s+TABLE", r[0], re.I))


def _colonnes(conn, table):
    try:
        return {c[1] for c in conn.execute('PRAGMA table_info("%s")' % table)}
    except sqlite3.Error:
        return set()


def _colonne_du_where(sql, colonnes):
    """La colonne filtree, SEULEMENT si c'en est vraiment une.

    Rend "" des que le predicat n'est pas un simple `colonne <op> ...` : un
    prédicat compose (`text IS NOT NULL AND ...`), un alias non resolu (`c.id`)
    ou un fragment tronque ne donnent pas un index valide. Mieux vaut « a
    examiner » qu'une commande qui echouera. Seule exception : `json_extract(...)`,
    qui EST indexable comme expression — c'est ce qui a corrige la dedup
    d'ingestion le 2026-09-03.
    """
    m = re.search(r"\bWHERE\s+(.+?)(?:\bGROUP\b|\bORDER\b|\bLIMIT\b|$)", sql,
                  re.I | re.S)
    if not m:
        return ""
    cl = re.sub(r"\s+", " ", m.group(1)).strip()
    m2 = re.match(r"(json_extract\([^)]*\))\s*(?:=|IN|IS|LIKE)", cl, re.I)
    if m2:
        return m2.group(1)
    m3 = re.match(r"(?:\w+\.)?(\w+)\s*(?:=|IN|>|<|>=|<=)\s*[?'\"\d]", cl, re.I)
    if not m3:
        return ""
    col = m3.group(1)
    # La colonne doit EXISTER dans la table : sans cette verification, une regex
    # tronquee proposait des index sur `embedd` ou `doma`.
    return col if col in colonnes else ""


def auditer(base_filtre=None, seuil=MIN_LIGNES):
    requetes = _requetes_du_code()
    rapport = {"seuil_lignes": seuil, "requetes_lues": len(requetes),
               "non_analysables": sum(1 for r in requetes if not r[3]),
               "bases": []}
    for chemin in _bases():
        rel = str(Path(chemin).relative_to(ROOT)) if str(chemin).startswith(str(ROOT)) \
            else str(chemin)
        if base_filtre and base_filtre not in rel.replace("\\", "/"):
            continue
        fiche = {"base": rel.replace("\\", "/"), "scans": [], "etat": "lu"}
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % str(chemin).replace("\\", "/"),
                                   uri=True)
            grosses = _tables_grosses(conn, seuil)
        except sqlite3.Error as e:
            fiche["etat"] = "ILLISIBLE (%s)" % type(e).__name__
            rapport["bases"].append(fiche)
            continue
        fiche["tables_volumineuses"] = grosses
        if not grosses:
            rapport["bases"].append(fiche)
            continue

        vus = set()
        for sql, fichier, ligne, analysable in requetes:
            if not analysable:
                continue
            cibles = {t for t in grosses
                      if re.search(r"\b(FROM|JOIN)\s+%s\b" % re.escape(t), sql, re.I)}
            if not cibles:
                continue
            try:
                plan = " | ".join(
                    r[-1] for r in conn.execute("EXPLAIN QUERY PLAN " + sql,
                                                tuple([None] * sql.count("?"))))
            except sqlite3.Error:
                # Requete d'un AUTRE schema (chaque base voit passer les 1400
                # requetes du depot) : attendu et sans consequence, mais compte.
                ECARTES["requetes_hors_schema"] += 1
                continue
            for t in cibles:
                if not _balaie_la_table(plan, t):
                    continue
                if _est_virtuelle(conn, t):
                    continue      # FTS5 : non indexable, et le SCAN y est normal
                col = _colonne_du_where(sql, _colonnes(conn, t))
                cle = (t, col)
                if cle in vus:
                    continue
                vus.add(cle)
                fiche["scans"].append({
                    "table": t, "lignes_max": grosses[t], "colonne": col,
                    "origine": "%s:%d" % (fichier, ligne),
                    # SQL COMPLET : la version tronquee a 150 chars etait rejouee
                    # telle quelle par `--apply`, d'ou « incomplete input » et
                    # « no such column: c » — 3 index sur 5 declares « non
                    # verifies » alors qu'ils n'avaient jamais ete testes.
                    # L'affichage tronque, la mesure non.
                    "sql": re.sub(r"\s+", " ", sql),
                    "actionnable": bool(col),
                    "index_suggere": (
                        'CREATE INDEX idx_%s_%s ON %s(%s);' % (
                            t, re.sub(r"\W+", "_", col)[:28].strip("_"), t, col)
                        if col else "(predicat compose ou alias — a examiner a la"
                                    " main, aucun index simple ne s'en deduit)")})
        fiche["scans"].sort(key=lambda s: (not s["actionnable"], -s["lignes_max"]))
        rapport["bases"].append(fiche)
    return rapport


def _ecrivain_actif() -> str:
    """Construire un index prend un verrou : ne pas le faire sous un ecrivain."""
    try:
        import psutil
    except ImportError:
        return ""
    for p in psutil.process_iter(["pid"]):
        try:
            cl = " ".join(p.cmdline())
        except Exception:  # noqa: BLE001  # muet-ok : process d'un autre compte
            continue
        if any(m in cl for m in ("audit_rfc_compliance", "forge_ingest",
                                 "curriculum_ingest", "rag_warmup")):
            return "pid %s" % p.pid
    return ""


def appliquer(rapport):
    """Pose les index ACTIONNABLES et verifie chacun PAR LE PLAN.

    Un `CREATE INDEX` qui ne leve pas ne prouve rien : l'optimiseur peut ne pas
    retenir l'index. Le verdict se lit sur le plan d'apres, jamais sur l'absence
    d'erreur — c'est ce qui a valide l'index de dedup le 2026-09-03.
    """
    import sqlite3
    import time
    poses, refuses = [], []
    occupe = _ecrivain_actif()
    if occupe:
        print("[advisor] REFUS : un ecrivain est actif (%s)." % occupe,
              file=sys.stderr)
        return [], [("*", "ecrivain actif")]

    for f in rapport["bases"]:
        actionnables = [s for s in f.get("scans", []) if s.get("actionnable")]
        if not actionnables:
            continue
        chemin = ROOT / f["base"]
        try:
            con = sqlite3.connect(str(chemin), isolation_level=None, timeout=180)
            con.execute("PRAGMA busy_timeout=180000")
        except sqlite3.Error as e:
            refuses.append((f["base"], "%s: %s" % (type(e).__name__, e)))
            continue
        for s in actionnables:
            ddl = s["index_suggere"].rstrip(";")
            nom = re.search(r"INDEX\s+(\w+)", ddl).group(1)
            t0 = time.time()
            try:
                con.execute(ddl.replace("CREATE INDEX", "CREATE INDEX IF NOT EXISTS"))
            except sqlite3.Error as e:
                refuses.append((nom, "%s: %s" % (type(e).__name__, e)))
                continue
            dt = time.time() - t0
            try:
                plan = " | ".join(r[-1] for r in con.execute(
                    "EXPLAIN QUERY PLAN " + s["sql"],
                    tuple([None] * s["sql"].count("?"))))
                retenu = not _balaie_la_table(plan, s["table"])
            except sqlite3.Error:
                retenu = None      # cree, mais NON verifie : on le dit
            poses.append({"index": nom, "table": s["table"], "secondes": round(dt, 1),
                          "retenu_par_le_plan": retenu})
            print("   %-46s %6.1f s  plan: %s"
                  % (nom, dt, {True: "SEARCH (retenu)", False: "SCAN (NON retenu)",
                               None: "non verifie"}[retenu]))
    return poses, refuses


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    base = None
    seuil = MIN_LIGNES
    if "--base" in argv:
        base = argv[argv.index("--base") + 1]
    if "--min-lignes" in argv:
        seuil = int(argv[argv.index("--min-lignes") + 1])

    r = auditer(base, seuil)
    r["non_examine"] = dict(ECARTES)
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    try:
        SORTIE.write_text(json.dumps(r, indent=1, ensure_ascii=False),
                          encoding="utf-8")
    except OSError as e:
        print("[advisor] rapport non ecrit (%s)" % type(e).__name__, file=sys.stderr)

    print("=== INDEX ADVISOR — %d requete(s) SQL lues dans le code "
          "(%d non analysables, assemblees dynamiquement)"
          % (r["requetes_lues"], r["non_analysables"]))
    print("    seuil : tables de %d lignes ou plus\n" % r["seuil_lignes"])
    total = actionnables = 0
    for f in r["bases"]:
        if f["etat"] != "lu":
            print("  %-42s %s" % (f["base"], f["etat"]))
            continue
        if not f.get("scans"):
            continue
        print("  %s" % f["base"])
        for s in f["scans"]:
            total += 1
            if not s["actionnable"]:
                continue          # liste seulement les ACTIONNABLES en clair
            actionnables += 1
            print("     SCAN %-20s ~%9d lignes  filtre sur %-18s  %s"
                  % (s["table"], s["lignes_max"], s["colonne"], s["origine"]))
            # (le SQL est stocke ENTIER dans le rapport ; ici on n'affiche que
            #  l'essentiel — tronquer la MESURE etait le defaut, pas l'affichage)
            print("          %s" % s["index_suggere"])
        reste = sum(1 for s in f["scans"] if not s["actionnable"])
        if reste:
            print("     (+ %d balayage(s) a predicat compose : aucun index simple"
                  " ne s'en deduit, voir le rapport)" % reste)
    print("\n%d balayage(s) mesure(s), dont %d avec un index simple identifiable."
          % (total, actionnables))

    if "--apply" in argv:
        print("\n=== POSE DES INDEX ===")
        poses, refuses = appliquer(r)
        ok = sum(1 for p in poses if p["retenu_par_le_plan"] is True)
        print("\n%d index pose(s), dont %d RETENUS par l'optimiseur." % (len(poses), ok))
        for p in poses:
            if p["retenu_par_le_plan"] is not True:
                print("   ATTENTION %s : pose mais %s — le defaut n'est pas corrige"
                      % (p["index"], "non retenu" if p["retenu_par_le_plan"] is False
                         else "non verifie"))
        for nom, err in refuses:
            print("   REFUSE %s : %s" % (nom, err))
    print("NON EXAMINE : %d fichier(s) source illisible(s), %d table(s) non "
          "mesurable(s), %d requete(s) hors schema (attendu)."
          % (ECARTES["fichiers_illisibles"], ECARTES["tables_non_mesurables"],
             ECARTES["requetes_hors_schema"]))
    print("Rapport : %s" % SORTIE)
    if "--apply" not in argv:
        print("Aucun index n'a ete cree : chaque suggestion se relit avant d'etre"
              " posee (un index coute a l'ecriture).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

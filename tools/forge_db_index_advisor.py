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

LA PORTEE (owner, 21/10/2026). « Il existe de la matiere hors RAG, sur d'autres
disques. » Le census ne voit que le depot (`ROOT.rglob("*.db")`) ; le code, lui,
designe ses bases PAR LEUR CHEMIN : %NOKIDO_DATA%\embeddings.db (la vraie),
E:/LaForge_tiede, D:/Temp. L'audit les cherche donc HORS du depot aussi, et DIT
ce qu'il a pu voir de chaque racine : ABSENT (disque non monte), ILLISIBLE
(refus) ou LU. Et une lecture d'index ENTIER (`SELECT COUNT(*)` sans WHERE) est
une lecture MASSIVE : le plan la montre, on la compte.

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
import os
import re
import sqlite3
import tempfile
import sys
import time
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

# --- PORTEE : les bases ne sont pas QUE sous ROOT ----------------------------
# Le census (`forge_savoir_census.bases`) fait `ROOT.rglob("*.db")` : il ne voit
# que le depot. Or le code designe ses bases PAR LEUR CHEMIN, sur d'autres
# lecteurs : %NOKIDO_DATA%\embeddings.db (la vraie), E:/LaForge_tiede, D:/Temp. Un chasseur
# qui ne sort pas du depot ne chasse pas.
EXTENSIONS_BASE = (".db", ".sqlite", ".sqlite3")
EXTENSIONS_SOURCE = (".py", ".ts", ".toml", ".json", ".ps1", ".bat")
ZONES_SOURCE = ("app", "tools", "proxy_deno/core", "config")

# C: est le lecteur du depot : deja couvert par le census, et « hors depot » y
# serait faux. Une racine = une lettre de lecteur, puis ':', puis '/' ou '\' ;
# le segment s'arrete au premier separateur : `une_lettre:/premier_segment`.
_RX_RACINE = re.compile(
    r'(?<![A-Za-z0-9_])([A-Za-z]):[/\\]'
    r'([^\s/\\"\'`<>|,;:)\]}?*]*)')

# La COLLECTION s'arrete a `profondeur` niveaux ; le COMPTAGE au-dela va
# MARGE_AU_DELA niveaux plus loin. Une borne dit COMBIEN, pas « au moins un ».
MARGE_AU_DELA = 3
# Budget de TOUT le parcours hors depot (s) ; au-dela, les racines restantes sont NON_EXAMINE, et le disent.
BUDGET_HORS_DEPOT_S = 30.0
# Filet : un lecteur lent (reseau) ne doit pas faire tourner l'audit pendant des
# heures. Le cortege est DIT (`tronque`), jamais cache derriere un 0.
BUDGET_SCAN_S = 8.0

_CACHE_TEXTES = {}
_CACHE_HORS = {}


_SEGMENTS_SYSTEME = {"windows", "program", "program files", "program files (x86)", "programfiles"}
_SYSTEME_ECARTES = set()   # racines systeme vues dans le code et ecartees : DITES dans le rapport, jamais tues


def est_racine_systeme(racine):
    """Dossier systeme de C: (Windows, Program Files) : le code le cite, Nokido n'y range aucune donnee.

    Decision owner 21/10 : C:/WINDOWS consommait 8 s du budget et laissait C:/nokido, C:/laforge-runner NON_EXAMINE.
    `C:/Program` est la forme reellement extraite de `C:/Program Files/...` (la regex coupe a l'espace)."""
    r = racine.replace("\\", "/").rstrip("/").lower()
    return r.startswith("c:/") and r[3:] in _SEGMENTS_SYSTEME


def racines_hors_depot(textes, depot=None):
    """Racines citees par le code, hors depot.

    `{fichier: texte}` -> racines `une_lettre:/premier_segment`, normalisees en '/', triees, sans doublon. Une racine
    sans segment reste nue (`une_lettre:/`). Owner 21/10 : C: n'est plus exclu en bloc (C:/tmp portait 658 bases) ;
    seules sont ecartees les racines qui SONT le depot, le CONTIENNENT (C:/, C:/Users : on reparcourrait le depot) ou
    sont DEDANS -- le depot est deja couvert par le census.
    """
    dep = Path(depot or ROOT).as_posix().rstrip("/").lower()
    vues = {}                                 # cle insensible a la casse -> premiere graphie (Windows ignore la casse)
    for texte in (textes or {}).values():
        if not texte:
            continue
        for lettre, segment in _RX_RACINE.findall(texte):
            segment = segment.strip().rstrip(".")      # « voir D:/Temp. » : le point finit la phrase, pas le chemin
            if any(c in segment for c in "{}[]%="):
                continue                      # bruit tire d'une chaine de code (A:/n{text_a[, S:/%s), pas un chemin
            racine = ("%s:/%s" % (lettre.upper(), segment) if segment else "%s:/" % lettre.upper())
            r = racine.rstrip("/").lower()
            if r == dep or dep.startswith(r + "/") or r.startswith(dep + "/"):
                continue                      # le depot, un ancetre ou un contenu : deja couvert
            if est_racine_systeme(racine):
                _SYSTEME_ECARTES.add(racine)  # dit plus bas dans les etats, jamais parcouru
                continue
            vues.setdefault(r, racine)
    return sorted(vues.values())


def ordre_parcours(racines, temporaires):
    """Ordre du parcours sous budget (21/10) : temporaires, puis disques de DONNEES (hors C:), puis C:.

    L'ordre alphabetique faisait manger le budget par C:/WINDOWS et laissait E: et V: NON_EXAMINE."""
    temp = set(temporaires)
    return sorted(racines, key=lambda r: (r not in temp, r not in temp and r.upper().startswith("C:"), r))


def racines_temporaires():
    """Dossiers temporaires parcourus MEME non cites : le code qui y ecrit ne les nomme pas (owner 21/10 ;
    mesure : C:/tmp 658 bases, TEMP du compte 1,1 Go de bases de recette)."""
    return sorted({"C:/tmp", "D:/Temp", Path(tempfile.gettempdir()).as_posix()})


def _parcours_borne(racine, profondeur):
    """(bases dans la borne, bases au-dela, tronque, illisibles) sous `racine`.

    La racine est le niveau 0. La COLLECTION s'arrete a `profondeur` niveaux ;
    le COMPTE au-dela va MARGE_AU_DELA niveaux plus loin.
    """
    horizon = profondeur + MARGE_AU_DELA
    trouvees, au_dela, illisibles = [], 0, 0
    debut = time.time()
    pile = [(str(racine), 0)]
    while pile:
        dossier, niveau = pile.pop()
        if time.time() - debut > BUDGET_SCAN_S:
            return trouvees, au_dela, True, illisibles
        try:
            with os.scandir(dossier) as entrees:
                for e in entrees:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if niveau + 1 <= horizon:
                                pile.append((e.path, niveau + 1))
                            continue
                        if os.path.splitext(e.name)[1].lower() not in EXTENSIONS_BASE:
                            continue
                        if niveau <= profondeur:
                            trouvees.append(e.path)
                        else:
                            au_dela += 1
                    except OSError:
                        illisibles += 1     # une entree illisible est COMPTEE, jamais avalee
        except OSError:
            if niveau == 0:
                raise               # la racine elle-meme : son refus est dit
            illisibles += 1         # un sous-dossier refuse : il est COMPTE
    return trouvees, au_dela, False, illisibles


def bases_hors_depot(racines, profondeur=2):
    """(bases, etats) : les bases SQLite sous les racines hors depot.

    Trois etats, jamais confondus : ABSENT (le disque n'est pas monte),
    ILLISIBLE (le refus est dit, avec son Exception), LU. Ce qui depasse la
    profondeur est COMPTE (`au_dela`) : une borne dit combien.
    """
    bases, etats = [], []
    for racine in racines:
        chemin = Path(racine)
        try:
            os.stat(chemin)
        except FileNotFoundError:
            etats.append({"racine": str(racine), "etat": "ABSENT"})
            continue
        except OSError as e:
            etats.append({"racine": str(racine),
                          "etat": "ILLISIBLE (%s)" % type(e).__name__})
            continue
        try:
            if chemin.is_dir():
                trouvees, au_dela, tronque, illisibles = _parcours_borne(
                    chemin, profondeur)
                bases.extend(trouvees)
                etat = {"racine": str(racine), "etat": "LU",
                        "bases": len(trouvees), "au_dela": au_dela,
                        "au_dela_horizon": profondeur + MARGE_AU_DELA}
                if tronque:
                    etat["tronque"] = True
                if illisibles:
                    etat["sous_dossiers_illisibles"] = illisibles
                etats.append(etat)
            else:
                trouvees = ([str(chemin)]
                            if chemin.suffix.lower() in EXTENSIONS_BASE else [])
                bases.extend(trouvees)
                etats.append({"racine": str(racine), "etat": "LU",
                              "bases": len(trouvees), "au_dela": 0})
        except OSError as e:
            etats.append({"racine": str(racine),
                          "etat": "ILLISIBLE (%s)" % type(e).__name__})
    return bases, etats


def _textes_du_code():
    """{chemin relatif: texte} des sources que le code cite.

    Les bases hors depot sont designees par des CHEMINS ecrits dans le code ;
    sans les lire, %NOKIDO_DATA%\, E:/ ou D:/ restent invisibles.
    """
    if "textes" in _CACHE_TEXTES:
        return _CACHE_TEXTES["textes"]
    out = {}
    for zone in ZONES_SOURCE:
        dossier = ROOT / zone
        if not dossier.is_dir():
            continue
        for f in sorted(dossier.rglob("*")):
            if f.suffix.lower() not in EXTENSIONS_SOURCE or not f.is_file():
                continue
            try:
                out[f.relative_to(ROOT).as_posix()] = f.read_text(
                    encoding="utf-8", errors="replace")
            except OSError:
                ECARTES["fichiers_illisibles"] += 1
    _CACHE_TEXTES["textes"] = out
    return out


def _hors_depot():
    """(bases hors depot, etats des racines), memorises par les racines."""
    import time as _t
    temporaires = racines_temporaires()
    racines = sorted(set(racines_hors_depot(_textes_du_code())) | set(temporaires))
    cle = tuple(racines)
    if _CACHE_HORS.get("cle") != cle:
        _CACHE_HORS["cle"] = cle
        # BUDGET GLOBAL (21/10) : rouvrir C: a ramene les racines systeme citees par le code (C:/Windows,
        # C:/Program Files...), chacune parcourue jusqu'a BUDGET_SCAN_S -- l'audit depassait. Temporaires d'abord ;
        # ce qui reste apres le budget est DIT (NON_EXAMINE), jamais cache derriere un 0.
        t0, bases, etats = _t.time(), [], []
        for r in ordre_parcours(racines, temporaires):
            if _t.time() - t0 > BUDGET_HORS_DEPOT_S:
                etats.append({"racine": r, "etat": "NON_EXAMINE (budget global %.0f s depasse)" % BUDGET_HORS_DEPOT_S})
                continue
            b, e = bases_hors_depot([r])
            bases.extend(b)
            etats.extend(e)
        for s in sorted(_SYSTEME_ECARTES):
            etats.append({"racine": s, "etat": "ECARTE (dossier systeme, decision owner 21/10)"})
        for e in etats:
            e["temporaire"] = e.get("racine") in temporaires
        _CACHE_HORS["bases"], _CACHE_HORS["etats"] = bases, etats
    return _CACHE_HORS["bases"], _CACHE_HORS["etats"]


def _sans_doublon(chemins):
    """Les memes bases vues par deux chemins ne sont comptees qu'une fois."""
    vus, out = set(), []
    for c in chemins:
        try:
            cle = str(Path(c).resolve())
        except OSError:
            cle = str(c)
        if cle in vus:
            continue
        vus.add(cle)
        out.append(c)
    return out


def _bases_du_depot():
    """Reutilise l'enumeration du census plutot que de la reecrire (anti-dup)."""
    sys.path.insert(0, str(ROOT))
    from nokido_agent.tools.forge_savoir_census import bases
    return bases()


def _bases():
    """Les bases du depot ET celles qui sont hors depot, sans doublon."""
    hors, _etats = _hors_depot()
    return _sans_doublon(list(_bases_du_depot()) + list(hors))


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


def _balaie_l_index(plan, table):
    """`SCAN t USING ... INDEX` = parcours d'un index ENTIER.

    `SELECT COUNT(*)` sans WHERE tombe la-dedans : il lit l'index complet
    (10,5 M d'entrees) au lieu de la table. Ce n'est pas une table balayee,
    mais c'est une lecture MASSIVE — et l'ancien rapport la comptait comme
    saine.
    """
    m = re.search(r"\bSCAN\s+%s\b(?P<suite>[^|]*)" % re.escape(table), plan, re.I)
    if not m:
        return False
    suite = m.group("suite").upper()
    return "USING" in suite and "INDEX" in suite


def _a_une_limite(sql):
    """Une requete bornee par LIMIT lit peu : ce n'est pas une lecture massive."""
    return bool(re.search(r"\bLIMIT\b", sql, re.I))


def _entree_index_complet(conn, sql, table, origine, plan):
    """L'index lu ENTIER que le plan montre, ou None.

    `SELECT COUNT(*)` sans WHERE tombe la-dedans : il lit l'index complet
    (10,5 M d'entrees) au lieu de la table. Ce n'est pas une table balayee,
    mais c'est une lecture MASSIVE — et l'ancien rapport la comptait comme
    saine.
    """
    if _a_une_limite(sql) or not _balaie_l_index(plan, table):
        return None
    if _est_virtuelle(conn, table):
        return None
    return {"table": table, "origine": origine, "origines": [origine],
            "sql": re.sub(r"\s+", " ", sql), "plan": plan}


def _entree_scan(conn, plan, sql, table, origine, lignes):
    """Le balayage de TABLE que le plan montre, ou None."""
    if not _balaie_la_table(plan, table):
        return None
    if _est_virtuelle(conn, table):
        return None      # FTS5 : non indexable, et le SCAN y est normal
    col = _colonne_du_where(sql, _colonnes(conn, table))
    return {
        "table": table, "lignes_max": lignes, "colonne": col,
        "origine": origine,
        # AUCUN SITE PERDU : dedupliquer par (table, colonne) ne doit pas
        # faire disparaitre les AUTRES fichier:ligne du meme balayage.
        "origines": [origine],
        # SQL COMPLET : la version tronquee a 150 chars etait rejouee telle
        # quelle par `--apply`, d'ou « incomplete input » et « no such column:
        # c » — 3 index sur 5 declares « non verifies » alors qu'ils n'avaient
        # jamais ete testes. L'affichage tronque, la mesure non.
        "sql": re.sub(r"\s+", " ", sql),
        "actionnable": bool(col),
        "index_suggere": (
            'CREATE INDEX idx_%s_%s ON %s(%s);' % (
                table, re.sub(r"\W+", "_", col)[:28].strip("_"), table, col)
            if col else "(predicat compose ou alias — a examiner a la"
                        " main, aucun index simple ne s'en deduit)")}


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


def _tri_rowid_borne(conn, sql, table):
    """Vrai si la requete parcourt `table` A REBOURS sur son rowid et s'arrete au LIMIT : O(n), pas O(table).

    Mesure 21/10 (passage reel) : `... FROM network_log ORDER BY id DESC LIMIT 10` sortait en SCAN sur 2,1 M de
    lignes. Conditions : aucun WHERE (un filtre peut parcourir loin), un LIMIT, et un ORDER BY sur `rowid` ou sur la
    SEULE colonne INTEGER PRIMARY KEY (alias de rowid)."""
    s = " ".join(sql.split())
    if re.search(r"\bWHERE\b", s, re.I) or not re.search(r"\bLIMIT\b", s, re.I):
        return False
    m = re.search(r"\bORDER\s+BY\s+(\w+)(\s+(ASC|DESC))?\s+LIMIT\b", s, re.I)
    if not m:
        return False
    col = m.group(1).lower()
    if col in ("rowid", "_rowid_", "oid"):
        return True
    try:
        pk = [r for r in conn.execute("PRAGMA table_info(%s)" % table) if r[5]]
    except sqlite3.Error:  # muet-ok : schema illisible = pas de preuve de borne -> la requete RESTE comptee en balayage
        return False
    return len(pk) == 1 and pk[0][1].lower() == col and str(pk[0][2]).upper() == "INTEGER"


def _collecter(conn, requetes, grosses, bornes=None):
    """(scans, index_complets) mesures sur UNE base ; `bornes` recoit les parcours a rebours limites (dits).

    Un scan est deduplique par (table, colonne) mais garde TOUS ses sites :
    dedupliquer ne doit pas faire disparaitre les autres `fichier:ligne`.
    """
    vus = {}           # (table, colonne) -> entree de scan
    complets = {}      # (table, sql)    -> entree d'index lu entier
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
            origine = "%s:%d" % (fichier, ligne)
            if _tri_rowid_borne(conn, sql, t):
                if bornes is not None:
                    bornes.append({"table": t, "origine": origine, "sql": re.sub(r"\s+", " ", sql)})
                continue
            entree = _entree_index_complet(conn, sql, t, origine, plan)
            if entree is not None:
                cle = (t, entree["sql"])
                deja = complets.get(cle)
                if deja is None:
                    complets[cle] = entree
                elif origine not in deja["origines"]:
                    deja["origines"].append(origine)
                continue
            entree = _entree_scan(conn, plan, sql, t, origine, grosses[t])
            if entree is None:
                continue
            cle = (t, entree["colonne"])
            deja = vus.get(cle)
            if deja is None:
                vus[cle] = entree
            elif origine not in deja["origines"]:
                deja["origines"].append(origine)
    scans = list(vus.values())
    for entree in scans:
        entree["origines"] = sorted(entree["origines"])
        entree["origine"] = entree["origines"][0]
    scans.sort(key=lambda s: (not s["actionnable"], -s["lignes_max"]))
    for entree in complets.values():
        entree["origines"] = sorted(entree["origines"])
        entree["origine"] = entree["origines"][0]
    return scans, sorted(complets.values(), key=lambda e: (e["table"], e["origine"]))


def _fiche_base(chemin, requetes, seuil):
    """La fiche d'UNE base : scans, index_complets, etat de lecture."""
    rel = str(Path(chemin).relative_to(ROOT)) if str(chemin).startswith(str(ROOT)) \
        else str(chemin)
    fiche = {"base": rel.replace("\\", "/"), "scans": [], "index_complets": [], "bornes": [],
             "etat": "lu"}
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % str(chemin).replace("\\", "/"),
                               uri=True)
        grosses = _tables_grosses(conn, seuil)
    except sqlite3.Error as e:
        fiche["etat"] = "ILLISIBLE (%s)" % type(e).__name__
        return fiche
    fiche["tables_volumineuses"] = grosses
    if not grosses:
        return fiche
    scans, complets = _collecter(conn, requetes, grosses, fiche["bornes"])
    fiche["scans"] = scans
    fiche["index_complets"] = complets
    return fiche


def auditer(base_filtre=None, seuil=MIN_LIGNES):
    requetes = _requetes_du_code()
    rapport = {"seuil_lignes": seuil, "requetes_lues": len(requetes),
               "non_analysables": sum(1 for r in requetes if not r[3]),
               # Un NOMBRE ne dit pas OU : le site de chaque requete non
               # analysable est ce qu'il faut aller corriger.
               "non_analysables_sites": sorted(
                   "%s:%d" % (f, l) for _s, f, l, an in requetes if not an),
               "racines_hors_depot": [],
               "bases": []}
    try:
        _hors, etats = _hors_depot()
        rapport["racines_hors_depot"] = etats
    except OSError as e:
        rapport["racines_hors_depot"] = [
            {"racine": "*", "etat": "ILLISIBLE (%s)" % type(e).__name__}]
    for chemin in _bases():
        rel = str(Path(chemin).relative_to(ROOT)) if str(chemin).startswith(str(ROOT)) \
            else str(chemin)
        if base_filtre and base_filtre not in rel.replace("\\", "/"):
            continue
        rapport["bases"].append(_fiche_base(chemin, requetes, seuil))
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


def _afficher_portee(rapport):
    """La portee : les racines hors depot, et les sites non analysables."""
    etats = rapport.get("racines_hors_depot") or []
    if etats:
        print("\n=== HORS DEPOT — %d racine(s) citee(s) par le code ===" % len(etats))
        for e in etats:
            ligne = "  %-44s %s" % (e.get("racine", "?"), e.get("etat", "?"))
            if e.get("etat") == "LU":
                ligne += "  (%d base(s) dans la borne, %d au-dela)" % (
                    e.get("bases", 0), e.get("au_dela", 0))
                if e.get("tronque"):
                    ligne += "  [COMPTE TRONQUE]"
            print(ligne)
    sites = rapport.get("non_analysables_sites") or []
    if sites:
        print("Requetes non analysables : %d site(s) — %s"
              % (len(sites), ", ".join(sites[:8])
                 + (" ..." if len(sites) > 8 else "")))


def _afficher_base(fiche):
    """Affiche la fiche d'une base ; rend (scans, actionnables)."""
    if fiche["etat"] != "lu":
        print("  %-42s %s" % (fiche["base"], fiche["etat"]))
        return 0, 0
    scans = fiche.get("scans") or []
    if not scans and not fiche.get("index_complets"):
        return 0, 0
    print("  %s" % fiche["base"])
    for e in fiche.get("index_complets") or []:
        print("     INDEX COMPLET %-18s %-22s %s"
              % (e["table"], e["origine"], e["sql"][:56]))
    total = actionnables = 0
    for s in scans:
        total += 1
        if not s["actionnable"]:
            continue
        actionnables += 1
        print("     SCAN %-20s ~%9d lignes  filtre sur %-18s  %s"
              % (s["table"], s["lignes_max"], s["colonne"], s["origine"]))
        # (le SQL est stocke ENTIER dans le rapport ; ici on n'affiche que
        #  l'essentiel — tronquer la MESURE etait le defaut, pas l'affichage)
        print("          %s" % s["index_suggere"])
    reste = sum(1 for s in scans if not s["actionnable"])
    if reste:
        print("     (+ %d balayage(s) a predicat compose : aucun index simple"
              " ne s'en deduit, voir le rapport)" % reste)
    return total, actionnables


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--portee" in argv:
        # Mode COURT (21/10) : parcours hors depot seul, aucune base ouverte, aucune requete -- lancable sous
        # LaForgeTrusted (trusted_script, borne 110 s), le compte a qui l'owner a ouvert E:/LaForge_tiede et
        # E:/nokido_backups. Un etat ILLISIBLE reste ILLISIBLE.
        bases, etats = _hors_depot()
        print(json.dumps({"racines_hors_depot": etats, "bases": len(bases)}, ensure_ascii=False))
        return 0
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
        n_scan, n_actionnable = _afficher_base(f)
        total += n_scan
        actionnables += n_actionnable
    print("\n%d balayage(s) mesure(s), dont %d avec un index simple identifiable."
          % (total, actionnables))
    _afficher_portee(r)

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

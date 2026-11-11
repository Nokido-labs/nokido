#!/usr/bin/env python3
"""forge_savoir_census — OU vit le savoir de Nokido, et par quoi est-il ATTEIGNABLE.

__FORGE_COLOR__ = "cognition/census-du-savoir"

POURQUOI
========
Mesure du 2026-09-03 : cherchant si les RFC etaient ingerees, trois sondes FTS
independantes n'ont rien rendu — alors que l'owner se souvient d'une ingestion par
le workflow SearXNG/crawl4ai. Impossible de trancher, parce que PERSONNE ne sait
quelle est la COUVERTURE de l'index lexical : chercher dans un index partiel sans
le savoir, c'est produire des « absences » qui n'en sont pas.

Le probleme n'est pas les RFC, il est general et deja consigne (mémoire 2026-09-02 :
753 fiches memoire, ~45 indexees, adressabilite du reste INCONNUE). Il y a plusieurs
supports — SQLite RAG, index lexical, vecteurs, fiches markdown, SSoT, blackboard,
transcripts — et un savoir STOCKE mais NON INTERROGEABLE est perdu en pratique.

CE QUE CE MODULE FAIT — ET NE FAIT PAS
======================================
LECTURE SEULE, strictement : aucun ANALYZE, aucune ingestion, aucune ecriture dans
les bases. L'ordre owner du 2026-09-02 est explicite : census d'abord, attribution
ensuite, ingestion apres. On ne repare pas ce qu'on n'a pas fini de compter.

Il ne compte PAS par balayage (`COUNT(*)` sur 22,8 Go a deja fait tomber le hub deux
fois le 2026-08-23) : il lit `MAX(rowid)`, instantane, et le declare comme une BORNE
SUPERIEURE, pas comme un compte exact — les suppressions ne rendent pas leur rowid.

TROIS ETATS pour l'adressabilite, jamais deux :
  ATTEIGNABLE   un terme temoin extrait du document le retrouve par MATCH
  INATTEIGNABLE le document existe mais aucun terme temoin ne le retrouve
  INDETERMINE   on n'a pas pu tester (table absente, lecture refusee, temoin vide)

Usage : LAFORGE_PYTHON tools/forge_savoir_census.py [--echantillon N]
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

from dataclasses import asdict, is_dataclass
from app.forge_mesure import Mesure

ROOT = Path(__file__).resolve().parent.parent
SORTIE = ROOT / "sandbox" / "census_savoir.json"
EXCLUS = ("sandbox", "archive", "_attic", "node_modules", ".git", "RAG_plain_bak")


def _emit(etape: str, i: int, n: int) -> None:
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_job_progress import emit
        emit(etape, index=i, total=n)
    except Exception:  # noqa: BLE001  # muet-ok : progression != census
        # Le marqueur va sur la ligne du HANDLER, pas sur le `pass` : le gate lit
        # l'except. Muet assume ici, et seulement ici : perdre la barre de
        # progression ne doit pas faire tomber une mesure de plusieurs minutes.
        pass


def _ouvrir(p: Path) -> sqlite3.Connection | None:
    try:
        return sqlite3.connect("file:%s?mode=ro" % p.as_posix(), uri=True, timeout=10)
    except sqlite3.Error:
        return None


def bases() -> list[Path]:
    out = []
    for f in ROOT.rglob("*.db"):
        rel = str(f.relative_to(ROOT)).replace("\\", "/")
        if any(rel.split("/")[0] == e for e in EXCLUS):
            continue
        out.append(f)
    return sorted(out, key=lambda p: -p.stat().st_size)


# Tables INTERNES de FTS5 : leur rowid est un identifiant encode, pas un compte de
# lignes. Mesure 2026-09-03 : `rag_fts_data` sortait a ~4 672 924 418 050, chiffre
# affiche comme une cardinalite. Un nombre faux est pire qu'une absence de nombre.
_FTS_INTERNES = ("_data", "_idx", "_docsize", "_config", "_content", "_stat")


def tables(conn: sqlite3.Connection) -> list[tuple[str, int | None]]:
    """(table, borne superieure de lignes). None = ILLISIBLE ou non comptable,
    jamais 0 par defaut : un zero invente est un faux negatif indetectable."""
    res = []
    try:
        noms = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    except sqlite3.Error:
        return res
    for n in noms:
        if any(n.endswith(s) for s in _FTS_INTERNES):
            res.append((n, None))   # rowid encode : non comptable, pas vide
            continue
        try:
            v = conn.execute('SELECT MAX(rowid) FROM "%s"' % n).fetchone()[0]
            res.append((n, int(v) if v is not None else 0))
        except sqlite3.Error:
            res.append((n, None))   # illisible : PAS zero
    return res


def couverture_par_jointure(conn: sqlite3.Connection, plafond: int = 5000) -> dict:
    """Couverture MESUREE, pas estimee : DEUX PASSES sur la cle.

    Le nom dit encore « jointure » parce que ses appelants l'appellent ainsi ;
    l'implementation, elle, n'en fait plus AUCUNE depuis le 2026-09-03 — un
    `LEFT JOIN` sur une colonne de table virtuelle FTS5 a lu 2 195 Go en 41 min
    sans rendre une ligne (aucun B-tree, et `CREATE INDEX` y est refuse).

    Deux tentatives par la recherche ont donne deux ARTEFACTS differents :
      - 2026-09-01 : comparaison des `rowid` de deux index -- ils n'ont pas le
        meme espace, le resultat « 0/200 » ne voulait rien dire ;
      - 2026-09-03 : temoin unique + LIMIT -- un mot frequent noie le document
        cible, qui est declare absent alors qu'il est indexe.

    La methode fiable est celle que `rebuild_fts_index` utilise DEJA pour savoir
    quoi reconstruire : `LEFT JOIN rag_fts ON f.chunk_id = rc.id`. On ne compte
    pas tout (balayage = hub a terre, deux fois deja) : on borne par `plafond` et
    on rapporte « au moins N » plutot qu'un total invente.
    """
    out: dict = {"methode": "deux passes lineaires + set en RAM", "plafond": plafond}
    # PAS DE JOINTURE. `rag_fts.chunk_id` est une colonne d'une table VIRTUELLE
    # FTS5 : aucun B-tree dessus, et SQLite refuse CREATE INDEX sur une table
    # virtuelle. Un `LEFT JOIN ... ON f.chunk_id = rc.id` rescanne donc TOUT le
    # FTS pour CHAQUE ligne de rag_chunks. Mesure 2026-09-03, payee en direct :
    # 41 min de CPU a 98 % et **2 195 Go lus** avant d'etre arrete, sans un seul
    # resultat. C'est aussi la forme qui a tue le hub le 23/08 (GROUP BY) et ce
    # soir (COUNT sur rag_fts).
    #
    # Deux passes SEQUENTIELLES a la place : les identifiants du FTS dans un set
    # (~2 M x 40 o = 80 Mo, tenable), puis rag_chunks en streaming avec un test
    # d'appartenance en O(1). Et la ventilation en QUATRE QUADRANTS se lit dans
    # la meme passe, puisque `embedding IS NULL` est sur la ligne : ce qui manque
    # aux DEUX index est le seul angle mort reel — un chunk absent du vectoriel
    # mais present en lexical reste atteignable par les mots exacts.
    try:
        indexes = {r[0] for r in conn.execute(
            "SELECT chunk_id FROM rag_fts") if r[0] is not None}
        out["fts_ids_lus"] = len(indexes)
    except sqlite3.Error as e:
        out["etat"] = "INDETERMINE (lecture rag_fts: %s)" % type(e).__name__
        return out

    quad = {"vec_et_fts": 0, "vec_seul": 0, "fts_seul": 0, "aucun_des_deux": 0}
    manquants, vus, orphelins = 0, 0 , []
    try:
        cur = conn.execute(
            "SELECT id, embedding IS NOT NULL, source FROM rag_chunks "
            "WHERE text IS NOT NULL AND LENGTH(text) > 20")
        while True:
            lot = cur.fetchmany(20000)
            if not lot:
                break
            for _id, _vec, _src in lot:
                vus += 1
                dans_fts = _id in indexes
                if _vec and dans_fts:
                    quad["vec_et_fts"] += 1
                elif _vec:
                    quad["vec_seul"] += 1
                elif dans_fts:
                    quad["fts_seul"] += 1
                else:
                    quad["aucun_des_deux"] += 1
                    if len(orphelins) < 12:
                        orphelins.append((_src or "")[:80])
                if not dans_fts:
                    manquants += 1
    except sqlite3.Error as e:
        out["etat"] = "INDETERMINE (lecture rag_chunks: %s)" % type(e).__name__
        out["quadrants_partiels"] = quad
        return out
    out["chunks_vus"] = vus
    out["quadrants"] = quad
    out["angle_mort_pct"] = round(100.0 * quad["aucun_des_deux"] / vus, 2) if vus else None
    out["orphelins_exemples"] = orphelins
    # ENTREES A CLE NULLE. Mesure 2026-08-23 : 54 264 lignes de l'index sans clef
    # de rattachement. La jointure les ignore, donc leurs chunks ressortent
    # « manquants » alors qu'ils SONT indexes — c'est ce qui avait produit un
    # residu negatif, seule chose qui ait rendu l'erreur visible. On le compte au
    # lieu de le subir : sans ce chiffre, `manquants_vus` est une borne haute
    # potentiellement tres surevaluee.
    try:
        out["index_sans_clef"] = int(conn.execute(
            "SELECT COUNT(*) FROM (SELECT 1 FROM rag_fts WHERE chunk_id IS NULL "
            "LIMIT ?)", (plafond,)).fetchone()[0])
    except sqlite3.Error as e:
        out["index_sans_clef"] = None
        out["index_sans_clef_etat"] = "INDETERMINE (%s)" % type(e).__name__
    out["manquants_vus"] = manquants
    out["sature"] = False   # passe complete : plus de plafond, plus de troncature
    _nul = out.get("index_sans_clef")
    _avert = ""
    if _nul:
        _avert = (" | ATTENTION : %d entree(s) d'index SANS CLEF — leurs chunks "
                  "sont comptes 'hors index' a tort, ce chiffre est une borne HAUTE"
                  % _nul)
    out["etat"] = ("%d chunk(s) hors index lexical sur %d — compte EXACT (passe "
                   "complete)" % (manquants, vus)) + _avert
    return out


def couverture_fts(conn: sqlite3.Connection, echantillon: int = 25) -> dict:
    """Un document tire au sort est-il RETROUVABLE par l'index lexical ?

    On ne compare PAS les rowid de deux tables : mesure du 2026-09-01, deux index
    n'ont pas le meme espace de rowid (`content=` externe vs autonome) et la
    comparaison rend un ARTEFACT. On compare donc par le CONTENU, avec un terme
    temoin tire du document lui-meme.
    """
    out = {"testes": 0, "atteignables": 0, "inatteignables": 0, "indetermines": 0,
           "exemples_rates": []}
    try:
        conn.execute("SELECT 1 FROM rag_fts LIMIT 1")
        lignes = conn.execute(
            "SELECT source, text FROM rag_chunks WHERE text IS NOT NULL "
            "AND length(text) > 120 LIMIT ?", (echantillon * 4,)).fetchall()
    except sqlite3.Error as e:
        out["erreur"] = type(e).__name__
        return out
    import random
    random.shuffle(lignes)
    for source, texte in lignes[:echantillon]:
        out["testes"] += 1
        # TEMOIN CONJONCTIF, et non un mot unique. Mesure 2026-09-03 : un temoin
        # seul comme « CONSOLIDATION » ou « ingested » est TRES frequent dans les
        # chunks session:* ; le document cible sortait alors au-dela du LIMIT et
        # etait declare INATTEIGNABLE alors qu'il est indexe. La sonde mesurait la
        # frequence du mot, pas la couverture de l'index — et le resultat
        # m'arrangeait, ce qui aurait du suffire a le rendre suspect.
        mots = list(dict.fromkeys(re.findall(r"[A-Za-zÀ-ÿ]{8,20}", texte or "")))
        if not mots:
            out["indetermines"] += 1
            continue
        # 3 mots longs distincts = requete selective ; a defaut, ce qu'on a.
        choisis = sorted(mots, key=len, reverse=True)[:3]
        requete = " AND ".join('"%s"' % m for m in choisis)
        try:
            q = conn.execute(
                "SELECT source FROM rag_fts WHERE rag_fts MATCH ? LIMIT 200",
                (requete,)).fetchall()
        except sqlite3.Error:
            out["indetermines"] += 1
            continue
        if any((r[0] or "") == source for r in q):
            out["atteignables"] += 1
        else:
            out["inatteignables"] += 1
            if len(out["exemples_rates"]) < 8:
                out["exemples_rates"].append({"source": (source or "")[:70],
                                              "temoins": choisis,
                                              "retours": len(q)})
    return out


def supports_fichiers() -> dict:
    """Savoirs qui ne vivent PAS en base : fiches, SSoT, docs."""
    # PAS `Path.home()` : sous un compte de service, HOME vaut C:\Users\Default et le
    # dossier ressort « absent » alors qu'il contient 753 fiches. Mesure 2026-09-03 :
    # l'outil ecrit pour detecter ce piege l'a reproduit dans sa propre sonde. On
    # essaie les emplacements CONNUS et on declare l'echec de lecture comme tel.
    candidats = [Path(os.environ["LAFORGE_MEMORY_DIR"])] if os.environ.get(
        "LAFORGE_MEMORY_DIR") else []
    candidats += [
        Path(r"%USERPROFILE%/.claude/projects/C--Users-user-Script-python-IA/memory"),
        Path.home() / ".claude" / "projects" / "C--Users-user-Script-python-IA" / "memory",
    ]
    # Selection par TENTATIVE DE LECTURE, jamais par `is_dir()` : celui-ci rend
    # False aussi bien pour « absent » que pour « acces refuse ». Le repli
    # `candidats[-1]` tombait alors sur le chemin derive de HOME
    # (C:\Users\Default sous un compte de service), qui lui n'existe pas — et un
    # ILLISIBLE ressortait en « absent ». Mesure 2026-09-03 : 753 fiches
    # declarees absentes par ce chemin, dans l'outil meme qui mesure la
    # couverture du savoir. On retient le premier candidat LISIBLE ; a defaut,
    # celui qui a porte la premiere erreur, pour que l'etat rapporte parle du bon
    # dossier.
    mem, _mem_err = None, None
    for _c in candidats:
        try:
            next(_c.iterdir(), None)
        except OSError as _e:
            if _mem_err is None:
                _mem_err = _c
            continue
        mem = _c
        break
    if mem is None:
        mem = _mem_err or candidats[-1]
    out = {}
    for nom, dossier, motif in (("fiches_memoire", mem, "*.md"),
                                ("ssot_docs", ROOT / "docs", "*_state.json"),
                                ("skills", ROOT / "docs" / "skills", "**/SKILL.md")):
        # `is_dir()` rend False AUSSI quand l'acces est refuse. Ecrire « absent »
        # dans ce cas est un faux negatif : mesure 2026-09-03, les 753 fiches
        # memoire ont ete declarees absentes DEUX FOIS de suite par cet outil, une
        # fois pour un chemin derive de HOME, une fois pour l'ACL. Le compte de
        # service ne voit pas le profil owner : il faut le DIRE, pas conclure.
        try:
            listing = list(dossier.iterdir())
        except FileNotFoundError:
            out[nom] = {"chemin": str(dossier), "fichiers": 0, "etat": "absent"}
            continue
        except OSError as e:
            out[nom] = {"chemin": str(dossier), "fichiers": None,
                        "etat": "ILLISIBLE (%s) — relancer en console OWNER"
                                % type(e).__name__}
            continue
        try:
            n = len(list(dossier.glob(motif)))
        except OSError as e:
            out[nom] = {"chemin": str(dossier), "fichiers": None,
                        "etat": "ILLISIBLE au glob (%s)" % type(e).__name__}
            continue
        out[nom] = {"chemin": str(dossier), "fichiers": n, "etat": "lu",
                    "entrees_totales": len(listing)}
    return out


# ======================================================================
# ATLAS DES DONNEES (P1_atlas_des_donnees_20261021, premiere livraison)
# ======================================================================
# Par magasin, des statuts DISTINCTS, jamais fusionnes en un « OK » :
#   declare      le magasin est-il nomme par une source canonique ?
#   localise     le chemin existe-t-il (present / absent / ILLISIBLE) ?
#   ouvert       ouverture lecture seule + lecture de sqlite_master ?
#   requete      requete representative verifiee par EXPLAIN QUERY PLAN
#                (EXPLAIN n'execute rien : aucun balayage, meme sur rag_chunks)
#   integrite    quick_check, JAMAIS au-dessus de 1 Go (fenetre de maintenance)
#   fraicheur    age de la derniere modification du fichier (mtime), dit tel quel
# Absent ou illisible est DIT ; rien n'est deduit. Aucune base centrale, aucun
# index cree, aucun PRAGMA d'ecriture.

SEUIL_INTEGRITE_OCTETS = 1024 ** 3
FRAICHEUR_PERIME_JOURS = 30.0
NON_CONTROLEE_GROS = "integrite NON controlee (fenetre de maintenance)"
RACINES_HORS_DEPOT = ("%NOKIDO_DATA%\", "E:/LaForge_tiede", "D:/", "F:/Grodata")
_ID_SQL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _chemins_canoniques() -> list[dict]:
    """Magasins declares par app/forge_db_path.py (source canonique)."""
    out = []
    try:
        from app import forge_db_path as fdp
    except Exception as e:  # noqa: BLE001  # muet-ok : dit dans la declaration
        return [{"nom": "forge_db_path", "chemin": None,
                 "declare_par": "app/forge_db_path.py INDISPONIBLE (%s)" % type(e).__name__}]
    cand = [("rag", "db_path", ("rag_chunks", "source")),
            ("authority", "authority_path", None),
            ("m2m", "m2m_path", None),
            ("tasks", "tasks_path", None)]
    for nom, fn, req in cand:
        try:
            ch = getattr(fdp, fn)()
        except Exception as e:  # noqa: BLE001  # muet-ok : dit
            out.append({"nom": nom, "chemin": None,
                        "declare_par": "forge_db_path.%s ERREUR (%s)" % (fn, type(e).__name__)})
            continue
        out.append({"nom": nom, "chemin": str(ch), "requete": req,
                    "declare_par": "app/forge_db_path.py:%s" % fn})
    try:
        for j in fdp.journaux_connus():
            out.append({"nom": "journal_%s" % j, "chemin": str(fdp.journal_path(j)),
                        "declare_par": "app/forge_db_path.py:journal_path"})
    except Exception as e:  # noqa: BLE001  # muet-ok : dit
        out.append({"nom": "journaux", "chemin": None,
                    "declare_par": "journaux_connus ERREUR (%s)" % type(e).__name__})
    return out


def _magasins_hors_depot() -> list[dict]:
    return [{"nom": "racine:%s" % r, "chemin": r,
             "declare_par": "ordre owner P1_atlas (racine hors depot)"}
            for r in RACINES_HORS_DEPOT]


def _etat_chemin(chemin: str) -> tuple[str, int | None, float | None]:
    """(present|absent|ILLISIBLE, octets, mtime). Acces refuse != absent."""
    try:
        st = os.stat(chemin)
    except FileNotFoundError:
        return "absent", None, None
    except OSError as e:
        return "ILLISIBLE (%s)" % type(e).__name__, None, None
    return "present", st.st_size, st.st_mtime


def requete_representative(conn: sqlite3.Connection, table: str, colonne: str) -> dict:
    """EXPLAIN QUERY PLAN de `SELECT * FROM table WHERE colonne = ?`. N'execute pas."""
    if not (_ID_SQL.match(table or "") and _ID_SQL.match(colonne or "")):
        return {"statut": "non verifiee (identifiant refuse)"}
    try:
        plan = [str(r[-1]) for r in conn.execute(
            'EXPLAIN QUERY PLAN SELECT * FROM "%s" WHERE "%s" = ?' % (table, colonne), ("x",))]
    except sqlite3.Error as e:
        return {"statut": "non verifiee (%s: %s)" % (type(e).__name__, e)}
    txt = " | ".join(plan)
    if "SEARCH" in txt and "USING" in txt:
        return {"statut": "verifiee (index)", "plan": plan}
    return {"statut": "SANS INDEX pour la requete representative", "plan": plan}


def integrite(conn: sqlite3.Connection | None, octets: int | None) -> str:
    if conn is None:
        return "integrite non controlee (base non ouverte)"
    if octets is not None and octets > SEUIL_INTEGRITE_OCTETS:
        return NON_CONTROLEE_GROS
    try:
        rep = conn.execute("PRAGMA quick_check").fetchone()
    except sqlite3.Error as e:
        return "integrite ECHEC du controle (%s)" % type(e).__name__
    if rep and rep[0] == "ok":
        return "integrite controlee: ok"
    return "integrite controlee: CORROMPUE (%s)" % (rep[0] if rep else "?")


def _fraicheur(mtime: float | None, maintenant: float) -> str:
    if mtime is None:
        return "non controlee"
    jours = max(0.0, (maintenant - mtime) / 86400.0)
    pre = "PERIME" if jours > FRAICHEUR_PERIME_JOURS else "frais"
    return "%s: modifie il y a %.1f j (mtime du fichier)" % (pre, jours)


def evaluer_magasin(decl: dict, maintenant: float | None = None) -> dict:
    """Statuts distincts d'un magasin. decl: nom, chemin, declare_par, requete=(table, col)."""
    maintenant = time.time() if maintenant is None else maintenant
    fiche = {"nom": decl.get("nom"), "chemin": decl.get("chemin"),
             "declare": ("declare (%s)" % decl["declare_par"]) if decl.get("declare_par")
             else "NON declare", "lacunes": []}
    ch = decl.get("chemin")
    if not ch:
        fiche.update(localise="chemin inconnu", ouvert="non applicable",
                     requete="non verifiee", integrite="non controlee",
                     fraicheur="non controlee",
                     integrite_mesure=Mesure("ABSENT", source=decl.get("nom") or "?", motif="chemin non renseigne"),
                     fraicheur_mesure=Mesure("ABSENT", source=decl.get("nom") or "?", motif="chemin non renseigne"))
        fiche["lacunes"].append("chemin non resolu")
        return fiche
    etat, octets, mtime = _etat_chemin(ch)
    fiche["localise"] = etat
    fiche["octets"] = octets
    if etat != "present":
        fiche.update(ouvert="non applicable", requete="non verifiee",
                     integrite="non controlee", fraicheur="non controlee",
                     integrite_mesure=Mesure("ABSENT" if etat == "absent" else "ILLISIBLE",
                                             source=ch, motif="etat chemin : %s" % etat),
                     fraicheur_mesure=Mesure("ABSENT" if etat == "absent" else "ILLISIBLE",
                                             source=ch, motif="etat chemin : %s" % etat))
        fiche["lacunes"].append("localise: %s" % etat)
        return fiche
    if os.path.isdir(ch):
        fr_str = _fraicheur(mtime, maintenant)
        is_perime = fr_str.startswith("PERIME")
        fiche.update(ouvert="non applicable (repertoire)", requete="non verifiee",
                     integrite="non applicable (repertoire)",
                     fraicheur=fr_str,
                     integrite_mesure=Mesure("NON_APPLICABLE", source=ch, motif="repertoire"),
                     fraicheur_mesure=Mesure("STALE" if is_perime else "VALEUR",
                                             valeur=mtime, source=ch,
                                             temoin_positif=True, mesure_le=maintenant,
                                             motif=fr_str))
        return fiche
    conn = _ouvrir(Path(ch))
    ok = False
    if conn is None:
        fiche["ouvert"] = "NON (ouverture lecture seule refusee)"
    else:
        try:
            conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
            ok = True
            fiche["ouvert"] = "oui (lecture seule)"
        except sqlite3.Error as e:
            fiche["ouvert"] = "NON (%s)" % type(e).__name__
    req = decl.get("requete")
    if ok and req:
        r = requete_representative(conn, req[0], req[1])
        fiche["requete"], fiche["plan"] = r["statut"], r.get("plan")
    elif ok:
        fiche["requete"] = "non declaree (aucune requete representative)"
    else:
        fiche["requete"] = "non verifiee (base non ouverte)"
    int_str = integrite(conn if ok else None, octets)
    fr_str = _fraicheur(mtime, maintenant)
    fiche["integrite"] = int_str
    fiche["fraicheur"] = fr_str

    # Mesure typee integrite
    if not ok:
        m_int = Mesure("ILLISIBLE", source=ch, motif=fiche["ouvert"])
    elif int_str == "integrite controlee: ok":
        m_int = Mesure("VALEUR", valeur="ok", temoin_positif=True, source=ch, mesure_le=maintenant)
    elif int_str == NON_CONTROLEE_GROS:
        m_int = Mesure("NON_APPLICABLE", source=ch, motif=NON_CONTROLEE_GROS)
    else:
        m_int = Mesure("ILLISIBLE", source=ch, motif=int_str)
    fiche["integrite_mesure"] = m_int

    # Mesure typee fraicheur
    if mtime is None:
        m_fr = Mesure("ILLISIBLE", source=ch, motif="mtime absent")
    elif fr_str.startswith("PERIME"):
        m_fr = Mesure("STALE", valeur=mtime, source=ch, mesure_le=maintenant, motif=fr_str)
    else:
        m_fr = Mesure("VALEUR", valeur=mtime, temoin_positif=True, source=ch, mesure_le=maintenant, motif=fr_str)
    fiche["fraicheur_mesure"] = m_fr
    if conn is not None:
        conn.close()
    for cle in ("ouvert", "requete", "integrite"):
        v = fiche[cle]
        if (v.startswith(("NON", "SANS", "non", "integrite non", "integrite NON",
                          "integrite ECHEC")) or "CORROMPUE" in v):
            fiche["lacunes"].append("%s: %s" % (cle, v))
    if fiche["fraicheur"].startswith("PERIME"):
        fiche["lacunes"].append("fraicheur: " + fiche["fraicheur"])
    return fiche


def _serialiser_mesures(obj):
    if is_dataclass(obj):
        return asdict(obj)
    raise TypeError("Type non serialisable en JSON : %r" % type(obj))


def atlas_donnees(declarations: list[dict] | None = None) -> dict:
    """Atlas par magasin + liste des lacunes. Aucune ecriture, aucun index."""
    decls = declarations if declarations is not None else (
        _chemins_canoniques() + _magasins_hors_depot())
    magasins = [evaluer_magasin(d) for d in decls]
    lacunes = ["%s: %s" % (m["nom"], x) for m in magasins for x in m["lacunes"]]
    # Serialisation propre pour compatibilite JSON complete
    magasins_json = []
    for m in magasins:
        item = dict(m)
        if is_dataclass(item.get("integrite_mesure")):
            item["integrite_mesure"] = asdict(item["integrite_mesure"])
        if is_dataclass(item.get("fraicheur_mesure")):
            item["fraicheur_mesure"] = asdict(item["fraicheur_mesure"])
        magasins_json.append(item)
    return {"genere": time.strftime("%Y-%m-%d %H:%M:%S"), "magasins": magasins_json,
            "lacunes": lacunes}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--atlas" in argv:
        print(json.dumps(atlas_donnees(), indent=1, ensure_ascii=False, default=_serialiser_mesures))
        return 0
    ech = 25
    if "--echantillon" in argv:
        try:
            ech = int(argv[argv.index("--echantillon") + 1])
        except (ValueError, IndexError):
            # PAS muet : un argument mal forme qui retombe en silence sur le
            # defaut fait croire a l'appelant que sa valeur a ete prise. C'est le
            # meme defaut que « absent » pour « illisible », applique aux entrees.
            print("[census] --echantillon ignore (valeur absente ou non entiere)"
                  " ; defaut %d conserve" % ech, file=sys.stderr)

    liste = bases()
    rapport = {"genere": time.strftime("%Y-%m-%d %H:%M:%S"), "bases": [],
               "fichiers": supports_fichiers()}
    print("=== CENSUS DU SAVOIR (lecture seule) ===")
    print("bases .db retenues : %d (exclus : %s)" % (len(liste), ", ".join(EXCLUS)))

    for i, p in enumerate(liste, 1):
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        _emit("base %s" % rel, i, len(liste))
        conn = _ouvrir(p)
        if conn is None:
            rapport["bases"].append({"base": rel, "etat": "ILLISIBLE"})
            print("  ILLISIBLE  %s" % rel)
            continue
        t = tables(conn)
        fiche = {"base": rel, "octets": p.stat().st_size, "etat": "lu",
                 "tables": [{"nom": n, "lignes_max": v} for n, v in t]}
        if any(n == "rag_fts" for n, _ in t):
            # Les DEUX : la jointure fait foi, la sonde par recherche montre ce
            # qu'un client vivrait reellement (elle a ses biais, ils sont dits).
            fiche["couverture_jointure"] = couverture_par_jointure(conn)
            fiche["couverture_fts"] = couverture_fts(conn, ech)
        conn.close()
        rapport["bases"].append(fiche)
        gros = sorted([x for x in t if x[1]], key=lambda x: -(x[1] or 0))[:3]
        # « vide » ne se DECLARE que si des tables ont ete lues ET qu'elles sont a
        # zero. Sans table comptable, ou sur un fichier volumineux, c'est
        # INDETERMINE : une base de 14 Mo n'est pas vide, et l'ecrire fabrique une
        # certitude fausse (mesure 2026-09-03 sur .continue/embeddings.db).
        if gros:
            resume = ", ".join("%s~%d" % (n, v) for n, v in gros)
        elif t and all(v == 0 for _n, v in t if v is not None) and p.stat().st_size < 1e6:
            resume = "(aucune ligne)"
        else:
            resume = "INDETERMINE (%d table(s), aucune comptable)" % len(t)
        fiche["resume"] = resume
        print("  %-42s %7.0f Mo  %s" % (rel[:42], p.stat().st_size / 1e6, resume))

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps(rapport, indent=1, ensure_ascii=False, default=_serialiser_mesures), encoding="utf-8")

    print("\n--- COUVERTURE PAR JOINTURE (fait foi)")
    for f in rapport["bases"]:
        j = f.get("couverture_jointure")
        if j:
            print("  %s : %s" % (f["base"], j.get("etat")))
            for ex in (j.get("exemples") or [])[:8]:
                print("      hors index : %s" % ex)

    print("\n--- SONDE PAR RECHERCHE (indicative, biais connus)")
    for f in rapport["bases"]:
        c = f.get("couverture_fts")
        if not c:
            continue
        if c.get("erreur"):
            print("  %s : INDETERMINE (%s)" % (f["base"], c["erreur"]))
            continue
        print("  %s : %d testes -> %d atteignables, %d INATTEIGNABLES, %d indetermines"
              % (f["base"], c["testes"], c["atteignables"], c["inatteignables"],
                 c["indetermines"]))
        for ex in c.get("exemples_rates", []):
            print("      rate : %-60s (temoin %s)" % (ex["source"], ex["temoin"]))
    print("\n--- SUPPORTS HORS BASE")
    for nom, v in rapport["fichiers"].items():
        print("  %-16s %-6s %s" % (nom, v["fichiers"], v["etat"]))
    print("\nrapport ecrit : %s" % SORTIE)
    print("NOTE : `lignes_max` est une BORNE SUPERIEURE (MAX(rowid)), pas un compte — "
          "les suppressions ne rendent pas leur rowid. Aucun COUNT n'a ete lance : "
          "un balayage a deja fait tomber le hub deux fois.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

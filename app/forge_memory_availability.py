"""Disponibilite de la connaissance PAR CANAL — ce que Nokido sait, et par quelle voie.

__FORGE_COLOR__ = "memoire/disponibilite-par-canal"

POURQUOI (demande owner 2026-09-01). Un chunk n'est jamais simplement `available:
true/false`. Il l'est PAR CANAL, et surtout : l'absence d'un signal a plusieurs causes
qu'un booleen confond. Le routeur de recuperation doit pouvoir distinguer

    « ce chunk n'est pas pertinent vectoriellement »
    de
    « ce chunk n'a pas encore d'embedding »
    de
    « ce chunk n'en aura JAMAIS, la politique l'interdit ».

Sans cette distinction, un score vectoriel absent devient un score NUL, et le canal
conclut a la non-pertinence de ce qu'il n'a simplement pas pu voir. C'est le meme
defaut, transpose au retrieval, que celui que Nokido paie ailleurs : « je n'ai rien vu »
lu comme « il n'y a rien ».

ETATS EMIS — et seulement ceux qu'on peut MESURER :
    AVAILABLE           le signal existe et a pu servir ;
    PENDING             il manque, mais rien ne s'oppose a ce qu'il arrive ;
    REFUSED_BY_POLICY   il ne viendra jamais : `forge_tier_guard` fait RAISE(IGNORE)
                        sur ce palier. Mesure du jour : 626 646 chunks, soit 81,1 %
                        des 772 264 « sans embedding ». Les lire comme PENDING
                        surestimait la dette d'un facteur cinq ;
    UNKNOWN             on n'a pas pu regarder. JAMAIS confondu avec une absence.

`FAILED` N'EST PAS EMIS, VOLONTAIREMENT. Rien en base ne distingue aujourd'hui un
embedding jamais tente d'un embedding tente et echoue : il n'y a pas d'emetteur. Declarer
cet etat sans l'instrumenter reviendrait a inventer une mesure — et Nokido a deja paye
plusieurs fois le motif « garde branche sur un signal que personne n'emet ». Le jour ou
un emetteur existera, il s'ajoutera ici et NON par deduction depuis `embedding IS NULL`.

PAS DE SOURCE DE VERITE NOUVELLE. Tout est DERIVE :
  - le canal vectoriel se lit sur `rag_chunks.embedding`, en BASE et non dans le cache
    memoire (`_load_embeddings` omet la colonne quand le sidecar vectoriel tourne :
    lire le cache dirait « pas de vecteur » pour des chunks parfaitement vectorises) ;
  - le palier reprend le CASE du trigger `forge_tier_guard`, dont la table
    `sqlite_master` reste l'unique autorite — un test de non-regression compare les deux
    et echoue s'ils divergent.
"""

from __future__ import annotations

import logging
import sqlite3
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

# Racine du depot : `app/` -> parent. Sert uniquement a situer le snapshot ;
# la base, elle, reste resolue par `forge_db_path`.
ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)

__FORGE_COLOR__ = "memoire/disponibilite-par-canal"

AVAILABLE = "AVAILABLE"
PENDING = "PENDING"
REFUSED_BY_POLICY = "REFUSED_BY_POLICY"
UNKNOWN = "UNKNOWN"

# Paliers que `forge_tier_guard` laisse passer ; tout le reste est refuse.
VECTORISABLES = ("laforge", "laforge-code", "laforge-memory", "web-crawl")


def tier(source: str | None, domain: str | None) -> str:
    """Palier d'un chunk — COPIE FIDELE du CASE de `forge_tier_guard`.

    L'autorite reste le trigger en base ; `test_memory_availability_nr` compare cette
    fonction au DDL lu dans `sqlite_master` et echoue si l'un des deux bouge sans
    l'autre. Recopier sans garde ferait une seconde verite ; recopier AVEC la garde
    fait un miroir verifie.
    """
    s = source or ""
    d = domain or ""
    if s.startswith("gitingest"):
        return "external-lib"
    if s.endswith(".pdf") or d in ("nagios_core", "vitis_ai"):
        return "external-doc"
    if d in ("gitingest", "gitingest_litellm", "sdk_gitingest", "laforge_digest"):
        return "cold-legacy"
    if d == "code":
        return "external-pr"
    if d == "mcp_result":
        return "tool-output"
    if d == "longmemeval":
        return "eval-data"
    if d == "conv" or s.startswith("conv"):
        return "conversation"
    if (s.startswith("session:") or s.startswith("anchor")
            or d in ("autonomous", "episodic_memory", "longterm_memory", "rag")):
        return "laforge-memory"
    if s.startswith("http"):
        return "web-crawl"
    if (s.startswith("app/") or s.startswith("tools/") or s.startswith("ctf/")
            or s.startswith("proxy_deno/")):
        return "laforge-code"
    return "laforge"


def statut_vectoriel(a_un_vecteur: bool | None, source: str | None,
                     domain: str | None) -> str:
    """AVAILABLE / PENDING / REFUSED_BY_POLICY / UNKNOWN.

    `a_un_vecteur=None` veut dire « pas regarde » et rend UNKNOWN : c'est le cas quand
    la base n'a pas pu etre interrogee. Une absence de mesure n'est pas une absence.
    """
    if a_un_vecteur is None:
        return UNKNOWN
    if a_un_vecteur:
        return AVAILABLE
    return PENDING if tier(source, domain) in VECTORISABLES else REFUSED_BY_POLICY


def statuts_pour(ids, conn=None) -> dict:
    """Statut vectoriel des chunks nommes, LU EN BASE (une seule requete bornee).

    On interroge la base plutot que le cache memoire du moteur : `_load_embeddings`
    n'emporte PAS la colonne `embedding` quand le sidecar vectoriel tourne, et un cache
    sans la colonne rendrait « aucun vecteur » sur un corpus vectorise.

    Rend {} si la base est injoignable — l'appelant verra UNKNOWN, jamais une absence
    fabriquee.
    """
    ids = [i for i in (ids or []) if i]
    if not ids:
        return {}
    propre = conn is None
    try:
        if propre:
            from nokido_agent.app.forge_db_path import db_path

            conn = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True, timeout=5)
        marques = ",".join("?" * len(ids))
        lignes = conn.execute(
            "SELECT id, embedding IS NOT NULL, source, domain FROM rag_chunks "
            f"WHERE id IN ({marques})", ids).fetchall()
    except Exception as exc:  # noqa: BLE001 - base injoignable : UNKNOWN, pas une absence
        logger.debug("[availability] lecture impossible (%r) -- statuts UNKNOWN", exc)
        return {}
    finally:
        if propre and conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - muet-ok: fermeture best-effort
                pass
    return {r[0]: {"vector": statut_vectoriel(bool(r[1]), r[2], r[3]),
                   "tier": tier(r[2], r[3])} for r in lignes}


def annoter(docs, lexical_contrib=None, conn=None):
    """Ajoute `availability` a chaque document RENDU par une recherche.

    N'ECRIT AUCUN SCORE et ne reordonne rien : cette etape rend le retrieval
    OBSERVABLE, elle ne le modifie pas.

    `lexical_contrib` = ensemble des ids ayant reellement pese dans le score lexical de
    CETTE requete. D'ou la nuance du canal lexical :
        AVAILABLE  ce chunk a contribue au score lexical ;
        UNKNOWN    il n'a pas contribue — ce qui ne dit PAS qu'il est absent de l'index,
                   seulement qu'il n'a pas matche cette requete-ci. Repondre MISSING
                   ici serait conclure d'une observation partielle, et c'est exactement
                   l'erreur que cette couche existe pour empecher.
    """
    docs = list(docs or [])
    if not docs:
        return docs
    par_id = statuts_pour([d.get("id") for d in docs], conn=conn)
    contrib = set(lexical_contrib or ())
    for d in docs:
        fiche = par_id.get(d.get("id"), {})
        d["availability"] = {
            "lexical": AVAILABLE if d.get("id") in contrib else UNKNOWN,
            "vector": fiche.get("vector", UNKNOWN),
            "tier": fiche.get("tier"),
        }
    return docs


# --------------------------------------------------------------- snapshot
# POURQUOI UN CACHE, et pourquoi il ne calcule JAMAIS lui-meme.
#
# `compteurs()` balaye la table : mesure du 2026-09-02, 10,8 s au total, dont
# 8,27 s pour le seul GROUP BY (source, domain) qui separe PENDING de
# REFUSED_BY_POLICY -- 139 342 groupes distincts. Le regulateur de ressources
# decide, lui, plusieurs fois par minute. Appeler cette fonction sur son chemin
# chaud reviendrait a remplacer un capteur FAUX par un capteur JUSTE mais qui
# etouffe l'organe qu'il informe.
#
# Le snapshot est donc PASSIF : il LIT un fichier ecrit ailleurs, et ne calcule
# rien. S'il ne trouve rien, ou trop vieux, il le DIT -- il ne se rabat pas sur
# `embedding IS NULL`. Ce chiffre brut (751 305) melange 626 646 chunks que la
# politique refuse pour toujours et 124 659 reellement en attente : y revenir en
# repli recreerait exactement la confusion que ce module existe pour lever.
#
# L'AGE FAIT PARTIE DU SIGNAL. Un consommateur qui recoit une valeur sans savoir
# de quand elle date ne peut pas juger s'il a le droit de s'en servir.

_SNAPSHOT = ROOT / "sandbox" / "memory_availability_snapshot.json"
# 26 h, et le chiffre est ALIGNE SUR SON EMETTEUR, pas choisi pour faire joli :
# le rafraichissement est lance par le circadien en NREM1, phase QUOTIDIENNE
# (fenetre 22h-02h). Une peremption a 6 h aurait laisse l'arbitre en INCONNU
# 18 h sur 24 -- un garde muet les trois quarts du temps, ce qui est pire qu'un
# garde absent puisqu'on croirait l'avoir. 26 h couvre un cycle plus deux heures
# de marge : un seul rafraichissement rate se voit, il ne casse rien.
#
# Cette latence est acceptable ICI et le resterait mal ailleurs : le backlog
# PENDING se resorbe en jours (124 659 chunks), et le seuil qui declenche
# l'arbitrage est a 5 000 -- il faudrait en assimiler 119 000 en une journee
# pour que la valeur d'hier induise une decision differente. Un signal qui
# bougerait vite exigerait un autre emetteur, pas une autre constante.
_AGE_MAX_DEFAUT_S = 93600.0


def rafraichir(conn=None, chemin=None) -> dict:
    """Calcule les compteurs et les ECRIT. A lancer HORS chemin chaud.

    Rend le snapshot ecrit. L'ecriture est atomique : un lecteur ne doit jamais
    tomber sur un fichier a moitie ecrit et le lire comme un compte a zero.
    """
    import json
    import os
    import tempfile

    c = compteurs(conn)
    snap = {
        "measured_at": time.time(),
        "total": c["total"],
        "vector_pending": c["vector"][PENDING],
        "vector_available": c["vector"][AVAILABLE],
        "vector_refused": c["vector"][REFUSED_BY_POLICY],
        "lexical_available": c["lexical"][AVAILABLE],
        "lexical_ecart_source": c["lexical"]["ecart_source"],
        "by_domain": c.get("by_domain", []),
        "avg_quality": c.get("avg_quality"),
    }
    cible = Path(chemin) if chemin else _SNAPSHOT
    cible.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(cible.parent), suffix=".snap.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(snap, fh)
        os.replace(tmp, cible)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    # SERIE TEMPORELLE -- 2026-09-20. Le snapshot ci-dessus ECRASE son
    # predecesseur : chaque rafraichissement effacait l'histoire du backlog, si
    # bien que personne ne pouvait repondre a « le drain draine-t-il ? ». Trois
    # lectures a 33 min d'ecart ce jour-la (64, 66, 81) n'ont existe que parce
    # qu'un agent les a relevees a la main pendant une session -- c'est la
    # transition EFFECT -> VERIFIED qui manquait.
    #
    # CONSOMMATEUR : `forge_resource_manager` arbitre deja sur `vector_pending`,
    # mais sur sa valeur INSTANTANEE. La serie lui permet de distinguer un seuil
    # franchi d'une DERIVE, deux situations qui appellent des reponses
    # differentes et qu'une lecture unique confond.
    #
    # Le patron existe deja deux fois ici (`forge_generation._append_oplog`,
    # `sandbox/introspect_serie.jsonl`) : on AJOUTE une ligne la ou la mesure
    # vient d'etre calculee, plutot que de la recalculer ailleurs sur un etat
    # qui aura change.
    #
    # PAS DE BORNE, et c'est un choix : une ligne par rafraichissement, quelques
    # rafraichissements par jour, ~100 octets -- de l'ordre du kilo-octet par
    # jour. Borner couterait l'histoire qu'on cherche a constituer.
    try:
        _serie = cible.parent / "memory_availability_serie.jsonl"
        with open(_serie, "a", encoding="utf-8") as _fh:
            _fh.write(json.dumps({
                "ts": snap["measured_at"],
                "vector_pending": snap["vector_pending"],
                "vector_available": snap["vector_available"],
                "total": snap["total"],
            }, ensure_ascii=False) + "\n")
    except Exception as _exc:  # noqa: BLE001
        # Le snapshot est l'acte PRINCIPAL ; la serie l'accompagne. Un journal
        # qui echoue ne doit pas emporter la mesure -- mais il le DIT, sinon on
        # croirait l'histoire tenue alors qu'elle est muette.
        logger.warning("[memoire] serie NON ecrite (%s: %s) -- le snapshot, lui, "
                       "est ecrit", type(_exc).__name__, _exc)
    return snap


def snapshot(age_max_s: float = _AGE_MAX_DEFAUT_S, chemin=None) -> dict:
    """Derniers compteurs connus, avec leur AGE. Ne calcule JAMAIS.

    Rend toujours un dict portant `frais` (bool) et `raison`. Quand `frais` est
    faux, `vector_pending` vaut None -- surtout pas une valeur de repli : une
    absence de mesure n'est pas une mesure a zero, et ce n'est pas non plus le
    chiffre brut.
    """
    import json

    cible = Path(chemin) if chemin else _SNAPSHOT
    if not cible.exists():
        return {"frais": False, "vector_pending": None, "age_s": None,
                "raison": "aucun snapshot : lancer forge_memory_availability.rafraichir "
                          "(hors chemin chaud)"}
    try:
        snap = json.loads(cible.read_text(encoding="utf-8"))
        mesure_a = float(snap["measured_at"])
    except Exception as exc:  # noqa: BLE001
        return {"frais": False, "vector_pending": None, "age_s": None,
                "raison": "snapshot illisible (%s)" % type(exc).__name__}
    age = time.time() - mesure_a
    if age > age_max_s:
        return {"frais": False, "vector_pending": None, "age_s": age,
                "raison": "snapshot perime (%.0f s > %.0f s)" % (age, age_max_s),
                **{k: v for k, v in snap.items() if k != "vector_pending"}}
    snap.update({"frais": True, "age_s": age, "raison": ""})
    return snap


def compteurs(conn=None) -> dict:
    """Audit global par canal et par etat. Balaye la table : a lancer DEPORTE."""
    propre = conn is None
    if propre:
        from nokido_agent.app.forge_db_path import db_path

        conn = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True, timeout=120)
    try:
        total = conn.execute("SELECT count(*) FROM rag_chunks").fetchone()[0]
        avec = conn.execute(
            "SELECT count(*) FROM rag_chunks WHERE embedding IS NOT NULL").fetchone()[0]
        par_etat = {AVAILABLE: avec, PENDING: 0, REFUSED_BY_POLICY: 0}
        for src, dom, n in conn.execute(
                "SELECT source, domain, count(*) FROM rag_chunks "
                "WHERE embedding IS NULL GROUP BY source, domain"):
            etat = PENDING if tier(src, dom) in VECTORISABLES else REFUSED_BY_POLICY
            par_etat[etat] += n
        # Pour la PROPRIOCEPTION (mesure 2026-09-06) : elle recomptait ces deux
        # agregats a CHAQUE cycle sur la base de 24,9 Go (GROUP BY domain + AVG),
        # 4e incarnation du balayage complet. Calcules ICI, une fois, hors chemin
        # chaud, et servis par le snapshot.
        par_domaine = conn.execute(
            "SELECT COALESCE(domain, 'unknown'), count(*) FROM rag_chunks "
            "GROUP BY domain ORDER BY 2 DESC LIMIT 15").fetchall()
        _q = conn.execute(
            "SELECT AVG(quality_score) FROM rag_chunks WHERE quality_score IS NOT NULL"
        ).fetchone()[0]
        indexes = conn.execute("SELECT count(*) FROM rag_chunks_fts_docsize").fetchone()[0]
    finally:
        if propre:
            conn.close()
    return {
        "total": total,
        "vector": par_etat,
        "by_domain": [[d, int(n)] for d, n in par_domaine],
        "avg_quality": round(float(_q), 4) if _q is not None else None,
        "lexical": {AVAILABLE: indexes, "ecart_source": total - indexes},
        "note": ("FAILED absent volontairement : aucun emetteur ne distingue "
                 "'jamais tente' de 'tente et echoue'."),
    }


# ── MATRICE DES REPRESENTATIONS (chantier 3bis, 2026-09-05) ───────────────────
# Ce module savait dire, PAR CHUNK, si le canal VECTORIEL etait disponible. Une
# connaissance existe dans plusieurs representations, et « indexee » sans dire PAR
# LAQUELLE est un booleen qui masque une couverture partielle. On elargit donc
# l'etage, on n'en cree pas un second.
#
# CINQ ETATS, jamais d'absence : OUI · NON · INCONNU · N_A · BLOQUE(raison).
# Une case ABSENTE du resultat serait la zone d'ombre exacte qu'on combat : le test
# NR verifie que les cinq representations sont TOUJOURS presentes.
#
# CE QUE LA MESURE A ETABLI, ET QUI DICTE LA FORME :
#   - le lexical a DEUX porteurs aux contrats OPPOSES. `rag_chunks_fts` est un index
#     a contenu EXTERNE tenu par QUATRE triggers SQL : sa couverture est garantie par
#     la base elle-meme, et ses trois colonnes sont interrogeables. `rag_fts` est
#     AUTONOME, sans aucun trigger, et declare `chunk_id` / `source` / `domain` en
#     UNINDEXED : l'appartenance d'une source n'y est PAS interrogeable sans balayer
#     22,8 Go. C'est la cause racine du fameux `MATCH 'source:rfc'` a zero. Le second
#     porteur sort donc INCONNU avec sa raison, jamais NON ;
#   - le structurel existe (`rag_graph_nodes` / `rag_graph_edges`), mais il n'est
#     indexe QUE par chunk_id : on interroge par identifiant, jamais par source ;
#   - l'hybride n'est PAS un index. C'est une capacite COMPOSEE, donc derivee.
REPRESENTATIONS = ("relationnel", "lexical", "structurel", "vectoriel", "hybride")
OUI, NON, N_A, BLOQUE = "OUI", "NON", "N_A", "BLOQUE"


def _cellule(valeur, producteur=None, vivant=None, raison=None, population=None):
    """Une case n'est jamais une valeur nue : elle porte QUI la produit et POURQUOI."""
    return {"valeur": valeur, "producteur": producteur, "producteur_vivant": vivant,
            "raison": raison, "population": population}


def _etat_producteur(organe):
    """(bat, eteint_par_decision) emprunte a la topologie. `(None, None)` = non mesure.

    LA DISTINCTION QUI CHANGE QUI DOIT AGIR. Un producteur `disabled = true` dans
    `services.toml` n'est pas « mort » : il est ETEINT PAR DECISION — pour les
    embedders, la directive owner du 2026-09-01 qui route l'embedding vers Modal.
    Rapporter cela en `RESOURCE_UNAVAILABLE` enverrait quelqu'un reparer un choix.
    """
    try:
        from nokido_agent.app import forge_nervous_map as nm

        for f in nm.autorites()["organes"]:
            if f["organe"] == organe:
                # INFERENCE et non fraicheur brute : `bat` seul promouvait le pouls
                # d'un orphelin en preuve de vie. `INCERTAIN` rend None — « on ne
                # sait pas » n'est pas « mort », et cette matrice refuse depuis sa
                # premiere ligne de transformer une ignorance en panne.
                _v = f.get("producteur_vivant")
                return ({"OUI": True, "NON": False}.get(_v),
                        f.get("eteint_par_decision"))
    except Exception:  # noqa: BLE001 - muet-ok : sans topologie, l'etat reste INCONNU
        return None, None
    return None, None


def representations(source: str, conn=None) -> dict:
    """Matrice des representations d'UNE source. Aucune case absente.

    Les populations restent SEPAREES : on ne produit aucun pourcentage global, qui
    melangerait des denominateurs differents et masquerait la cause.
    """
    from nokido_agent.app.forge_db_path import db_path

    ferme = False
    if conn is None:
        cx = sqlite3.connect("file:%s?mode=ro" % str(db_path()).replace("\\", "/"),
                             uri=True, timeout=15)
        conn, ferme = cx, True
    cells = {}
    try:
        lignes = conn.execute(
            "SELECT id, domain, embedding IS NULL, rowid FROM rag_chunks "
            "WHERE source = ?", (source,)).fetchall()
        ids = [r[0] for r in lignes]
        n = len(ids)

        # 1. RELATIONNEL — la presence en base, mesure directe (index sur `source`).
        cells["relationnel"] = _cellule(OUI if n else NON, producteur="ingestion",
                                        population=n)

        # 2. LEXICAL — deux porteurs, deux contrats. On rapporte les deux.
        # APPARTENANCE PAR ROWID, et surtout PAS par `MATCH 'source:"..."'`. Mesure du
        # 2026-09-05 : la phrase rendait 144 entrees pour 16 chunks, parce que le
        # tokenizer coupe `memory:MEMORY_ARCHIVE` en jetons dont `memory` et `MEMORY`
        # — la source VOISINE etait comptee dans la notre. Un index a contenu externe
        # partage le `rowid` de sa table source : c'est la seule jointure exacte.
        try:
            presents = 0
            for _l in lignes:
                presents += conn.execute(
                    "SELECT count(*) FROM rag_chunks_fts WHERE rowid = ?",
                    (_l[3],)).fetchone()[0]
            if not n:
                cells["lexical"] = _cellule(N_A, raison="aucun chunk relationnel")
            else:
                cells["lexical"] = _cellule(
                    OUI if presents == n else ("PARTIEL" if presents else NON),
                    producteur="triggers SQL rag_chunks_fts_{bi,ai,ad,au}",
                    vivant=True, population={"indexes": presents, "attendus": n},
                    raison=None if presents == n
                    else "%d chunk(s) absent(s) de l'index a contenu externe" % (n - presents))
        except Exception as exc:  # noqa: BLE001
            cells["lexical"] = _cellule(UNKNOWN, producteur="rag_chunks_fts",
                                        raison="interrogation impossible: %s" % exc)
        # SECOND PORTEUR, nomme meme s'il est inutilisable : `rag_fts` est autonome,
        # sans trigger, et declare ses colonnes UNINDEXED. Son appartenance n'est pas
        # interrogeable sans balayer la base — on le DIT au lieu de l'omettre.
        cells["lexical"]["second_porteur"] = _cellule(
            UNKNOWN, producteur="rag_fts (autonome, alimente par le code d'ingestion)",
            raison="colonnes chunk_id/source/domain UNINDEXED : appartenance non "
                   "interrogeable sans balayage — c'est la cause racine du "
                   "MATCH 'source:...' a zero")

        # 3. STRUCTUREL — graphe de relations, interrogeable par chunk_id SEULEMENT.
        try:
            noeuds = aretes = 0
            for cid in ids:
                noeuds += conn.execute(
                    "SELECT count(*) FROM rag_graph_nodes WHERE chunk_id = ?",
                    (cid,)).fetchone()[0]
                aretes += conn.execute(
                    "SELECT count(*) FROM rag_graph_edges WHERE src = ?",
                    (cid,)).fetchone()[0]
            if not n:
                cells["structurel"] = _cellule(N_A, raison="aucun chunk relationnel")
            else:
                cells["structurel"] = _cellule(
                    OUI if noeuds else NON, producteur="forge_graph_linker",
                    population={"noeuds": noeuds, "aretes": aretes},
                    raison=None if noeuds else "aucun noeud de graphe pour ces chunks")
        except Exception as exc:  # noqa: BLE001
            cells["structurel"] = _cellule(UNKNOWN, raison="graphe illisible: %s" % exc)

        # 4. VECTORIEL — statut par chunk via le patron de ce module, PAS un booleen.
        etats = {}
        for cid, domaine, sans_vecteur, _rid in lignes:
            etats.setdefault(
                statut_vectoriel(not sans_vecteur, source, domaine), []).append(cid)
        producteur_vivant, eteint_decision = _etat_producteur("embed_auto_trigger")
        if not n:
            cells["vectoriel"] = _cellule(N_A, raison="aucun chunk relationnel")
        elif etats.get(AVAILABLE):
            cells["vectoriel"] = _cellule(
                OUI if len(etats[AVAILABLE]) == n else "PARTIEL",
                producteur="embed_auto_trigger", vivant=producteur_vivant,
                population={k: len(v) for k, v in etats.items()})
        elif etats.get(REFUSED_BY_POLICY):
            cells["vectoriel"] = _cellule(
                BLOQUE, producteur="forge_tier_guard", vivant=True,
                raison="REFUSED_BY_POLICY : le palier de cette source est refuse par "
                       "le trigger, ce n'est PAS une dette",
                population={k: len(v) for k, v in etats.items()})
        else:
            # PENDING. Un producteur MORT n'est pas une file qui avance : la nuance
            # decide si quelqu'un doit agir ou seulement attendre.
            # DEUX FAITS DISTINCTS, et les confondre refait le faux diagnostic que
            # cette campagne a elimine plusieurs fois (correction owner 2026-09-05) :
            #   (a) l'embedder LOCAL est eteint PAR DECISION (`disabled = true`,
            #       directive du 2026-09-01 qui route l'embedding vers Modal) ;
            #   (b) le backend DESIGNE, lui, a son propre etat — et il n'est pas
            #       mesurable ici : `forge_pool_registry` porte 48 membres et AUCUN
            #       d'embedding (mesure 2026-09-05). Sans emetteur, cet etat reste
            #       UNKNOWN ; l'inventer serait exactement ce que ce module refuse
            #       depuis sa premiere ligne.
            blocage = {
                "policy": "DISABLED_LOCAL_EMBEDDER" if eteint_decision else None,
                "backend_designe": UNKNOWN,
                "backend_raison": "aucun membre d'embedding declare dans "
                                  "forge_pool_registry : disponibilite non mesuree",
            }
            if eteint_decision:
                raison = ("PENDING — embedder LOCAL desactive par decision ; l'etat du "
                          "backend designe est INCONNU, non defaillant")
            elif producteur_vivant is False:
                blocage["policy"] = None
                raison = "PENDING et producteur MORT sans decision d'extinction"
            else:
                raison = "PENDING, liveness du producteur non mesuree"
            cellule = _cellule(
                BLOQUE if (producteur_vivant is False or eteint_decision) else UNKNOWN,
                producteur="embed_auto_trigger", vivant=producteur_vivant,
                raison=raison,
                population={k: len(v) for k, v in etats.items()})
            cellule["blocage"] = blocage
            cells["vectoriel"] = cellule

        # 5. HYBRIDE — DERIVE, jamais un index. Une capacite composee ne peut pas
        # depasser le plus faible de ses composants.
        lex, vec = cells["lexical"]["valeur"], cells["vectoriel"]["valeur"]
        if lex == OUI and vec == OUI:
            h, r = OUI, None
        elif lex == OUI and vec in (BLOQUE, "PARTIEL", UNKNOWN):
            h, r = "DEGRADE", "lexical seul : la voie vectorielle est %s" % vec
        elif lex in (NON, UNKNOWN):
            h, r = UNKNOWN, "disponibilite lexicale %s : la fusion n'est pas evaluable" % lex
        else:
            h, r = NON, "aucune voie disponible"
        cells["hybride"] = _cellule(h, producteur="derive (fusion + rerank)", raison=r)
    finally:
        if ferme:
            conn.close()

    manquantes = [r for r in REPRESENTATIONS if r not in cells]
    for r in manquantes:  # ceinture : une case absente serait la zone d'ombre meme
        cells[r] = _cellule(UNKNOWN, raison="non calculee — defaut de l'instrument")
    return {"source": source, "representations": cells,
            "cases_rattrapees": manquantes}


def main() -> int:
    import json

    print(json.dumps(compteurs(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""forge_tier_policy.py — Provenance (origin) + politique de tiering RAG.

SOURCE UNIQUE DE VERITE du tiering RAG.

Probleme resolu : le `domain` etait pose non-fiablement a l'ingestion (du
gitingest de libs externes etiquete nokido_code/ami/general) et servait
pourtant de cle de tiering -> ~278k chunks externes vectorises a tort.

Fix structurel : `origin` = champ de PROVENANCE explicite, derive
deterministiquement de source+domain par une regle unique (ORIGIN_EXPR).
- ORIGIN_EXPR  : expression SQL CASE  -> etiquette d'origine.
- colonne `origin` : ORIGIN_EXPR materialisee (generee virtuelle, ajoutee par
  forge_migrate_origin.py) -> queryable, indexee, visible.
- HOT_TIER_SQL : clause WHERE (= origin hot) ; le tiering est une POLITIQUE
  fonction de l'origin, plus une devinette sur le domaine.
- derive_origin() : miroir Python de ORIGIN_EXPR (pour les ingesteurs).

Taxonomie : seul le contenu genuinement Nokido est vectorise ; l'externe
(libs tierces, docs vendor, PRs, sorties d'outils, datasets) reste FTS-only.
"""

def base_rag() -> str:
    """Chemin de la base qui PORTE `rag_chunks` (forme utilisable en URI sqlite).

    ⚠️ C'est la TABLE qui decide, PAS l'existence du fichier : `data/rag.db`
    EXISTE mais fait 0 octet et ne porte aucune table `rag%` (mesure 2026-08-19).
    Un candidat retenu sur `os.path.exists` rendait donc une base vide, et tout
    compteur bati dessus lisait 0 — une absence de mesure prise pour une mesure
    d'absence.

    Vit ICI, avec la politique de tiering, parce que trois scripts d'embedding en
    portaient une copie a l'identique : le cliquet anti-clones les a rejetes, a
    juste titre — trois copies d'une regle de resolution divergent des qu'on en
    corrige une seule.

    Leve SystemExit si aucune base ne porte la table : sans base il n'y a pas de
    repli raisonnable, et poursuivre ne produirait que des comptes vides.
    """
    import os as _os
    import sqlite3 as _sq

    _racine = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    for _cand in ("%NOKIDO_DATA%\embeddings.db",
                  _os.path.join(_racine, "RAG", "embeddings.db").replace("\\", "/"),
                  _os.path.join(_racine, "data", "rag.db").replace("\\", "/")):
        try:
            _c = _sq.connect("file:%s?mode=ro" % _cand, uri=True, timeout=5.0)
            try:
                _c.execute("SELECT 1 FROM rag_chunks LIMIT 1").fetchone()
            finally:
                _c.close()
            return _cand
        except Exception:  # noqa: BLE001 - base absente, vide ou sans la table
            continue
    raise SystemExit("aucune base ne porte rag_chunks")


# Origines vectorisables (tier chaud) = savoir dense et divers.
HOT_ORIGINS = ("laforge", "laforge-code", "laforge-memory", "web-crawl")
# Origines NON vectorisees (tier froid, FTS-only). `conversation` = logs bruts
# homogenes qui encombrent l'espace vectoriel ; leur savoir est deja distille
# dans `laforge-memory` (anchors/lessons) -> froid, reste cherchable via FTS.
COLD_ORIGINS = (
    "conversation",
    "external-lib",
    "external-doc",
    "external-pr",
    "tool-output",
    "eval-data",
    "cold-legacy",
)

# Regle unique source+domain -> origin. Premier match gagne (ordre important).
ORIGIN_EXPR = """CASE
  WHEN source LIKE 'gitingest%' THEN 'external-lib'
  WHEN source LIKE '%.pdf' OR domain IN ('nagios_core','vitis_ai') THEN 'external-doc'
  WHEN domain IN ('gitingest','gitingest_litellm','sdk_gitingest','nokido_digest') THEN 'cold-legacy'
  WHEN domain = 'code' THEN 'external-pr'
  WHEN domain = 'mcp_result' THEN 'tool-output'
  WHEN domain = 'longmemeval' THEN 'eval-data'
  WHEN domain = 'conv' OR source LIKE 'conv%' THEN 'conversation'
  WHEN source LIKE 'session:%' OR source LIKE 'anchor%'
       OR domain IN ('autonomous','episodic_memory','longterm_memory','rag') THEN 'laforge-memory'
  WHEN source LIKE 'http%' THEN 'web-crawl'
  WHEN source LIKE 'app/%' OR source LIKE 'tools/%' OR source LIKE 'ctf/%'
       OR source LIKE 'proxy_deno/%' THEN 'laforge-code'
  ELSE 'laforge'
END"""

# Clause WHERE : vrai = chunk eligible au tier vectoriel. Forme inline (CASE)
# -> robuste, ne depend pas de l'existence de la colonne `origin`.
HOT_TIER_SQL = (
    "(" + " ".join(ORIGIN_EXPR.split()) + ") IN (" + ", ".join(f"'{o}'" for o in HOT_ORIGINS) + ")"
)

# Meme predicat, mais lu dans la COLONNE au lieu d'etre recalcule par ligne.
# `origin` est declaree `GENERATED ALWAYS AS (CASE ...)` avec EXACTEMENT ORIGIN_EXPR :
# la valeur est donc toujours coherente, et surtout INDEXABLE -- ce que le CASE inline
# ne sera jamais. Mesure 2026-07-25 : la selection des chunks a vectoriser passe de
# 1,07 s a 0,00 s (plan `SEARCH ... USING INDEX idx_emb_null_origin`), sur une table de
# 707 940 lignes dont 138 000 sans vecteur mais FROIDES que le CASE rejetait une par
# une, a chaque passe. C'est ce cout, et non l'embedding (0,16 s/chunk), qui dominait.
HOT_TIER_SQL_ORIGIN = (
    "origin IN (" + ", ".join(f"'{o}'" for o in HOT_ORIGINS) + ")"
)


def hot_tier_clause(conn) -> str:
    """Clause WHERE « tier chaud » la plus rapide DISPONIBLE sur cette base.

    Le choix du CASE inline pour `HOT_TIER_SQL` etait deliberement defensif (il ne
    depend pas de l'existence de la colonne `origin`). On ne casse pas ce filet : on
    DEMANDE a la base si la colonne existe, et on ne prend la forme indexable que dans
    ce cas. Une base ancienne ou reduite continue de fonctionner avec le CASE.
    """
    try:
        # `table_xinfo` et NON `table_info` : ce dernier n'expose PAS les colonnes
        # GENERATED (mesure 2026-07-25 -- `origin`, `ext`, `folder`, `lang` etaient
        # invisibles a l'inventaire, ce qui faisait retomber cette fonction sur le CASE
        # alors que la colonne existait). Piege a retenir pour toute detection de schema.
        cols = {r[1] for r in conn.execute("PRAGMA table_xinfo(rag_chunks)")}
    except Exception:  # noqa: BLE001
        return HOT_TIER_SQL
    return HOT_TIER_SQL_ORIGIN if "origin" in cols else HOT_TIER_SQL


def derive_origin(source: str, domain: str) -> str:
    """Miroir Python de ORIGIN_EXPR — classe un chunk par provenance.

    A appeler par les ingesteurs pour poser `origin` explicitement.
    """
    s = source or ""
    sl = s.lower()
    d = domain or ""
    if sl.startswith("gitingest"):
        return "external-lib"
    if sl.endswith(".pdf") or d in ("nagios_core", "vitis_ai"):
        return "external-doc"
    if d in ("gitingest", "gitingest_litellm", "sdk_gitingest", "nokido_digest"):
        return "cold-legacy"
    if d == "code":
        return "external-pr"
    if d == "mcp_result":
        return "tool-output"
    if d == "longmemeval":
        return "eval-data"
    if d == "conv" or sl.startswith("conv"):
        return "conversation"
    if (
        sl.startswith("session:")
        or sl.startswith("anchor")
        or d in ("autonomous", "episodic_memory", "longterm_memory", "rag")
    ):
        return "laforge-memory"
    if sl.startswith("http"):
        return "web-crawl"
    if s.startswith(("app/", "tools/", "ctf/", "proxy_deno/")):
        return "laforge-code"
    return "laforge"


def is_hot_tier(source: str, domain: str) -> bool:
    """True si le chunk doit etre vectorise (origin du tier chaud)."""
    return derive_origin(source, domain) in HOT_ORIGINS

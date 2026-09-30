"""NR -- aucun chemin FREQUENT ne balaie rag_chunks / rag_fts (veille lot_B_34, P1 ; 2026-09-24).

Politique zio-blocks transposee a la cause MESUREE du P0 WAL (23/09) : « une passe de correction
(humaine ou agentique) n'a pas le droit d'ajouter du travail par element sur une boucle
optimisee ». Quatre NR ponctuels existaient, chacun pose APRES son incident (post-commit,
audit RAG, drain Qdrant, balayeurs) ; celui-ci GENERALISE leur methode sans nouveau mecanisme :
  - la requete est LUE DANS LA SOURCE (AST), jamais recopiee -- un test qui recopie protege une copie ;
  - EXPLAIN QUERY PLAN est joue sur le SCHEMA REEL (index compris, releve en lecture seule le
    24/09) : le plan depend du schema et de la forme de la requete, pas du volume ;
  - un balayage VOULU et BORNE est une EXCEPTION NOMMEE avec sa preuve, jamais un silence ;
    une exception qui ne sert plus fait rougir (elle cacherait le prochain retour) ;
  - ce qui n'est pas rejouable (fragments assembles a l'execution, f-strings) est COMPTE sous un
    plafond : ILLISIBLE n'est pas SAIN.
Mesure a la creation (base reelle, lecture seule) : 22 requetes sans balayage, 4 SCAN (3 voulus et
nommes ci-dessous + 1 echantillon borne mesure a 3 ms), 5 illisibles.
Un balayage d'INDEX (`USING [COVERING] INDEX`) est admis : il ne lit pas les BLOB de la table.
"""
from __future__ import annotations

import ast
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TABLES = ("rag_chunks", "rag_fts", "rag_chunks_fts")

# Chemins FREQUENTS declares, avec leur cadence. Ajouter un module frequent = le declarer ICI.
CHEMINS_CHAUDS = {
    "tools/forge_post_commit.py": "hook a chaque commit",
    "app/forge_health_diagnostic.py": "phase health du tick (~7 min)",
    "tools/forge_qdrant_sync_daemon.py": "drain toutes les 30 s (gele le 24/09, garde maintenue)",
    "app/forge_memory_availability.py": "lu par le regulateur plusieurs fois par minute",
    "app/forge_proprioception.py": "cycle de proprioception",
    "tools/hook_capability_gate.py": "hook PreToolUse, chaque appel d'outil",
    "tools/hook_recon_first.py": "hook PreToolUse, chaque edition",
    # Ajoute le 2026-09-24 (chantier UI) : la page /epistemic du portail joue ses 3 requetes a
    # CHAQUE chargement, dans un handler synchrone (un thread du portail immobilise). Mesure :
    # `test_ui_pages_rendent_nr` y restait bloque jusqu'au delai de pytest.
    "app/web_hub/epistemic.py": "page /epistemic du portail, a chaque chargement",
}

# Balayages VOULUS, prouves hors chemin chaud ou bornes : (module, fonction, marqueur) -> preuve.
EXCEPTIONS = {
    ("tools/forge_post_commit.py", "update_readme_stats", "COUNT(*)"):
        "appele seulement sur --readme-stats explicite depuis le P0 WAL (23/09)",
    ("app/forge_memory_availability.py", "compteurs", ""):
        "audit global DEPORTE : seul rafraichir() l'appelle, en NREM1 quotidien (snapshot passif)",
    ("app/forge_health_diagnostic.py", "_audit_rag_chunks_mesure", "LIMIT 50"):
        "echantillon borne : 3 ms mesurees le 24/09 (premieres lignes vectorisees) ; cout DEPENDANT des donnees",
}
PLAFOND_ILLISIBLES = 5  # releve 24/09 : 4 fragments `... IN (` assembles a l'execution + 1 prose

# Schema REEL de %NOKIDO_DATA%\embeddings.db (sqlite_master, lecture seule, 2026-09-24) pour les tables que
# ces chemins touchent. Un index ajoute ou retire en production change les plans : regenerer ici.
SCHEMA = r"""
CREATE TABLE qdrant_sync_pending ( chunk_id TEXT PRIMARY KEY, queued_at REAL );
CREATE TABLE rag_chunks ( id TEXT PRIMARY KEY, text TEXT NOT NULL, source TEXT NOT NULL, domain TEXT DEFAULT 'general', role_hint TEXT DEFAULT 'chat', embedding BLOB, meta TEXT DEFAULT '{}', ingested_at TEXT DEFAULT (datetime('now')) , author TEXT DEFAULT '', sequence_id INTEGER, session_id TEXT DEFAULT '', version_id TEXT DEFAULT '', updated_at TEXT DEFAULT '', hash TEXT, indexed_at TEXT, quality_score REAL DEFAULT NULL, created_at INTEGER, origin TEXT GENERATED ALWAYS AS (CASE WHEN source LIKE 'gitingest%' THEN 'external-lib' WHEN source LIKE '%.pdf' OR domain IN ('nagios_core','vitis_ai') THEN 'external-doc' WHEN domain IN ('gitingest','gitingest_litellm','sdk_gitingest','laforge_digest') THEN 'cold-legacy' WHEN domain = 'code' THEN 'external-pr' WHEN domain = 'mcp_result' THEN 'tool-output' WHEN domain = 'longmemeval' THEN 'eval-data' WHEN domain = 'conv' OR source LIKE 'conv%' THEN 'conversation' WHEN source LIKE 'session:%' OR source LIKE 'anchor%' OR domain IN ('autonomous','episodic_memory','longterm_memory','rag') THEN 'laforge-memory' WHEN source LIKE 'http%' THEN 'web-crawl' WHEN source LIKE 'app/%' OR source LIKE 'tools/%' OR source LIKE 'ctf/%' OR source LIKE 'proxy_deno/%' THEN 'laforge-code' ELSE 'laforge' END) VIRTUAL, ext TEXT GENERATED ALWAYS AS (CASE WHEN source LIKE '%.py' OR source LIKE '%.py#%' THEN 'py' WHEN source LIKE '%.ts' OR source LIKE '%.ts#%' THEN 'ts' WHEN source LIKE '%.js' OR source LIKE '%.js#%' THEN 'js' WHEN source LIKE '%.md' OR source LIKE '%.md#%' THEN 'md' WHEN source LIKE '%.rs' OR source LIKE '%.rs#%' THEN 'rs' WHEN source LIKE '%.toml' OR source LIKE '%.toml#%' THEN 'toml' WHEN source LIKE '%.json' OR source LIKE '%.json#%' THEN 'json' WHEN source LIKE '%.yaml' OR source LIKE '%.yaml#%' THEN 'yaml' WHEN source LIKE '%.yml' OR source LIKE '%.yml#%' THEN 'yaml' WHEN source LIKE '%.sh' OR source LIKE '%.sh#%' THEN 'sh' WHEN source LIKE '%.bat' OR source LIKE '%.bat#%' THEN 'bat' WHEN source LIKE '%.ps1' OR source LIKE '%.ps1#%' THEN 'ps1' WHEN source LIKE '%.sql' OR source LIKE '%.sql#%' THEN 'sql' WHEN source LIKE '%.html' OR source LIKE '%.html#%' THEN 'html' WHEN source LIKE '%.css' OR source LIKE '%.css#%' THEN 'css' WHEN source LIKE '%.pdf' OR source LIKE '%.pdf#%' THEN 'pdf' WHEN source LIKE '%.txt' OR source LIKE '%.txt#%' THEN 'txt' ELSE '' END) VIRTUAL, folder TEXT GENERATED ALWAYS AS (CASE WHEN instr(source, '/') > 0 THEN substr(source, 1, instr(source, '/') - 1) ELSE '' END) VIRTUAL, lang TEXT GENERATED ALWAYS AS (CASE ext WHEN 'py' THEN 'python' WHEN 'ts' THEN 'typescript' WHEN 'js' THEN 'javascript' WHEN 'rs' THEN 'rust' WHEN 'sh' THEN 'shell' WHEN 'ps1' THEN 'powershell' WHEN 'md' THEN 'markdown' WHEN 'sql' THEN 'sql' ELSE '' END) VIRTUAL, canonical_id TEXT, version TEXT DEFAULT 'v1', superseded_by TEXT, active INTEGER DEFAULT 1, epistemic_weight REAL DEFAULT 0.5, last_validated_at TEXT, retraction_status TEXT, embedding_model TEXT DEFAULT NULL, access_count INTEGER DEFAULT 0);
CREATE INDEX idx_chunks_canonical_active ON rag_chunks(canonical_id, active);
CREATE INDEX idx_chunks_epistemic ON rag_chunks(epistemic_weight DESC) WHERE active=1;
CREATE INDEX idx_domain ON rag_chunks(domain);
CREATE INDEX idx_domain_ext ON rag_chunks(domain, ext);
CREATE INDEX idx_emb_null_origin ON rag_chunks(origin) WHERE embedding IS NULL;
CREATE INDEX idx_embedding_null ON rag_chunks(id) WHERE embedding IS NULL;
CREATE INDEX idx_ext ON rag_chunks(ext);
CREATE INDEX idx_folder ON rag_chunks(folder);
CREATE INDEX idx_lang ON rag_chunks(lang);
CREATE INDEX idx_rag_chunks_active ON rag_chunks(active);
CREATE INDEX idx_rag_chunks_ingested_at ON rag_chunks(ingested_at);
CREATE INDEX idx_rag_chunks_json_extract_meta_consensus ON rag_chunks(json_extract(meta,'$.consensus_level'));
CREATE INDEX idx_rag_chunks_json_extract_meta_ingested_a ON rag_chunks(json_extract(meta,'$.ingested_at'));
CREATE INDEX idx_rag_chunks_role_hint ON rag_chunks(role_hint);
CREATE INDEX idx_rag_disco ON rag_chunks(role_hint) WHERE role_hint='disco';
CREATE INDEX idx_rag_domain ON rag_chunks(domain);
CREATE INDEX idx_rag_fingerprint ON rag_chunks(json_extract(meta,'$.fingerprint'));
CREATE INDEX idx_rag_origin ON rag_chunks(origin);
CREATE INDEX idx_rag_ring_expr ON rag_chunks(json_extract(meta,'$.ring'));
CREATE INDEX idx_rag_seq ON rag_chunks(sequence_id);
CREATE INDEX idx_rag_session ON rag_chunks(session_id);
CREATE INDEX idx_rag_source ON rag_chunks(source);
CREATE INDEX idx_rag_updated ON rag_chunks(updated_at);
CREATE VIRTUAL TABLE rag_chunks_fts USING fts5( text, source, domain, content='rag_chunks', content_rowid='rowid' );
CREATE VIRTUAL TABLE "rag_fts" USING fts5(chunk_id UNINDEXED, text, source UNINDEXED, domain UNINDEXED);
CREATE TABLE chunk_claims ( id TEXT PRIMARY KEY, chunk_id TEXT NOT NULL, text TEXT NOT NULL, predicates TEXT, confidence_authored REAL DEFAULT 0.5, is_technical INTEGER DEFAULT 1, abstract_embedding BLOB, extracted_by TEXT, extracted_at TEXT, FOREIGN KEY (chunk_id) REFERENCES rag_chunks(id) ON DELETE CASCADE );
CREATE TABLE claim_reevaluations ( older_claim_id TEXT NOT NULL, newer_claim_id TEXT NOT NULL, reevaluation_type TEXT NOT NULL, confidence REAL DEFAULT 0.5, rationale TEXT, detected_by TEXT, detected_at TEXT, PRIMARY KEY (older_claim_id, newer_claim_id) );
CREATE INDEX idx_chunk_claims_chunk ON chunk_claims(chunk_id);
CREATE INDEX idx_claims_chunk ON chunk_claims(chunk_id);
CREATE INDEX idx_claims_extracted ON chunk_claims(extracted_at);
CREATE INDEX idx_reeval_newer ON claim_reevaluations(newer_claim_id);
CREATE INDEX idx_reeval_older ON claim_reevaluations(older_claim_id, reevaluation_type);
"""
# Index qu'un SEARCH ne rend pas selectif : `active` ne prend que NULL / 0 / 1. Mesure 2026-09-24 sur
# la base reelle (page /epistemic) : `WHERE c.active IS NULL OR c.active = 1` donnait
# `MULTI-INDEX OR` + `SEARCH c USING INDEX idx_rag_chunks_active (active=?)` en boucle EXTERNE -- un
# SEARCH en apparence, un parcours de toutes les lignes actives en realite (169 revendications a joindre).
_INDEX_NON_SELECTIFS = ("idx_rag_chunks_active",)

_T = re.compile(r"\b(rag_chunks|rag_fts|rag_chunks_fts)\b")
_SQL = re.compile(r"(?is)(select|delete|update|with)\b")
_PAS_ALIAS = {"WHERE", "ON", "JOIN", "LIMIT", "ORDER", "GROUP", "SET", "USING", "CROSS", "INNER", "LEFT", "MATCH"}


def _base() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    return con


def _fonction(arbre: ast.AST, ligne: int) -> str:
    best, span = "<module>", 10**9
    for n in ast.walk(arbre):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.lineno <= ligne <= (n.end_lineno or n.lineno):
            if (n.end_lineno or n.lineno) - n.lineno < span:
                best, span = n.name, (n.end_lineno or n.lineno) - n.lineno
    return best


def _requetes():
    """(module, fonction, ligne, sql) lus dans la source ; + liste des illisibles."""
    vues, illisibles = [], []
    for rel in CHEMINS_CHAUDS:
        arbre = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        # les morceaux constants d'une f-string ne sont pas des requetes a part (double compte mesure)
        dans_fstring = {id(v) for f in ast.walk(arbre) if isinstance(f, ast.JoinedStr) for v in f.values}
        for n in ast.walk(arbre):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in dans_fstring:
                q = n.value.strip()
                if _T.search(q) and _SQL.match(q):
                    vues.append((rel, _fonction(arbre, n.lineno), n.lineno, q))
            elif isinstance(n, ast.JoinedStr):
                s = "".join(v.value for v in n.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
                if _T.search(s) and _SQL.match(s.strip()):
                    illisibles.append("%s:%d f-string" % (rel, n.lineno))
    return vues, illisibles


def _balayages(con: sqlite3.Connection, q: str) -> list[str]:
    """Lignes de plan qui balaient une table RAG. Leve si la requete n'est pas rejouable."""
    nb = q.count("?")
    noms = re.findall(r"[:@$](\w+)", q)
    params = (None,) * nb if nb else {k: None for k in noms}
    plan = [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + q, params)]
    alias = {m.group(1) for m in re.finditer(r"(?i)\b(?:rag_chunks|rag_fts|rag_chunks_fts)\s+(?:AS\s+)?(\w+)", q)
             if m.group(1).upper() not in _PAS_ALIAS}
    mauvais = []
    for p in plan:
        m = re.match(r"(SCAN|SEARCH) (\w+)", p)
        if not m or (m.group(2) not in TABLES and m.group(2) not in alias):
            continue
        if m.group(1) == "SEARCH":
            if any("USING INDEX %s " % i in p + " " for i in _INDEX_NON_SELECTIFS):
                mauvais.append(p)
            continue
        if "USING INDEX" in p or "USING COVERING INDEX" in p or re.search(r"VIRTUAL TABLE INDEX \d+:\S", p):
            continue
        mauvais.append(p)
    return mauvais


def test_aucun_chemin_chaud_ne_balaie_la_base():
    con = _base()
    vues, illisibles = _requetes()
    assert len(vues) >= 20, "moins de requetes lues que mesure (~31) : le lecteur ne voit plus les chemins chauds"
    fautes, servies = [], set()
    for rel, fn, ligne, q in vues:
        try:
            mauvais = _balayages(con, q)
        except sqlite3.Error as e:
            illisibles.append("%s:%d %s" % (rel, ligne, str(e)[:40]))
            continue
        if not mauvais:
            continue
        cle = next((k for k in EXCEPTIONS if k[0] == rel and k[1] == fn and k[2] in q), None)
        if cle:
            servies.add(cle)
        else:
            fautes.append("%s:%d (%s) %s -> %s" % (rel, ligne, fn, " ".join(q.split())[:90], mauvais))
    assert not fautes, "BALAYAGE sur un chemin chaud (cause du P0 WAL) :\n  " + "\n  ".join(fautes)
    perimees = sorted(set(EXCEPTIONS) - servies)
    assert not perimees, "exception(s) qui ne servent plus -- les retirer, sinon elles couvriront le prochain retour : %s" % perimees
    assert len(illisibles) <= PLAFOND_ILLISIBLES, (
        "requetes NON rejouables en hausse (%d > %d) -- ILLISIBLE n'est pas SAIN :\n  %s"
        % (len(illisibles), PLAFOND_ILLISIBLES, "\n  ".join(illisibles)))


def test_le_schema_de_reference_porte_les_index_reels():
    con = _base()
    idx = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_rag_source", "idx_embedding_null", "idx_domain"} <= idx, "schema de reference ampute : plans sans valeur"


def test_garde_du_garde():
    con = _base()
    assert _balayages(con, "SELECT id FROM rag_chunks WHERE text LIKE ?")
    assert not _balayages(con, "SELECT id FROM rag_chunks WHERE source = ?")
    assert _balayages(con, "SELECT c.id FROM rag_chunks c WHERE c.quality_score IS NOT NULL")
    assert _balayages(con, "SELECT chunk_id FROM rag_fts WHERE source = ?"), "FTS sans MATCH = balayage"
    assert not _balayages(con, "SELECT chunk_id FROM rag_fts WHERE rag_fts MATCH ?")
    assert not _balayages(con, "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL")
    # l'index non selectif `active` : un SEARCH qui parcourt tout, et sa forme saine
    assert _balayages(con, "SELECT c.text FROM chunk_claims cc JOIN rag_chunks c ON c.id = cc.chunk_id "
                           "WHERE c.active IS NULL OR c.active = 1"), "SEARCH par idx_rag_chunks_active non vu"
    assert not _balayages(con, "SELECT c.text FROM chunk_claims cc CROSS JOIN rag_chunks c ON c.id = cc.chunk_id "
                               "WHERE COALESCE(c.active, 1) = 1")

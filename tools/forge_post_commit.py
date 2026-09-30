#!/usr/bin/env python3
"""
tools/forge_post_commit.py — Automatisation post-git-commit Nokido
====================================================================
Déclenché par .git/hooks/post-commit après chaque commit.
Trois actions en séquence :

1. SYNC .md / SKILL.md — met à jour les fichiers consultables par les IAs
   (CLAUDE, GEMINI, CLINE, ROO) avec les dernières modifications du commit.

2. VECTORISATION — indexe dans embeddings.db les fichiers Python et .md
   modifiés par le commit. Mise à jour du RAG immédiatement après commit.

3. KNOWLEDGE UPDATE — met à jour les SKILL.md des IAs avec un résumé
   des nouveaux modules et patterns introduits dans ce commit.

Usage :
    Automatique : déclenché par git hook
    Manuel      : python tools/forge_post_commit.py [--dry-run] [--commit SHA]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
PYTHON = Path(__import__("os").path.expanduser(r"~\miniforge3\python.exe"))
DB = ROOT / "RAG" / "embeddings.db"
LOG = ROOT / "logs" / "post_commit.log"

# Le fichier de log s'ouvre A L'IMPORT : sous un compte sans droit d'ecriture sur
# logs/, le module devenait INIMPORTABLE (PermissionError) — donc intestable, et
# inutilisable par tout appelant qui n'est pas l'owner. Un journal indisponible
# degrade la trace, il ne doit pas empecher le module d'exister.
_handlers = [logging.StreamHandler(sys.stderr)]
try:
    _handlers.insert(0, RotatingFileHandler(str(LOG), encoding="utf-8",
                                            maxBytes=10485760, backupCount=5))
except Exception:  # noqa: BLE001 - droits, disque plein, chemin absent
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [post-commit] %(message)s",
    handlers=_handlers,
)
log = logging.getLogger("post_commit")

# ── Circuit breaker (incident 2026-08-16) ────────────────────────────────────
# Un commit de 451 fichiers a fait POSTer ~2255 fois vers le hub, chaque appel
# refuse (GATE DENY) mais NON detecte (le corps n'etait pas lu) : le hub a
# sature et est mort. Deux garde-fous purs :
MAX_FILES_HUB = 80    # au-dela : ecriture directe, le hub n'est pas sollicite
MAX_CONSEC_DENY = 3   # K refus consecutifs -> hub coupe pour le reste du run


def modules_a_instrumenter(changed, perimetre=None) -> list[str]:
    """Modules NEUFS de ce commit qui n'ont AUCUN perimetre de mesure.

    ORGANE REACTIF (2026-09-08). Instrumenter un module neuf n'est pas une
    consolidation de sommeil, c'est une reponse a un EVENEMENT : le module vient
    d'apparaitre. Le mettre en NREM1 le faisait attendre ~41 h ; ici il est vu tout
    de suite.

    L'EMBOLIE est impossible par construction, et le garde n'est pas neuf : le volume
    est borne par le commit lui-meme, et au-dela de `MAX_FILES_HUB` on s'abstient —
    ce plafond a ete pose apres un commit de 451 fichiers qui avait declenche ~2255
    POST vers le hub. On reutilise un garde PAYE plutot que d'en inventer un.
    """
    chemins = [str(f).replace("\\", "/") for f in changed]
    if len(chemins) > MAX_FILES_HUB:
        return []  # commit volumineux : on ne pompe pas, cf. garde ci-dessus
    if perimetre is None:
        import sys as _s

        _s.path.insert(0, str(ROOT / "app"))
        from nokido_agent.app.forge_mutation_judge import perimetre_mesure as perimetre
    from nokido_agent.tools.forge_couverture_perimetre import est_ecarte

    out = []
    for rel in chemins:
        if not rel.endswith(".py"):
            continue
        if not (rel.startswith("app/") or rel.startswith("tools/")):
            continue
        if est_ecarte(rel):
            continue
        if perimetre(rel):
            continue
        out.append(rel)
    return out


def should_use_hub(n_changed: int) -> bool:
    """Faux pour un commit volumineux : l'indexation passe alors en ecriture
    directe (qui ne touche pas l'event loop du hub) au lieu de le marteler."""
    return n_changed <= MAX_FILES_HUB


def reponse_refusee(raw: bytes) -> bool:
    """Vrai si la reponse du hub est un refus, MEME en HTTP 200.

    Le hub renvoie souvent 200 avec un corps d'erreur : ne pas lire le corps,
    c'est prendre un DENY pour un succes et marteler. Un corps vide ou non
    decodable n'est pas un refus (on ne coupe pas a tort)."""
    if not raw:
        return False
    try:
        bas = raw.decode("utf-8", errors="strict").lower()
    except (UnicodeDecodeError, AttributeError):
        return False
    return '"error"' in bas or "gate deny" in bas or "insufficient ring" in bas

# ── Domaines par type de fichier ──────────────────────────────────────────────
_DOMAIN_MAP = {
    ".py": "nokido_code",
    ".md": "nokido_doc",
    ".yaml": "nokido_config",
    ".yml": "nokido_config",
    ".json": "nokido_config",
}

# Fichiers à exclure de la vectorisation
_EXCLUDE = {
    "__pycache__",
    ".git",
    "node_modules",
    ".run_tmp",
    ".bridge_tmp",
    "embeddings.db",
    "*.pyc",
    "*.lock",
}


# ── 1. Récupérer les fichiers modifiés dans le dernier commit ─────────────────
def get_changed_files(commit: str = "HEAD") -> list[Path]:
    """Retourne les fichiers modifiés/ajoutés dans le commit."""
    r = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "-r", "--name-only", commit],
        capture_output=True,
        text=True, errors="replace", encoding="utf-8",
        cwd=str(ROOT),
    )
    files = []
    for line in r.stdout.splitlines():
        p = ROOT / line.strip()
        if not p.exists():
            continue
        # Filtrer les exclusions
        if any(exc in str(p) for exc in _EXCLUDE):
            continue
        if p.suffix in _DOMAIN_MAP:
            files.append(p)
    return files


# ── 2. Vectoriser un fichier dans embeddings.db ───────────────────────────────
# Documents de DOCTRINE : indexes a part, entiers, sous un source LISIBLE.
# Mesure 2026-07-24 : RULES_SHARED.md etait bien dans le RAG depuis le 21 mai, mais
#   (a) sous `mcp_result:POST_COMMIT:git_RULES_SHARED_md_p0:<ts>` — introuvable par
#       une recherche sur le nom du fichier, donc invisible en pratique ;
#   (b) TRONQUE par `chunks[:5]` (~10k chars) alors qu'il en fait 17,8k : le tableau
#       des capacites d'execution, en fin de fichier, n'a JAMAIS ete indexe ;
#   (c) jamais re-vectorise depuis, malgre les commits.
# Resultat : un agent demandant a Nokido « comment j'execute X » n'avait aucune
# reponse, et la doctrine se re-expliquait a la main a chaque session.
# DOCTRINE.md (2026-07-25) : les regles d'INGESTION, ajoutees apres trois violations
# du « lexical d'abord » le meme jour. Une regle qu'on repete est une regle qui n'est
# pas outillee — celle-ci est indexee, donc opposable et verifiable par requete.
_DOCTRINE = {"RULES_SHARED.md", "CLAUDE.md", "COGNITION.md", "DOCTRINE.md"}


def _hub_token() -> str:
    """Jeton du hub : environnement d'abord, COFFRE ensuite.

    Le hook tourne cote POSTE, ou la variable n'est pas posee : le POST repartait
    en 401 et l'indexation tombait en silence (mesure 24-07 : « RAG: 0/2 fichiers
    indexes » a chaque commit). Le jeton EST au coffre — on le DEMANDE au lieu de
    supposer l'environnement, comme le veut la regle sur les secrets de service.
    Il ne transite jamais par une ligne de commande.
    """
    # LE COFFRE D'ABORD, l'environnement en repli — et pas l'inverse.
    # Mesure 24-07 : la variable d'environnement portait un jeton de 64 caracteres
    # que le hub REFUSE (401), alors que le coffre en contient un de 412 qui est le
    # bon. Faire confiance a l'environnement, c'est prendre un jeton perime sans
    # jamais le savoir : l'echec est un 401 muet, pas une erreur de configuration.
    try:
        import sys as _sys

        _app = str(ROOT / "app")
        if _app not in _sys.path:
            _sys.path.insert(0, _app)
        from nokido_agent.app.forge_secrets import get_secret

        # SON jeton d'abord (chantier d'authentification, P0, 2026-09-24). MESURE du
        # 21/09 : 14 382 appels du hook partaient avec le MAITRE sous le nom POST_COMMIT
        # -- le maitre conserve l'agent de l'en-tete et son ring, c'est une USURPATION
        # (contrat AUTH-2 : le maitre ne devient jamais une identite d'organe). Le repli
        # sur le maitre reste pour ne pas couper l'indexation d'une machine sans ce
        # jeton, mais il se DIT a chaque fois, et il n'est jamais fige (piege du webhub
        # du 22/09 : un repli mis en cache devient definitif).
        tok = get_secret("FORGE_TOKEN_POST_COMMIT") or ""
        if tok:
            return tok
        tok = get_secret("FORGE_MCP_TOKEN") or ""
        if tok:
            print("[post_commit] FORGE_TOKEN_POST_COMMIT absent du coffre : repli sur le "
                  "jeton MAITRE (usurpation d'identite). Geste : forge_vault_seed_agent_tokens "
                  "--generate-missing --from-registre --ring-max 4 --agents POST_COMMIT",
                  file=_sys.stderr)
            return tok
    except Exception:  # noqa: BLE001
        pass
    return get_secret("FORGE_MCP_TOKEN") or ""


# P0 WAL (2026-09-23) — CE HOOK ETAIT LE LECTEUR LONG. `source = ? OR source LIKE ?`
# rendait `SCAN rag_chunks` (33 Go) PAR FICHIER commite : LIKE est insensible a la
# casse, donc `idx_rag_source` n'etait pas utilisable. Piege SYSTEM : WAL de 2,27 Go
# a 2,5 Mo dans la minute ou les deux post_commit de 17:55 sont sortis. La plage
# `[prefixe, prefixe borne)` passe par l'index — et elle est EXACTE, la ou le `_`
# d'un nom de fichier etait un joker LIKE. NR : tests/nr/test_post_commit_sans_scan_nr.py
_WHERE_SOURCE = "(source = ? OR (source >= ? AND source < ?))"


def _params_source(rel: str) -> tuple:
    """`rel` exact, ou `rel#chunk<N>` : borne haute = dernier caractere + 1."""
    bas = f"{rel}#chunk"
    return (rel, bas, bas[:-1] + chr(ord(bas[-1]) + 1))


def _purger_fts(con, anciens) -> int:
    """Purge `rag_fts` SANS le balayer. `chunk_id` et `source` y sont UNINDEXED : la
    seule voie indexee est MATCH sur `text`. On restreint par une phrase du texte,
    l'id sert de filtre EXACT. Sans mot exploitable, la ligne reste orpheline — et on
    le DIT : `purge_rag_fts_fantomes()` (sommeil NREM3) la reprend, et la recherche
    lexicale ne la sert pas d'ici la (elle joint `rag_chunks`).
    Source unique : `forge_db_path.purger_fts` (l'audit du corps en avait besoin aussi,
    2026-09-27) ; ici on ne garde que la voix du journal."""
    from nokido_agent.app.forge_db_path import purger_fts

    n, laissees = purger_fts(con, anciens)
    for cid in laissees:
        log.warning(f"FTS: {cid} sans mot exploitable -> ligne laissee a purge_rag_fts_fantomes")
    return n


# LIVENESS DU HOOK (option 1, validee par l'owner le 2026-09-23). Le rejeu de 24f6b1c5e
# a montre le hook encore lecteur long (4,9 Go en 90 s) : `guarded_change` appelait par
# defaut `_light_health` -> `forge_health_diagnostic.audit_rag_chunks`, dit « leger »
# mais qui balaie la base (deja accuse par l'observatoire le 2026-09-04). L'interface
# PREVOIT un `post_check` dedie : on lui passe la MEME propriete critique — tables
# critiques non videes — par `SELECT 1 ... LIMIT 1` (arret a la premiere ligne).
# `forge_guarded_change` et `forge_health_diagnostic` ne sont PAS modifies (hors
# perimetre) ; leur allegement reste une dette distincte (option 2).
_TABLES_CRITIQUES = ("rag_chunks", "biblio_raw", "forge_entities")


def _vie_legere() -> dict:
    """post_check du hook : ok=False si une table critique est VIDE. Table absente ou
    illisible = DITE, sans echec (le controle d'origine est fail-open sur ses erreurs)."""
    from nokido_agent.app.forge_guarded_change import _DB

    out = {"ok": True, "reason": ""}
    vides, illisibles = [], []
    con = sqlite3.connect(str(_DB), timeout=10)
    try:
        for t in _TABLES_CRITIQUES:
            try:
                if con.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone() is None:
                    vides.append(t)
            except sqlite3.OperationalError as e:
                illisibles.append(f"{t} ({e})")
    finally:
        con.close()
    if vides:
        out.update(ok=False, reason=f"tables critiques videes: {vides}")
    if illisibles:
        out["check_error"] = "tables critiques illisibles: %s" % illisibles
    return out


def _index_doctrine(path: Path, rel: str, text: str, dry_run: bool) -> bool:
    """Indexe un fichier ENTIER en direct, source lisible `<fichier>#chunkN`.

    Sert aux documents de doctrine, et de REPLI quand le POST vers le hub echoue
    (401 sans jeton cote poste) — sinon l'indexation tombe en silence.
    """
    if dry_run:
        log.info(f"[DRY] doctrine {rel} ({len(text)} chars, entier)")
        return True
    try:
        import hashlib
        import sys as _sys

        _app = str(ROOT / "app")
        if _app not in _sys.path:
            _sys.path.insert(0, _app)
        from nokido_agent.app.forge_db_path import db_path
        from nokido_agent.app.forge_rag_store import MarkdownChunker

        ch = MarkdownChunker()
        chunks = ch.chunk(text) if hasattr(ch, "chunk") else ch.split(text)
        con = sqlite3.connect(db_path(), timeout=20)
        n = 0
        try:
            # PURGER avant de reinserer. `cid` derive du TEXTE : au moindre mot change
            # l'id change, donc INSERT OR REPLACE n'a rien a remplacer et EMPILE une
            # version de plus sous le meme `source`. Mesure 24-07 : COGNITION.md#chunk4
            # present en deux exemplaires (703 et 1381 chars) — le RAG servait une
            # doctrine PERIMEE a cote de la courante, les deux en concurrence au
            # classement. Reindexer un fichier REMPLACE sa representation.
            # DELETE et INSERT partagent la meme transaction (commit unique en sortie) :
            # un echec en cours de route ne laisse pas la doctrine amputee.
            anciens = con.execute(
                "SELECT id, text FROM rag_chunks WHERE " + _WHERE_SOURCE,
                _params_source(rel)).fetchall()
            purged = con.execute(
                "DELETE FROM rag_chunks WHERE " + _WHERE_SOURCE, _params_source(rel)
            ).rowcount
            # La table FTS ne suit AUCUN trigger : sans cette purge, le lexical
            # continuerait de servir l'ancienne doctrine apres reindexation.
            try:
                _purger_fts(con, anciens)
            except sqlite3.OperationalError as _e:
                log.warning(f"DOCTRINE purge FTS {rel}: {_e}")
            for i, c in enumerate(chunks):
                body = c if isinstance(c, str) else (c.get("text") or str(c))
                if not body.strip():
                    continue
                src = f"{rel}#chunk{i}"
                cid = hashlib.sha256((src + body).encode("utf-8")).hexdigest()[:16]
                con.execute(
                    "INSERT OR REPLACE INTO rag_chunks (id, source, text, domain) VALUES (?,?,?,?)",
                    (cid, src, body, "doctrine"),
                )
                # INDEXATION LEXICALE — elle manquait purement et simplement.
                # Mesure 2026-07-25 : 121 chunks de doctrine en base, **0 dans
                # rag_fts**. La doctrine n'etait donc servie QUE par le canal dense ;
                # une recherche par mot exact (« __FORGE_COLOR__ », « ZONE_MORTE »)
                # ne la trouvait jamais. Or c'est le lexical qui doit primer : il est
                # exact, il ne depend d'aucun embedder, et il repond meme quand la
                # vectorisation est en retard.
                try:
                    con.execute(
                        "INSERT INTO rag_fts (chunk_id, text, source, domain)"
                        " VALUES (?,?,?,?)", (cid, body, src, "doctrine"))
                except sqlite3.OperationalError as _e:
                    log.warning(f"DOCTRINE FTS {src}: {_e}")
                n += 1
            con.commit()
            # VECTORISER dans la foulee. La purge ci-dessus repart d'ids neufs, donc
            # sans embedding : la doctrine sortirait du canal dense jusqu'au prochain
            # passage de l'auto-embed — invisible la ou elle doit primer (mesure 24-07 :
            # 83/83 chunks a NULL juste apres reindexation). Fail-soft : embedder muet
            # -> on LOG et on laisse NULL, l'auto-trigger rattrapera ; jamais d'echec
            # du hook pour ca.
            try:
                import struct as _st

                from nokido_agent.app.forge_embed_router import embed_batch_fast as _emb

                todo = con.execute(
                    "SELECT id, text FROM rag_chunks WHERE embedding IS NULL "
                    "AND " + _WHERE_SOURCE, _params_source(rel)
                ).fetchall()
                if todo:
                    vecs = _emb([t for _, t in todo])
                    k = 0
                    for (cid, _), v in zip(todo, vecs or []):
                        if not v:
                            continue
                        con.execute("UPDATE rag_chunks SET embedding = ? WHERE id = ?",
                                    (_st.pack(f"{len(v)}f", *v), cid))
                        k += 1
                    con.commit()
                    log.info(f"DOCTRINE vectorisee: {rel} ({k}/{len(todo)})")
            except Exception as _e:  # noqa: BLE001
                log.warning(f"DOCTRINE embed differe {rel}: {_e}")
        finally:
            con.close()
        log.info(f"DOCTRINE OK: {rel} ({n} chunks, entier, source lisible ; "
                 f"{purged} obsoletes purges)")
        return n > 0
    except Exception as e:  # noqa: BLE001
        log.warning(f"DOCTRINE FAIL {rel}: {e}")
        return False


def vectorise_file(path: Path, dry_run: bool = False, use_hub: bool = True) -> str:
    """Indexe un fichier dans le RAG. Rend un statut : 'ok' | 'direct' | 'deny'
    | 'fail' | 'skip'. use_hub=False force l'ecriture directe (le hub n'est pas
    sollicite : commit volumineux ou breaker declenche)."""
    domain = _DOMAIN_MAP.get(path.suffix, "general")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
    except Exception as e:
        log.warning(f"Lecture {path.name}: {e}")
        return False

    if len(text.strip()) < 50:
        return "skip"  # fichier vide ou trop court

    if path.name in _DOCTRINE:
        return "direct" if _index_doctrine(path, rel, text, dry_run) else "fail"

    if dry_run:
        log.info(f"[DRY] vectorise {rel} ({len(text)} chars) domain={domain}")
        return "ok"

    if not use_hub:
        # Breaker actif ou commit volumineux : ecriture directe, le hub reste a
        # l'abri de l'avalanche de POST (incident 2026-08-16).
        return "direct" if _index_doctrine(path, rel, text, dry_run=False) else "fail"

    # Envoyer au hub MCP via HTTP
    task_id = rel.replace("/", "_").replace(".", "_")
    sha = _get_commit_sha()
    token = _hub_token()
    # Chunking : tranches de 2000 chars avec recouvrement 200
    chunks = []
    for i in range(0, len(text), 1800):
        chunks.append(text[i : i + 2000])
    ok_count = 0
    for ci, chunk in enumerate(chunks[:5]):  # max 5 chunks par fichier
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "rag",
                    "arguments": {
                        "action": "index",
                        "task_id": f"git_{task_id}_p{ci}",
                        "result": (
                            "FILE: " + rel + " (part " + str(ci) + ")\n"
                            "COMMIT: " + sha + "\n"
                            "DOMAIN: " + domain + "\n\n" + chunk
                        ),
                    },
                },
            }
        ).encode()
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8766/mcp",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                    "X-Agent-Name": "POST_COMMIT",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read()
            # 200 avec un corps d'erreur = refus : le detecter, sinon on martele.
            if reponse_refusee(raw):
                log.warning(f"RAG DENY {rel} part {ci}: hub refuse (ring)")
                return "deny"
            ok_count += 1
        except Exception as e:
            log.warning(f"RAG FAIL {rel} part {ci}: {e}")
            break

    if ok_count == 0:
        # Le hook tourne cote POSTE : il n'a pas toujours le jeton du hub, et le POST
        # repart en 401 — silencieusement, car l'echec n'est que journalise.
        # Mesure 2026-07-24 : « RAG: 0/2 fichiers indexes » a chaque commit, donc le
        # CODE SOURCE n'entrait plus dans la cognition, sans que rien ne l'annonce.
        # Repli sur l'ecriture directe, exactement le chemin qui fait deja passer la
        # doctrine. Un index qui ne recoit plus rien est pire qu'un index absent :
        # il donne l'illusion d'une memoire a jour.
        if _index_doctrine(path, rel, text, dry_run=False):
            log.info(f"RAG OK (repli direct): {rel} ({len(text)} chars)")
            return "direct"
        return "fail"

    if ok_count:
        log.info(f"RAG OK: {rel} ({len(text)} chars, {ok_count} chunks)")
    return "ok" if ok_count else "fail"


def _get_commit_sha() -> str:
    r = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, errors="replace", cwd=str(ROOT),
    )
    return r.stdout.strip()


def _get_commit_msg() -> str:
    r = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        capture_output=True,
        text=True, errors="replace", encoding="utf-8",
        cwd=str(ROOT),
    )
    return r.stdout.strip()[:200]


# ── 3. Mettre à jour les SKILL.md pour les IAs ───────────────────────────────
def update_skill_md(changed_files: list[Path], dry_run: bool = False):
    """
    Met à jour docs/skills/nokido/SKILL.md avec les nouveaux modules.
    Ce fichier est lu par GEMINI, CLINE, ROO pour connaître le code.
    """
    # Le renommage LaForge -> Nokido a laisse ce chemin en arriere : la skill
    # canonique SUIVIE est docs/skills/nokido/ (commit a0f99914, "une skill = un
    # dossier = un nom"), mais le hook ecrivait dans docs/skills/laforge/, qui
    # n'est suivi par personne. Mesure du 2026-08-15 : docs/skills/nokido/SKILL.md
    # fige au 11/08 15:54 depuis quatre jours pendant que 90 commits
    # s'empilaient dans le doublon fantome -- les IAs lisaient une carte perimee.
    skill_path = ROOT / "docs" / "skills" / "nokido" / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)

    sha = _get_commit_sha()
    msg = _get_commit_msg()
    ts = time.strftime("%Y-%m-%d %H:%M")

    # Nouveaux modules .py dans ce commit
    new_py = [f for f in changed_files if f.suffix == ".py"]
    new_md = [f for f in changed_files if f.suffix == ".md"]

    if not new_py and not new_md:
        return

    # Lire SKILL.md existant ou créer
    existing = skill_path.read_text(encoding="utf-8") if skill_path.exists() else ""

    # Bloc à ajouter en tête du changelog
    entry = f"""
## Commit {sha} — {ts}
**{msg}**

"""
    if new_py:
        entry += "### Modules Python modifiés\n"
        for f in new_py[:20]:
            rel = str(f.relative_to(ROOT)).replace("\\", "/")
            entry += f"- `{rel}`\n"
        entry += "\n"

    if new_md:
        entry += "### Documentation mise à jour\n"
        for f in new_md[:10]:
            rel = str(f.relative_to(ROOT)).replace("\\", "/")
            entry += f"- `{rel}`\n"
        entry += "\n"

    # Insérer après le header existant (première ligne ## Commit)
    if dry_run:
        log.info(f"[DRY] SKILL.md update: {len(new_py)} py + {len(new_md)} md")
        return

    # Chercher le premier bloc ## Commit pour insérer avant lui
    insert_marker = "\n## Commit "
    if insert_marker in existing:
        idx = existing.find(insert_marker)
        new_content = existing[:idx] + "\n" + entry + existing[idx:]
    else:
        # Créer le fichier depuis un template
        header = _skill_header()
        new_content = header + "\n" + entry

    skill_path.write_text(new_content[:100000], encoding="utf-8")  # cap 100KB
    log.info(f"SKILL.md mis à jour: {skill_path}")


def _skill_header() -> str:
    return """---
name: nokido
description: >
  Nokido Sovereign Hub — orchestrateur multi-agents local-first.
  Hub HTTP:8766, bridge stdio, RAG SQLite, 196+ modules forge_*.py,
  7 rôles locaux (Ollama), 8 cloud roles (groq/github/mistral),
  forge_task_queue, forge_roles, forge_trust_score, forge_mailbox.
  Mis à jour automatiquement après chaque git commit.
---

# Nokido — Knowledge Base pour IAs collaboratrices

## Architecture rapide
- Hub : `tools/nokido_hub.py` — Starlette :8766
- Bridge : `tools/mcp_stdio_bridge.py` — stdio → HTTP
- Rôles : `app/forge_roles.py` — PLANNER/EXECUTOR/REVIEWER/ROUTER/SUMMARIZER/SENTINEL/MONITOR
- Queue : `app/forge_task_queue.py` — SQLite persistant, Semaphore(2)
- RAG : `RAG/embeddings.db` — 100K+ chunks bge-m3 1024d
- Rescue : `tools/forge_rescue.py` — canal de secours admin on-demand

## Changelog automatique (post-commit)
"""


# ── 4. Mettre à jour README.md avec stats live ───────────────────────────────
def update_readme_stats(dry_run: bool = False):
    """Injecte les stats live (modules, chunks RAG) dans README.md."""
    readme = ROOT / "README.md"
    if not readme.exists():
        return

    # Stats rapides
    try:
        n_py = len(list((ROOT / "app").glob("forge_*.py")))
        with sqlite3.connect(str(DB), timeout=5) as conn:
            n_chunks = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
            n_embed = conn.execute(
                "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL AND length(embedding) > 10"
            ).fetchone()[0]
    except Exception:
        return

    sha = _get_commit_sha()
    ts = time.strftime("%Y-%m-%d")
    badge_line = (
        f"<!-- STATS:{sha}:{ts} modules={n_py} rag_chunks={n_chunks} embeddings={n_embed} -->"
    )

    content = readme.read_text(encoding="utf-8")
    # Remplacer la ligne STATS existante ou ajouter en fin
    import re

    new_content, n = re.subn(r"<!-- STATS:[^>]+ -->", badge_line, content)
    if n == 0:
        new_content = content.rstrip() + f"\n\n{badge_line}\n"

    if dry_run:
        log.info(f"[DRY] README stats: {n_py} modules, {n_chunks} chunks, {n_embed} embeddings")
        return

    readme.write_text(new_content, encoding="utf-8")
    log.info(f"README.md stats: modules={n_py} chunks={n_chunks} embeddings={n_embed}")


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Nokido post-commit automation")
    parser.add_argument("--dry-run", action="store_true", help="Simulation sans écriture")
    parser.add_argument("--commit", default="HEAD", help="SHA commit à traiter")
    parser.add_argument("--no-rag", action="store_true", help="Skip vectorisation RAG")
    parser.add_argument("--no-skill", action="store_true", help="Skip mise à jour SKILL.md")
    parser.add_argument("--readme-stats", action="store_true",
                        help="Recompter les chunks pour README (DEUX balayages de la base)")
    args = parser.parse_args()

    sha = _get_commit_sha()
    msg = _get_commit_msg()
    log.info(f"=== post-commit {sha} — {msg} ===")
    t0 = time.monotonic()

    # 1. Fichiers modifiés
    changed = get_changed_files(args.commit)
    log.info(f"Fichiers modifiés: {len(changed)}")
    for f in changed[:5]:
        log.info(f"  {f.relative_to(ROOT)}")

    if not changed:
        log.info("Aucun fichier éligible — terminé")
        return

    # 2. Vectorisation RAG — gate anti-régression
    if not args.no_rag:
        if str(ROOT / "app") not in sys.path:
            sys.path.insert(0, str(ROOT))
        from contextlib import nullcontext

        from nokido_agent.app.forge_guarded_change import guarded_change

        # db_snapshot=False : post_commit tourne à CHAQUE commit -> un snapshot
        # complet serait trop lourd ; le healthcheck léger + la détection
        # d'effondrement du RAG suffisent (la vectorisation ne fait qu'ajouter).
        _g = (
            nullcontext()
            if args.dry_run
            else guarded_change("post_commit: vectorisation RAG", db_snapshot=False,
                                post_check=_vie_legere)
        )
        with _g:
            use_hub = should_use_hub(len(changed))
            if not use_hub:
                log.warning("commit volumineux (%d fichiers > %d) -> ecriture "
                            "directe, hub non sollicite (anti-avalanche)",
                            len(changed), MAX_FILES_HUB)
            ok = 0
            deny_streak = 0
            for f in changed:
                status = vectorise_file(f, dry_run=args.dry_run, use_hub=use_hub)
                if status in ("ok", "direct"):
                    ok += 1
                if status == "deny":
                    deny_streak += 1
                    if use_hub and deny_streak >= MAX_CONSEC_DENY:
                        log.warning("circuit breaker RAG: %d DENY consecutifs -> "
                                    "hub coupe, repli direct pour le reste",
                                    deny_streak)
                        use_hub = False
                else:
                    deny_streak = 0
        log.info(f"RAG: {ok}/{len(changed)} fichiers indexés")
    else:
        log.info("RAG: skipped (--no-rag)")

    # 3. SKILL.md pour IAs
    if not args.no_skill:
        update_skill_md(changed, dry_run=args.dry_run)
    else:
        log.info("SKILL.md: skipped (--no-skill)")

    # 4. README stats — HORS du chemin de chaque commit (P0 WAL, 2026-09-23) : ses deux
    # COUNT sur rag_chunks balaient la base a CHAQUE commit. Sur demande explicite
    # seulement ; la ligne STATS du README n'est donc plus rafraichie a chaque commit.
    if args.readme_stats:
        update_readme_stats(dry_run=args.dry_run)

    # 4.5 Proprioception : régén diff-only des cartes comportementales + ingest RAG (sha gate)
    if not args.dry_run:
        try:
            py_changed = [f.name for f in changed
                          if f.suffix == ".py" and f.parent.name in ("app", "tools")]
            if py_changed:
                if str(ROOT / "tools") not in sys.path:
                    sys.path.insert(0, str(ROOT))
                from nokido_agent.tools import forge_module_cards as _fmc
                _n = _fmc.refresh_changed(py_changed)
                log.info(f"Cartes comportementales: {len(py_changed)} régénérées, {_n} ingérées RAG")
        except Exception as e:
            log.warning(f"Cartes: skip ({e})")

    # 4.55 Instrumentation des modules NEUFS (2026-09-08) — ORGANE REACTIF.
    # Un module sans perimetre de mesure est un module sur lequel le juge a gain ne
    # peut rendre que GAIN_INDECIDABLE. On le voit ICI, a l'EVENEMENT, plutot qu'au
    # prochain NREM1 (~41 h d'intervalle mesures). L'embolie est impossible : le
    # volume est borne par le commit, et au-dela de MAX_FILES_HUB on s'abstient —
    # garde deja paye apres un commit de 451 fichiers. Best-effort, JAMAIS muet.
    if not args.dry_run:
        try:
            cibles = modules_a_instrumenter(changed)
            if cibles:
                if str(ROOT / "tools") not in sys.path:
                    sys.path.insert(0, str(ROOT))
                from nokido_agent.tools.forge_generer_appui import generer as _gen
                _r = _gen(cibles, appliquer=True)
                log.info("Appui: %d module(s) neuf(s) sans perimetre -> %d test(s) "
                         "genere(s), %d non instrumentable(s)",
                         len(cibles), len(_r["ecrits"]), len(_r["non_importables"]))
                for _rel, _motif in _r["non_importables"].items():
                    log.warning("Appui: %s NON instrumentable -> %s", _rel, _motif[:160])
        except Exception as e:  # noqa: BLE001 — n'emporte jamais le post-commit
            log.warning("Appui: instrumentation impossible (%s: %s) — les modules neufs "
                        "de ce commit restent sans perimetre", type(e).__name__, str(e)[:160])

    # 4.6 Intent drift : flague les NOUVELLES intentions mortes (create-intent -> module
    # ABSENT) introduites par CE commit, sur les fichiers changés SEULEMENT (cheap). Log-only,
    # fail-safe (try/except) : ne peut JAMAIS casser un commit. Prévient la dérive à la source.
    # Directive user : ne plus nourrir stub & code mort / intention oubliée.
    if not args.dry_run:
        try:
            if str(ROOT / "tools") not in sys.path:
                sys.path.insert(0, str(ROOT))
            from nokido_agent.tools.forge_roadmap_keeper import _scan_intent_source
            _dead = []
            for f in changed:
                if f.suffix in (".py", ".md"):
                    _dead += [x for x in _scan_intent_source(f, str(f.relative_to(ROOT)))
                              if x["verdict"] == "dead"]
            if _dead:
                log.warning("Intent drift: %d intention(s) morte(s) introduite(s) "
                            "(create -> module absent) — %s", len(_dead),
                            "; ".join(f"{x['src']}:{x['line']} {x['refs']}" for x in _dead[:5]))
        except Exception as e:
            log.warning(f"Intent drift: skip ({e})")

    # 5. Bench auto-trigger — if critical modules changed, fire promptfoo in background
    bench_triggers = {"forge_llm_router.py", "forge_rag_engine.py", "forge_rag_store.py"}
    changed_names = {f.name for f in changed}
    if changed_names & bench_triggers and not args.dry_run:
        bench_bat = ROOT / "sandbox" / "promptfoo_clinical" / "run_bench.bat"
        if bench_bat.exists():
            log.info(
                f"Bench trigger: {changed_names & bench_triggers} — launching {bench_bat.name}"
            )
            subprocess.Popen(
                [str(bench_bat)],
                cwd=str(bench_bat.parent),
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=open(ROOT / "sandbox" / "bench_auto.log", "a"),
                stderr=subprocess.STDOUT,
            )
        else:
            log.info(
                f"Bench trigger: {changed_names & bench_triggers} — run_bench.bat absent, skip"
            )

    elapsed = round((time.monotonic() - t0) * 1000)
    log.info(f"=== terminé en {elapsed}ms ===")


if __name__ == "__main__":
    main()

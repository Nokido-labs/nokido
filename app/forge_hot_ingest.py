# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_hot_ingest
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_hot_ingest.py — Fast-Track Ingestion (Priorité 0, Ring 2)
===============================================================
Point d'entrée prioritaire pour l'humain dans la TUI.

Principe :
  L'humain est un validateur. Quand il dépose un fichier ou une URL
  explicitement, on lui attribue ring=2 (TRUSTED) immédiatement —
  pas ring=3 comme un agent externe.

  Ce bypass est légitime UNIQUEMENT depuis la TUI (action humaine directe).
  Le MCP server n'a pas accès à cette voie.

Deux scénarios :
  1. @rag drop <fichier|URL>   — ingestion forcée Ring 2, priorité 0 (FLASH)
  2. Hot-folder watcher        — surveille data/rag_files/ et ingère les nouveaux
                                  fichiers avec ring=2 dès qu'ils apparaissent

Flux complet :
  TUI humain → hot_ingest() → add_document() [ring=2, author=user_manual]
                             → CoVe SKIPPÉ (humain a déjà validé)
                             → qualify_chunk() → trust_score=0.8 (TRUSTED)
                             → PromotionOrchestrator.enqueue(priority=0)
                             → FAISS rebuild
                             → feedback TUI immédiat

Author signé : 'user_manual' (ring=2 TRUSTED par convention humaine)
Provenance   : 'tui_drop' ou 'hot_folder'
"""


import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_RAG_DIR = _ROOT / "data" / "rag_files"

# Ring humain — validateur direct TUI
HUMAN_RING = 2
HUMAN_AUTHOR = "user_manual"
HUMAN_CONSENSUS = "verified"  # pas draft — l'humain a déjà présélectionné
HUMAN_TRUST = 0.8
HUMAN_PRIORITY = 0  # FLASH — passe devant tout


# ─────────────────────────────────────────────────────────────────────────────
# Utilitaires
# ─────────────────────────────────────────────────────────────────────────────


# 2/11 (owner, « attention aux injections de prompt ici aussi ») : un fichier DEPOSE par l'owner est le plus souvent
# ecrit par d'AUTRES (articles, PDF) et sera relu par des modeles. TRUSTED seulement pour un document ECRIT par l'owner
# (sous-dossier owner/ ou prefixe owner_) ; sinon ring EXTERNE. Et analyse anti-injection AVANT toute ingestion.
EXTERNAL_RING = 3
EXTERNAL_TRUST = 0.5
# caracteres invisibles par POINTS DE CODE (jamais litteraux dans le source : le hub les refuse, a juste titre)
# Analyse du contenu : forge_prompt_guard.analyser_contenu_tiers, garde commun a toute ingestion de tiers.
_REFUS = Path(__file__).resolve().parents[1] / "sandbox" / "hot_ingest_refus.jsonl"


def _auteur_owner(path: Path) -> bool:
    return path.parent.name.lower() == "owner" or path.name.lower().startswith("owner_")


# Repli OCR (owner 2/11, « version auteur d'abord, OCR sinon ») : un PDF sans couche texte (scan, impression image)
# etait refuse sans recours. rapidocr_onnxruntime vit HORS des environnements de services (pip --target, incident du
# 1/11 : une montee pip a chaud a arrete 4 services) ; son dossier est ajoute EN FIN de sys.path pour que les paquets
# deja installes (numpy, onnxruntime) gardent la priorite. NR : tests/nr/test_hot_ingest_ocr_repli_nr.py
_RACINE = Path(__file__).resolve().parent.parent
_OCR_DIR = _RACINE / "sandbox" / "ocr_textes"


def _ajouter_libs_ocr() -> str:
    import os
    import sys

    libs = os.environ.get("LAFORGE_OCR_LIBS") or str(_RACINE / "sandbox" / "ocr_libs")
    if Path(libs).exists() and libs not in sys.path:
        sys.path.append(libs)
    return libs


def ocr_disponible() -> tuple:
    """(bool, motif) : l'OCR est-il importable DANS CE PROCESSUS (compte + interpreteur) ? Dit des le demarrage du
    service, pas au premier PDF image refuse (2/11)."""
    import getpass

    libs = _ajouter_libs_ocr()
    try:
        import pdfplumber  # noqa: F401
        import rapidocr_onnxruntime  # noqa: F401
        return True, "rapidocr importable (libs %s)" % libs
    except Exception as e:  # noqa: BLE001 - dit avec le compte et la visibilite du dossier
        return False, "%s: %s ; libs=%s visible=%s ; compte=%s" % (
            type(e).__name__, str(e)[:160], libs, Path(libs).exists(), getpass.getuser())


def _ocr_pdf(path: Path) -> str:
    """Texte d'un PDF image par OCR (rapidocr, pages rendues a 200 dpi par pdfplumber). Leve si l'OCR manque."""
    _ajouter_libs_ocr()
    import numpy as np
    import pdfplumber
    from rapidocr_onnxruntime import RapidOCR

    moteur = RapidOCR()
    pages = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            res, _ = moteur(np.array(page.to_image(resolution=200).original.convert("RGB")))
            pages.append("\n".join(x[1] for x in (res or [])))
    return "\n\n".join(pages)


def _ecrire_fragments(source: str, domain: str, fragments: list) -> int:
    """Voie d'ecriture CANONIQUE (celle des veilles rapides) : `ecrire_chunk` (id canonique, aucune troncature muette)
    dans `write_retry`, + `rag_fts` pour les seuls fragments NEUFS (existence par cle primaire -- jamais
    `WHERE chunk_id` sur rag_fts, colonne UNINDEXED = plein scan). Rend le nombre de fragments neufs."""
    from nokido_agent.app import forge_db_path as D

    def ecrire(c):
        neufs = 0
        for t in fragments:
            cid = D.chunk_id(source, t)
            existait = c.execute("SELECT 1 FROM rag_chunks WHERE id=?", (cid,)).fetchone() is not None
            if D.ecrire_chunk(c, source, domain, t).get("refuse"):
                continue
            if not existait:
                c.execute("INSERT INTO rag_fts(chunk_id, text, source, domain) VALUES(?,?,?,?)",
                          (cid, t, source, domain))
                neufs += 1
        return neufs

    return D.write_retry(ecrire)


class IngesteurCanonique:
    """Moteur d'ingestion du depot surveille HORS de la TUI (2/11). `RAGEngine()` est interdit hors hub (il charge toute
    la base) et `app_ctx().rag_engine` y vaut None : sans ce moteur, le demon marquait chaque fichier vu puis
    l'abandonnait en silence. Meme interface que RAGEngine pour `add_document`.
    NR : tests/nr/test_depot_surveille_ingere_sans_moteur_nr.py"""

    async def add_document(self, path, delete_after: bool = False) -> bool:
        from nokido_agent.app.forge_rag_store import MarkdownChunker

        path = Path(path)
        brut = MarkdownChunker.chunk(_extraire_texte(path), 2000, 200)
        frags = [f if isinstance(f, str) else (getattr(f, "text", None) or f.get("text", "")) for f in brut]
        frags = [f for f in frags if f.strip()]
        if not frags:
            return False
        _ecrire_fragments(path.name, _detect_domain(str(path)), frags)
        if delete_after:
            path.unlink(missing_ok=True)
        return True


def _extraire_texte(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        import pypdf
        return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(path)).pages)
    return path.read_text(encoding="utf-8", errors="replace")


def analyser_avant_ingestion(path: Path) -> Dict:
    """{ok, motif, ...} : injection (forge_prompt_guard.detect_injection par fenetres de 2 000 caracteres), caracteres
    invisibles (bidi : 1 suffit ; largeur nulle : plus de 5), PDF sans couche texte. Extraction illisible = refus."""
    try:
        texte = _extraire_texte(path)
    except Exception as e:  # noqa: BLE001 - illisible : on ne l'ingere pas a l'aveugle, et c'est DIT
        return {"ok": False, "motif": "texte illisible (%s) : non ingere" % type(e).__name__}
    ocr = False
    if path.suffix.lower() == ".pdf" and len(texte.strip()) < 200:
        n_couche = len(texte.strip())
        try:
            texte = _ocr_pdf(path)
        except Exception as e:  # noqa: BLE001 - OCR absent ou en echec : refus DIT, jamais une ingestion a vide
            return {"ok": False, "motif": "PDF sans couche texte (%d caracteres extraits) et OCR indisponible (%s: %s) : "
                                          "non ingere" % (n_couche, type(e).__name__, str(e)[:160])}
        if len(texte.strip()) < 200:
            return {"ok": False, "motif": "PDF sans couche texte : OCR trop court (%d caracteres) : non ingere"
                                          % len(texte.strip())}
        ocr = True  # le texte OCR passe les MEMES gardes que tout texte (invisibles, injection) : pas de porte derobee
    from nokido_agent.app.forge_prompt_guard import analyser_contenu_tiers
    verdict = analyser_contenu_tiers(texte)
    if not verdict["ok"]:
        return verdict
    if ocr:
        return {"ok": True, "motif": "aucune alerte (texte OCR)", "caracteres": len(texte), "ocr": True, "texte": texte}
    return {"ok": True, "motif": "aucune alerte", "caracteres": len(texte)}


def _noter_refus(path: Path, verdict: Dict) -> None:
    import json as _json
    try:
        _REFUS.parent.mkdir(parents=True, exist_ok=True)
        with _REFUS.open("a", encoding="utf-8") as f:
            f.write(_json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "fichier": str(path),
                                 "motif": verdict.get("motif")}, ensure_ascii=False) + "\n")
    except OSError:
        logger.warning("[hot_ingest] refus non journalise pour %s", path)


def _build_human_meta(source: str, provenance: str = "tui_drop", auteur_owner: bool = False) -> Dict:
    """Construit le meta JSON pour une ingestion humaine directe : TRUSTED seulement si l'owner en est l'AUTEUR."""
    if not auteur_owner:
        return {
            "ring": EXTERNAL_RING,
            "ring_label": "EXTERNAL",
            "consensus_level": HUMAN_CONSENSUS,
            "trust_score": EXTERNAL_TRUST,
            "mutable": True,
            "verified_by": [{"agent": HUMAN_AUTHOR, "ring": HUMAN_RING, "check": "owner_depot_contenu_tiers",
                             "score": EXTERNAL_TRUST, "ts": datetime.now(timezone.utc).isoformat()}],
            "qualified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "origin_type": "document",
            "provenance": provenance,
            "author": "tiers",
            "cove_skip": False,
        }
    return {
        "ring": HUMAN_RING,
        "ring_label": "TRUSTED",
        "consensus_level": HUMAN_CONSENSUS,
        "trust_score": HUMAN_TRUST,
        "mutable": True,
        "verified_by": [
            {
                "agent": HUMAN_AUTHOR,
                "ring": HUMAN_RING,
                "check": "human_validation",
                "score": HUMAN_TRUST,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        ],
        "qualified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "origin_type": "document",
        "provenance": provenance,
        "author": HUMAN_AUTHOR,
        "cove_skip": True,  # l'humain a fait office de CoVe
    }


def _detect_domain(path_or_url: str) -> str:
    """Détecte le domaine probable depuis le nom du fichier."""
    s = path_or_url.lower()
    if any(x in s for x in ["secu", "kali", "pentest", "cve", "hack"]):
        return "securite"
    if any(x in s for x in ["python", "code", "prog", "dev"]):
        return "code"
    if any(x in s for x in ["linux", "debian", "ubuntu", "kernel"]):
        return "systeme"
    if any(x in s for x in ["reseau", "network", "cisco", "routeur"]):
        return "reseau"
    if any(x in s for x in ["docker", "k8s", "ansible", "ci", "devops"]):
        return "devops"
    if any(x in s for x in ["ia", "llm", "rag", "embedding", "ai"]):
        return "ia"
    return "general"


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion fichier (Fast-Track)
# ─────────────────────────────────────────────────────────────────────────────


async def hot_ingest_file(
    path: Path,
    rag_engine: Any,
    log_fn: Callable[[str], None] = print,
    provenance: str = "tui_drop",
    delete_after: bool = False,
) -> Dict:
    """
    Ingestion prioritaire d'un fichier local.
    Ring 2 (TRUSTED) — l'humain fait office de validateur.

    Returns:
        {"ok": bool, "chunks": int, "source": str, "trust": float, "msg": str}
    """
    from nokido_agent.app.forge_app_context import app_ctx as _actx

    _ac = _actx()
    # moteur de la TUI s'il existe, sinon celui passe, sinon la voie canonique (demon, jobs) -- jamais un abandon muet
    rag_engine = getattr(_ac, "rag_engine", None) or rag_engine or IngesteurCanonique()
    if not path.exists():
        return {"ok": False, "chunks": 0, "source": str(path), "trust": 0, "msg": f"Fichier introuvable: {path}"}

    verdict = analyser_avant_ingestion(path)
    if not verdict["ok"]:
        _noter_refus(path, verdict)
        log_fn(f"[red]⛔ {path.name} NON ingere : {verdict['motif']}[/]")
        return {"ok": False, "quarantaine": True, "chunks": 0, "source": path.name, "trust": 0,
                "msg": verdict["motif"]}
    owner = _auteur_owner(path)
    log_fn(f"[dim]⚡ Fast-track : [bold]{path.name}[/bold] (ring={'TRUSTED' if owner else 'EXTERNAL'})…[/dim]")
    t0 = time.monotonic()

    # PDF image passe par l'OCR : add_document reextrairait le PDF VIDE -- on ingere le texte OCR deja analyse.
    a_ingerer = path
    if verdict.get("ocr"):
        _OCR_DIR.mkdir(parents=True, exist_ok=True)
        a_ingerer = _OCR_DIR / (path.stem + ".ocr.md")
        a_ingerer.write_text("# %s (texte OCR)\n\n%s" % (path.name, verdict["texte"]), encoding="utf-8")
        log_fn(f"[dim]🔎 {path.name} : sans couche texte, OCR -> {a_ingerer.name}[/dim]")
    source = a_ingerer.name

    # Ingestion via RAGEngine standard
    ok = await rag_engine.add_document(a_ingerer, delete_after=delete_after and a_ingerer == path)
    if not ok:
        return {
            "ok": False,
            "chunks": 0,
            "source": source,
            "trust": 0,
            "msg": f"add_document a échoué pour {source}",
        }
    if delete_after and a_ingerer != path:
        path.unlink(missing_ok=True)

    # Patcher le meta des chunks nouvellement insérés avec ring=TRUSTED
    human_meta = _build_human_meta(source, provenance, auteur_owner=owner)
    _patch_source_meta(source, human_meta)

    # Promouvoir immédiatement dans la file prioritaire
    _enqueue_source_promotion(source, priority=HUMAN_PRIORITY)

    elapsed = (time.monotonic() - t0) * 1000
    n = _count_source_chunks(source)
    msg = f"[green]⚡ {source}[/] — {n} chunks · ring={human_meta['ring_label']} · " \
          f"trust={human_meta['trust_score']} · {elapsed:.0f}ms"
    log_fn(msg)
    return {"ok": True, "chunks": n, "source": source, "trust": human_meta["trust_score"], "msg": msg}


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion URL (Fast-Track)
# ─────────────────────────────────────────────────────────────────────────────


async def hot_ingest_url(
    url: str,
    rag_engine: Any,
    log_fn: Callable[[str], None] = print,
    provenance: str = "tui_drop",
) -> Dict:
    """
    Ingestion prioritaire d'une URL.
    Extraction texte via trafilatura → forge_rag_engine.ingest_web_content().

    Returns:
        {"ok": bool, "chunks": int, "source": str, "trust": float, "msg": str}
    """
    log_fn(f"[dim]⚡ Fast-track URL : [bold]{url[:60]}[/bold]…[/dim]")
    t0 = time.monotonic()
    text = ""

    # Extraction texte
    try:
        import trafilatura

        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=True) or ""
    except ImportError:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_hot_ingest.py', 196, exc_info=True)

    if not text:
        # Fallback : requests + strip HTML basique
        try:
            import urllib.request
            import html
            import re

            with urllib.request.urlopen(url, timeout=10) as r:
                raw = r.read().decode("utf-8", errors="replace")
            text = re.sub(r"<[^>]+>", " ", raw)
            text = html.unescape(text)
            text = re.sub(r"\s{3,}", "  ", text)[:50000]
        except Exception as e:
            return {"ok": False, "chunks": 0, "source": url, "trust": 0, "msg": f"Extraction URL échouée: {e}"}

    if len(text.strip()) < 50:
        return {"ok": False, "chunks": 0, "source": url, "trust": 0, "msg": "Contenu extrait trop court"}

    # Source canonique
    from urllib.parse import urlparse

    domain = urlparse(url).netloc.replace("www.", "")
    source = f"url:{domain}"

    # Ingestion via le moteur RAG
    n = await rag_engine.ingest_web_content(
        session_name=source,
        content=text,
        skill=_detect_domain(url),
        meta={"layer": "trusted", "url": url, "ingested_at": datetime.now(timezone.utc).isoformat()},
    )

    if n == 0:
        return {"ok": False, "chunks": 0, "source": url, "trust": 0, "msg": "Aucun chunk ingéré"}

    # Patcher avec meta TRUSTED
    human_meta = _build_human_meta(source, provenance)
    _patch_source_meta(source, human_meta)
    _enqueue_source_promotion(source, priority=HUMAN_PRIORITY)

    elapsed = (time.monotonic() - t0) * 1000
    msg = f"[green]⚡ {domain}[/] — {n} chunks · ring=TRUSTED · trust=0.8 · {elapsed:.0f}ms"
    log_fn(msg)
    return {"ok": True, "chunks": n, "source": source, "trust": HUMAN_TRUST, "msg": msg}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers DB
# ─────────────────────────────────────────────────────────────────────────────


def _patch_source_meta(source: str, human_meta: Dict) -> int:
    """
    Met à jour le meta de tous les chunks d'une source avec les données TRUSTED.
    Opération synchrone légère — SQLite WAL.
    """
    import sqlite3, json

    db = _ROOT / "RAG" / "embeddings.db"
    try:
        conn = sqlite3.connect(str(db))
        conn.execute("PRAGMA journal_mode=WAL")
        rows = conn.execute("SELECT id, meta FROM rag_chunks WHERE source=?", (source,)).fetchall()
        updates = []
        for chunk_id, meta_s in rows:
            meta = json.loads(meta_s) if meta_s else {}
            meta.update(human_meta)
            updates.append((json.dumps(meta, ensure_ascii=False), chunk_id))
        if updates:
            conn.executemany("UPDATE rag_chunks SET meta=? WHERE id=?", updates)
            conn.commit()
        conn.close()
        return len(updates)
    except Exception as e:
        logger.debug(f"[hot_ingest] patch_meta: {e}")
        return 0


def _count_source_chunks(source: str) -> int:
    """Count source chunks.

    Args:
        source: Description.
    """
    import sqlite3

    db = _ROOT / "RAG" / "embeddings.db"
    try:
        conn = sqlite3.connect(str(db))
        n = conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE source=?", (source,)).fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


def _enqueue_source_promotion(source: str, priority: int = 0) -> None:
    """Enfile tous les chunks d'une source dans la queue de promotion."""
    import sqlite3

    db = _ROOT / "RAG" / "embeddings.db"
    try:
        from nokido_agent.app.forge_promotion_queue import get_orchestrator

        orch = get_orchestrator()
        conn = sqlite3.connect(str(db))
        ids = [r[0] for r in conn.execute("SELECT id FROM rag_chunks WHERE source=?", (source,)).fetchall()]
        conn.close()
        # enqueue_sync — thread-safe depuis code synchrone
        for chunk_id in ids:
            orch.enqueue_sync(chunk_id, priority=priority, author_id=HUMAN_AUTHOR, source_exists=True)
        if ids:
            logger.debug(f"[hot_ingest] {len(ids)} chunks enfilés prio={priority}")
    except Exception as e:
        logger.debug(f"[hot_ingest] enqueue: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Hot-Folder Watcher
# ─────────────────────────────────────────────────────────────────────────────


class HotFolderWatcher:
    """
    Surveille data/rag_files/ et ingère les nouveaux fichiers automatiquement
    avec ring=TRUSTED dès qu'ils apparaissent.

    Utilisé quand l'humain copie directement un PDF dans le dossier RAG
    sans passer par la commande @rag download.

    Polling toutes les POLL_INTERVAL secondes (pas d'inotify requis).
    Non-bloquant : thread daemon.
    """

    POLL_INTERVAL = 3.0  # secondes entre chaque scan
    SUPPORTED_EXT = {".pdf", ".txt", ".md"}

    def __init__(self, rag_dir: Path = _RAG_DIR, rag_engine_getter: Callable = None, log_fn: Callable = None) -> None:
        """Init.

        Args:
            rag_dir: Description.
            rag_engine_getter: Description.
            log_fn: Description.
        """
        self._dir = rag_dir
        self._getter = rag_engine_getter  # callable() → rag_engine
        self._log_fn = log_fn or (lambda m: logger.info(m))
        self._seen: set = set()
        # Memoire persistante des fichiers TRAITES (2/11) : sans elle, un depot fait pendant un arret du service etait
        # marque vu au redemarrage et jamais ingere. NR : tests/nr/test_depot_surveille_reprise_nr.py
        # Comparaison au dossier de PRODUCTION litteral, jamais au global `_RAG_DIR` : un test qui le remplace ecrivait
        # sinon dans le vrai sandbox (paye le 2/11).
        _prod = (_RACINE / "data" / "rag_files").resolve()
        self._memo_path = (_RACINE / "sandbox" / "hot_folder_vus.json" if Path(rag_dir).resolve() == _prod
                           else Path(rag_dir).parent / "hot_folder_vus.json")
        self._memo: dict = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        # Indexer les fichiers déjà présents sans les ré-ingérer
        self._init_seen()

    def _init_seen(self) -> None:
        """Marque les fichiers existants comme déjà connus."""
        if not self._dir.exists():
            return
        presents = {f.name: f.stat().st_size for f in self._dir.iterdir() if f.suffix.lower() in self.SUPPORTED_EXT}
        try:
            memo = json.loads(self._memo_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            memo = None
        except Exception as e:  # noqa: BLE001 - memoire illisible : amorce, et c'est DIT
            logger.warning(f"[watcher] memoire {self._memo_path.name} illisible ({type(e).__name__}) : amorce")
            memo = None
        if memo is None:
            # AMORCE (premier demarrage) : les presents sont reputes traites, comme avant -- on ne reingere pas
            # tout l'historique du dossier.
            self._memo = dict(presents)
            self._seen = set(presents)
            self._ecrire_memo()
        else:
            self._memo = dict(memo)
            self._seen = {n for n, t in presents.items() if self._memo.get(n) == t}
            a_faire = sorted(set(presents) - self._seen)
            if a_faire:
                logger.info(f"[watcher] {len(a_faire)} fichier(s) depose(s) pendant l'arret : {a_faire[:5]}")
        logger.debug(f"[watcher] {len(self._seen)} fichiers deja traites")

    def _ecrire_memo(self) -> None:
        try:
            self._memo_path.parent.mkdir(parents=True, exist_ok=True)
            self._memo_path.write_text(json.dumps(self._memo, ensure_ascii=False, indent=0), encoding="utf-8")
        except OSError as e:
            logger.warning(f"[watcher] memoire NON ecrite ({type(e).__name__}) : la reprise apres arret est aveugle")

    def _marquer_vu(self, fname: str) -> None:
        self._seen.add(fname)
        try:
            self._memo[fname] = (self._dir / fname).stat().st_size
        except OSError:
            self._memo[fname] = -1
        self._ecrire_memo()

    def start(self) -> None:
        """Start."""
        if self._running:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="hot-folder-watcher", daemon=True)
        self._thread.start()
        logger.info(f"[watcher] Hot-folder actif : {self._dir}")

    def stop(self) -> None:
        """Stop."""
        self._running = False

    def _loop(self) -> None:
        """Loop."""
        while self._running:
            try:
                self._scan()
            except Exception as e:
                logger.debug(f"[watcher] scan: {e}")
            time.sleep(self.POLL_INTERVAL)

    def _scan(self) -> None:
        """Scan."""
        if not self._dir.exists():
            return
        current = {f.name for f in self._dir.iterdir() if f.suffix.lower() in self.SUPPORTED_EXT}
        new_files = current - self._seen
        for fname in sorted(new_files):
            fpath = self._dir / fname
            # Attendre que le fichier soit stable (copie en cours)
            try:
                s1 = fpath.stat().st_size
                time.sleep(0.5)
                s2 = fpath.stat().st_size
                if s1 != s2:
                    continue  # encore en cours de copie
            except Exception:
                __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_hot_ingest.py', 397, exc_info=True)
                continue

            logger.info(f"[watcher] Nouveau fichier détecté : {fname}")
            self._log_fn(f"[dim]📂 Hot-folder : [bold]{fname}[/bold] détecté → analyse puis ingestion…[/dim]")

            # 2/11 : plus de `if rag_engine:` -- sans moteur (demon, hors TUI), hot_ingest_file prend la voie
            # canonique. Avant, le fichier etait marque vu PUIS abandonne en silence. Un fichier n'est desormais
            # marque vu qu'une fois traite (ingere ou mis en quarantaine) ; un echec est DIT et retente au scan suivant.
            rag_engine = self._getter() if self._getter else None
            coro = hot_ingest_file(fpath, rag_engine, log_fn=self._log_fn, provenance="hot_folder")
            try:
                try:
                    boucle = asyncio.get_running_loop()
                except RuntimeError:
                    boucle = None
                if boucle is not None:  # boucle de la TUI vivante : le resultat arrive plus tard
                    asyncio.run_coroutine_threadsafe(coro, boucle)
                    self._marquer_vu(fname)
                    continue
                r = asyncio.run(coro)
            except Exception as e:  # noqa: BLE001 - dit, et retente au prochain scan
                logger.warning(f"[watcher] ingestion {fname}: {e}")
                self._log_fn(f"[red]⛔ {fname} : echec d'ingestion ({type(e).__name__}: {e}) -- retente au "
                             f"prochain scan[/]")
                continue
            if r.get("ok") or r.get("quarantaine"):
                self._marquer_vu(fname)
            else:
                self._log_fn(f"[red]⛔ {fname} non ingere : {r.get('msg')} -- retente au prochain scan[/]")


# ─────────────────────────────────────────────────────────────────────────────
# Singleton watcher — accessible depuis Nokido.py on_mount
# ─────────────────────────────────────────────────────────────────────────────

_watcher: Optional[HotFolderWatcher] = None


def get_watcher(
    rag_engine_getter: Optional[Callable] = None,
    log_fn: Optional[Callable] = None,
    rag_dir: Path = _RAG_DIR,
) -> HotFolderWatcher:
    """Retourne le watcher singleton, le crée si nécessaire."""
    global _watcher
    if _watcher is None:
        _watcher = HotFolderWatcher(
            rag_dir=rag_dir,
            rag_engine_getter=rag_engine_getter,
            log_fn=log_fn,
        )
    return _watcher

"""
forge_circadian_loop.py — Nokido v18.5 Cycle Circadien
========================================================
Daemon asynchrone de background processing.
S'active lors des phases de dormance du Hub (pas d'activite detectee).

PHASES :
  0. Detecteur de dormance  (asyncio, pas de CRON OS)
  1. Nettoyage synaptique   (forge_snapshot_janitor — zero LLM)
  2. Reve semantique        (Ollama local — connexions graphe intuition)
  3. Reprise architecturale (LLM distant — post-mortem taches echouees)
  4. Eveil / Epiphanie      (notification TUI resume nuit)

SECURITE :
  - Phase 3 : payload strict write_recommendation uniquement (RBAC)
  - Interruption propre : point de controle ENTRE les phases
  - Si une phase echoue : log + continuer la suivante (pas de crash)
  - Break-glass : FORGE_MCP_TOKEN bypass total si besoin
"""

from __future__ import annotations
import asyncio
import datetime
import hashlib
import json
import logging
import os
import random
import sqlite3
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("forge.circadian")

# ============================================================
# CONFIGURATION
# ============================================================

DORMANCY_MINUTES = int(os.environ.get("CIRCADIAN_DORMANCY_MIN", "120"))
CHECK_INTERVAL_S = int(os.environ.get("CIRCADIAN_CHECK_S", "60"))
DREAM_WALKS = int(os.environ.get("CIRCADIAN_DREAM_WALKS", "5"))
DREAM_WEIGHT_MIN = float(os.environ.get("CIRCADIAN_DREAM_WEIGHT", "0.8"))
POSTMORTEM_HOURS = int(os.environ.get("CIRCADIAN_POSTMORTEM_H", "24"))


def _db() -> Path:
    return Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"


def _conn(timeout=60) -> sqlite3.Connection:
    c = sqlite3.connect(str(_db()), timeout=timeout)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


# ============================================================
# DETECTEUR DE DORMANCE
# ============================================================


def _is_dormant() -> bool:
    """
    Retourne True si aucune activite recente depuis DORMANCY_MINUTES.
    Criteres (OR suffisant pour etre actif) :
      - tui_commands avec status=pending dans les X minutes
      - agent_tasks avec status pending/running/review modifiees recemment
      - tui_notifications ajoutees recemment (proxy d activite utilisateur)
    """
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(minutes=DORMANCY_MINUTES)).isoformat()

    try:
        conn = _conn(timeout=5)
        # Activite commandes TUI
        cmd = conn.execute(
            "SELECT COUNT(*) FROM tui_commands WHERE status='pending' AND created_at > ?", (cutoff,)
        ).fetchone()[0]
        if cmd > 0:
            conn.close()
            return False

        # Taches actives recentes
        tasks = conn.execute(
            "SELECT COUNT(*) FROM agent_tasks WHERE status IN ('pending','running','review') AND updated_at > ?",
            (cutoff,),
        ).fetchone()[0]
        if tasks > 0:
            conn.close()
            return False

        # Notifications recentes (proxy activite)
        notifs = conn.execute("SELECT COUNT(*) FROM tui_notifications WHERE created_at > ?", (cutoff,)).fetchone()[0]
        conn.close()
        return notifs == 0

    except Exception as e:
        logger.debug(f"[circadian] dormance check err: {e}")
        return False


# ============================================================
# PHASE 1 : NETTOYAGE SYNAPTIQUE (zero LLM)
# ============================================================


async def phase1_janitor() -> dict:
    """Purge snapshots, VACUUM. Deterministe, aucun LLM."""
    logger.info("[circadian:P1] Nettoyage synaptique...")
    t0 = time.perf_counter()
    result = {}
    try:
        from nokido_agent.tools.forge_snapshot_janitor import run_janitor

        result = await asyncio.get_event_loop().run_in_executor(None, lambda: run_janitor(dry_run=False))
        logger.info(f"[circadian:P1] Janitor: {result}")
        # Cleanup jti_cache (anti-replay JWT) — purge tokens expirés
        try:
            import sqlite3 as _sq, time as _ti, os as _co

            _db = _co.path.join(_co.path.dirname(__file__), "..", "RAG", "embeddings.db")
            with _sq.connect(_db, timeout=5) as _conn:
                _n = _conn.execute("DELETE FROM jti_cache WHERE exp < ?", (int(_ti.time()),)).rowcount
                _conn.commit()
            logger.info(f"[circadian:P1] jti_cache: {_n} tokens expirés purgés")
        except Exception as _je:
            logger.debug(f"[circadian:P1] jti_cache skip: {_je}")
    except Exception as e:
        logger.error(f"[circadian:P1] Janitor erreur: {e}")
        result["error"] = str(e)

    # NOTE 2026-08-14 : la reconstruction FTS a d'abord ete cablee ICI, puis
    # DEPLACEE dans `forge_circadian.PHASE_PROGRAM[Phase.NREM3]`. Motif : ce
    # module definit un cycle en quatre phases que personne n'appelle —
    # `phase1_janitor` et `_run_night_cycle` n'ont aucun appelant hors de ce
    # fichier, verifie. Le programme reellement execute est celui de
    # `forge_circadian`, dont `sandbox/circadian_state.json` horodate les
    # declenchements. Cabler une tache de maintenance ici revenait a poser un
    # garde qui ne garde rien — le defaut meme que la passe anti-regression
    # de ce jour traquait.
    result["duration_ms"] = int((time.perf_counter() - t0) * 1000)
    return result


# ============================================================
# PHASE 2 : REVE SEMANTIQUE (Ollama local)
# ============================================================


async def _embed_text(text: str) -> Optional[list]:
    """Embedding via Ollama local (bge-m3)."""
    try:
        import aiohttp

        async with aiohttp.ClientSession() as s:
            for _ in range(3):
                try:
                    async with s.post(
                        "http://127.0.0.1:11434/api/embeddings",
                        json={"model": "bge-m3", "prompt": text[:1200]},
                        timeout=aiohttp.ClientTimeout(total=20),
                    ) as r:
                        if r.status == 200:
                            d = await r.json()
                            return d.get("embedding")
                        await asyncio.sleep(0.5)
                except Exception:
                    await asyncio.sleep(0.5)
    except Exception as e:
        logger.debug(f"[circadian:P2] embed err: {e}")
    return None


async def _local_llm_link(text_a: str, text_b: str) -> dict:
    """
    Prompt Ollama local pour detecter un lien semantic entre deux chunks.
    Retourne {"link_found": bool, "description": str, "weight": float}
    """
    prompt = (
        "En tant qu architecte systeme, trouve un lien technique cache, "
        "une vulnerabilite croisee ou une correlation inattendue entre ces deux concepts. "
        "Reponds UNIQUEMENT par un JSON valide sans markdown : "
        '{"link_found": true/false, "description": "...", "weight": 0.0-1.0}\n\n'
        f"CONCEPT A:\n{text_a[:600]}\n\nCONCEPT B:\n{text_b[:600]}"
    )
    try:
        import aiohttp

        async with aiohttp.ClientSession() as s:
            async with s.post(
                "http://127.0.0.1:11434/api/generate",
                json={
                    "model": "qwen2.5-coder:7b",
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.4, "num_predict": 200},
                },
                timeout=aiohttp.ClientTimeout(total=60),
            ) as r:
                if r.status == 200:
                    d = await r.json()
                    raw = d.get("response", "").strip()
                    # Extraire JSON de la reponse
                    start = raw.find("{")
                    end = raw.rfind("}") + 1
                    if start >= 0 and end > start:
                        return json.loads(raw[start:end])
    except Exception as e:
        logger.debug(f"[circadian:P2] llm link err: {e}")
    return {"link_found": False, "description": "", "weight": 0.0}


async def phase2_dream(interrupt_flag: asyncio.Event) -> dict:
    """
    Random Walk semantique sur rag_graph_nodes.
    Cible les noeuds a fort degree dans des domaines differents.
    Cristallise les liens > DREAM_WEIGHT_MIN dans rag_graph_edges.
    """
    logger.info(f"[circadian:P2] Reve semantique ({DREAM_WALKS} walks)...")
    t0 = time.perf_counter()
    new_edges, walks_done = 0, 0

    try:
        conn = _conn()
        # Selectionner noeuds eligibles : fort degree, domaines varies
        nodes = conn.execute(
            "SELECT chunk_id, source, domain FROM rag_graph_nodes WHERE degree > 5 ORDER BY RANDOM() LIMIT 100"
        ).fetchall()

        if len(nodes) < 2:
            conn.close()
            return {"walks": 0, "new_edges": 0, "reason": "pas assez de noeuds"}

        for _ in range(DREAM_WALKS):
            if interrupt_flag.is_set():
                logger.info("[circadian:P2] Interruption propre demandee")
                break

            # Choisir 2 noeuds de domaines differents
            attempts = 0
            node_a, node_b = None, None
            while attempts < 20:
                a, b = random.sample(nodes, 2)
                if a[2] != b[2]:  # domaines differents
                    # Verifier absence d arete entre eux
                    existing = conn.execute(
                        "SELECT COUNT(*) FROM rag_graph_edges WHERE src=? AND dst=?", (a[0], b[0])
                    ).fetchone()[0]
                    if existing == 0:
                        node_a, node_b = a, b
                        break
                attempts += 1

            if node_a is None:
                continue

            # Recuperer les textes depuis rag_chunks
            chunk_a = conn.execute("SELECT text FROM rag_chunks WHERE id=? LIMIT 1", (node_a[0],)).fetchone()
            chunk_b = conn.execute("SELECT text FROM rag_chunks WHERE id=? LIMIT 1", (node_b[0],)).fetchone()

            if not chunk_a or not chunk_b:
                continue

            # Spike cognitif via LLM local
            link = await _local_llm_link(chunk_a[0], chunk_b[0])
            walks_done += 1

            if link.get("link_found") and link.get("weight", 0) >= DREAM_WEIGHT_MIN:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO rag_graph_edges(src, dst, rel_type, weight) VALUES(?,?,?,?)",
                        (node_a[0], node_b[0], "semantic_intuition", link["weight"]),
                    )
                    conn.execute(
                        "UPDATE rag_graph_nodes SET degree=degree+1 WHERE chunk_id IN (?,?)", (node_a[0], node_b[0])
                    )
                    conn.commit()
                    new_edges += 1
                    logger.info(
                        f"[circadian:P2] Intuition: {node_a[2]}<->{node_b[2]} "
                        f"w={link['weight']:.2f} — {link['description'][:80]}"
                    )
                except Exception as e:
                    logger.debug(f"[circadian:P2] edge insert err: {e}")

        conn.close()

    except Exception as e:
        logger.error(f"[circadian:P2] Reve erreur: {e}")

    return {
        "walks": walks_done,
        "new_edges": new_edges,
        "duration_ms": int((time.perf_counter() - t0) * 1000),
    }


# ============================================================
# PHASE 3 : REPRISE ARCHITECTURALE (LLM distant)
# ============================================================

POSTMORTEM_TOOLS = [
    {
        "name": "write_recommendation",
        "description": (
            "Enregistre une recommandation d amelioration dans la base Nokido. SEUL outil autorise en mode nocturne."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "param": {"type": "string", "description": "Parametre ou module concerne"},
                "current_value": {"type": "string"},
                "suggested_value": {"type": "string"},
                "reason": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "source_module": {"type": "string"},
            },
            "required": ["param", "reason", "confidence"],
        },
    }
]


async def phase3_postmortem(interrupt_flag: asyncio.Event) -> dict:
    """
    Collecte les taches failed/rejected des dernieres POSTMORTEM_HOURS.
    Soumet au LLM distant avec outil UNIQUEMENT write_recommendation.
    """
    if interrupt_flag.is_set():
        return {"skipped": True, "reason": "interruption"}

    logger.info(f"[circadian:P3] Post-mortem taches {POSTMORTEM_HOURS}h...")
    t0 = time.perf_counter()
    recs_written = 0

    try:
        conn = _conn()
        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=POSTMORTEM_HOURS)).isoformat()

        failed = conn.execute(
            "SELECT id, title, task_type, description, plan, results, forge_notes "
            "FROM agent_tasks "
            "WHERE (status='failed' OR forge_verdict='rejected') "
            "AND updated_at > ? ORDER BY updated_at DESC LIMIT 10",
            (cutoff,),
        ).fetchall()
        conn.close()

        if not failed:
            logger.info("[circadian:P3] Aucune tache echouee — skip")
            return {"tasks_analyzed": 0, "recs_written": 0, "duration_ms": 0}

        # Compiler le rapport
        rapport = "RAPPORT POST-MORTEM NOCTURNE\n\n"
        for row in failed:
            rapport += f"TACHE: {row[1]} (type={row[2]})\n"
            rapport += f"Description: {row[3][:200]}\n"
            rapport += f"Plan: {row[4][:300]}\n"
            rapport += f"Resultats: {row[5][:200]}\n"
            rapport += f"Notes forge: {row[6][:100]}\n"
            rapport += "---\n"

        rapport += (
            "\nAnalyse ces echecs et pour chacun utilise l outil write_recommendation "
            "pour inserer une recommandation concrete dans la base. "
            "Concentre-toi sur les causes racines et les corrections architecturales."
        )

        # Appel LLM distant avec payload strict
        try:
            from nokido_agent.app.forge_rbac import get_rbac

            rbac = get_rbac()
            base_payload = {
                "messages": [{"role": "user", "content": rapport}],
                "tools": POSTMORTEM_TOOLS,
                "max_tokens": 1000,
            }
            # Validation RBAC — seul write_recommendation autorise
            filtered = rbac.filter_tools_payload(base_payload, "agt_claude")
            if not any(t["name"] == "write_recommendation" for t in filtered.get("tools", [])):
                logger.error("[circadian:P3] write_recommendation bloque par RBAC — abort")
                return {"error": "RBAC bloque write_recommendation", "duration_ms": 0}

            # S assurer qu aucun outil dangereux n a ete injecte
            allowed_names = {t["name"] for t in filtered["tools"]}
            assert allowed_names == {"write_recommendation"}, f"Outils non autorises: {allowed_names}"

        except AssertionError as e:
            logger.error(f"[circadian:P3] Securite violation: {e}")
            return {"error": str(e)}

        # Appel agent distant
        try:
            from nokido_agent.app.forge_agent_proxy import ask_claude

            response = await ask_claude(rapport)
            resp_text = str(response)

            # Parser les write_recommendation de la reponse
            conn2 = _conn()
            if "write_recommendation" in resp_text or "param" in resp_text:
                # Extraire JSON des recommandations
                import re

                json_blocks = re.findall(r"\{[^}]+\}", resp_text)
                for block in json_blocks:
                    try:
                        rec = json.loads(block)
                        if "param" in rec and "reason" in rec:
                            conn2.execute(
                                "INSERT OR IGNORE INTO orchestrator_recommendations "
                                "(param, current_value, suggested_value, reason, confidence, source_module) "
                                "VALUES (?,?,?,?,?,?)",
                                (
                                    rec.get("param", ""),
                                    rec.get("current_value", ""),
                                    rec.get("suggested_value", ""),
                                    rec.get("reason", ""),
                                    float(rec.get("confidence", 0.7)),
                                    "circadian_postmortem",
                                ),
                            )
                            recs_written += 1
                    except Exception:
                        pass
            conn2.commit()
            conn2.close()

        except Exception as e:
            logger.error(f"[circadian:P3] LLM distant erreur: {e}")

    except Exception as e:
        logger.error(f"[circadian:P3] Post-mortem erreur: {e}")

    return {
        "tasks_analyzed": len(failed) if "failed" in dir() else 0,
        "recs_written": recs_written,
        "duration_ms": int((time.perf_counter() - t0) * 1000),
    }


# ============================================================
# PHASE 4 : EVEIL / EPIPHANIE (notification TUI)
# ============================================================


async def phase4_epiphany(phase_results: dict) -> None:
    """Agrege les resultats de la nuit et insere une notification TUI."""
    logger.info("[circadian:P4] Epiphanie — preparation rapport matinal...")

    try:
        conn = _conn()

        # Nouvelles intuitions semantiques de la nuit
        new_intuitions = phase_results.get("dream", {}).get("new_edges", 0)
        new_recs = phase_results.get("postmortem", {}).get("recs_written", 0)
        janitor = phase_results.get("janitor", {})
        deleted = (
            janitor.get("r1_update_old", 0) + janitor.get("r2_delete_orphan", 0) + janitor.get("r3_old_snapshots", 0)
        )

        # Construire le message
        lines = ["Nokido a travaille cette nuit :"]
        if deleted > 0:
            lines.append(f"  Nettoyage : {deleted} snapshots purges")
        if new_intuitions > 0:
            # Recuperer les dernieres intuitions
            edges = conn.execute(
                "SELECT src, dst, weight FROM rag_graph_edges "
                "WHERE rel_type='semantic_intuition' "
                "ORDER BY rowid DESC LIMIT 3"
            ).fetchall()
            lines.append(f"  Intuitions : {new_intuitions} nouvelles connexions semantiques")
            for e in edges:
                lines.append(f"    • {e[0][:12]}↔{e[1][:12]} (w={e[2]:.2f})")
        if new_recs > 0:
            lines.append(f"  Recommandations : {new_recs} propositions d amelioration en attente")
        if len(lines) == 1:
            lines.append("  Rien de nouveau — systeme stable")

        message = "\n".join(lines)

        # Inserer dans tui_notifications
        conn.execute(
            "INSERT INTO tui_notifications(source, type, message, payload, status) VALUES(?,?,?,?,?)",
            (
                "hub",
                "info",
                message,
                json.dumps({"circadian": True, "phases": phase_results}),
                "unread",
            ),
        )
        conn.commit()
        conn.close()
        logger.info(f"[circadian:P4] Notification inseree: {len(message)} chars")

    except Exception as e:
        logger.error(f"[circadian:P4] Epiphanie erreur: {e}")


# ============================================================
# DAEMON PRINCIPAL
# ============================================================


class CircadianLoop:
    """
    Daemon asynchrone du cycle circadien Nokido.
    Lance via : asyncio.create_task(CircadianLoop().run())
    """

    def __init__(self):
        self._running = False
        self._dormant = False
        self._interrupt = asyncio.Event()  # signal d interruption entre phases

    def wake(self) -> None:
        """Reveille le systeme (interruption propre entre les phases)."""
        if self._dormant:
            self._interrupt.set()
            logger.info("[circadian] Signal de reveil recu")

    async def run(self) -> None:
        """Boucle principale — tourne indefiniment."""
        self._running = True
        logger.info(f"[circadian] Daemon demarre (dormance={DORMANCY_MINUTES}min)")

        while self._running:
            try:
                await asyncio.sleep(CHECK_INTERVAL_S)

                if not self._dormant and _is_dormant():
                    logger.info("[circadian] Systeme DORMANT — sequence nocturne...")
                    self._dormant = True
                    self._interrupt.clear()
                    await self._run_night_cycle()
                    self._dormant = False
                    logger.info("[circadian] Sequence nocturne terminee")

                elif self._dormant and not _is_dormant():
                    # Reveil detecte entre cycles
                    self._interrupt.set()

            except asyncio.CancelledError:
                logger.info("[circadian] Daemon annule proprement")
                break
            except Exception as e:
                logger.error(f"[circadian] Erreur boucle: {e}")
                await asyncio.sleep(30)

    async def _run_night_cycle(self) -> None:
        """Execute les phases dans l ordre. Point de controle entre chaque phase."""
        results = {}
        ts_start = datetime.datetime.utcnow().isoformat()

        # Phase 0.5 — Diagnostic sante (lacunes + qualite donnees + audit constantes)
        # Tourne en debut de cycle nocturne pour que les phases suivantes voient
        # les lacunes (ex: phase1 janitor peut purger les hash dups detectes ici).
        try:
            from nokido_agent.app.forge_health_diagnostic import run_cycle as _health_cycle

            results["health"] = _health_cycle()
            logger.info(
                f"[circadian] P0.5 health score={results['health']['score']}/100 gaps={results['health']['gaps_count']}"
            )
        except Exception as e:
            logger.warning(f"[circadian] P0.5 health skip: {e}")
            results["health"] = {"error": str(e)}

        # Phase 1 — toujours executee (deterministe)
        try:
            results["janitor"] = await phase1_janitor()
        except Exception as e:
            logger.error(f"[circadian] P1 crash: {e}")
            results["janitor"] = {"error": str(e)}

        if self._interrupt.is_set():
            logger.info("[circadian] Interruption apres P1")
            await phase4_epiphany(results)
            return

        # Phase 2 — reve semantique (Ollama local)
        try:
            results["dream"] = await phase2_dream(self._interrupt)
        except Exception as e:
            logger.error(f"[circadian] P2 crash: {e}")
            results["dream"] = {"error": str(e)}

        if self._interrupt.is_set():
            logger.info("[circadian] Interruption apres P2")
            await phase4_epiphany(results)
            return

        # Phase 3 — post-mortem (LLM distant)
        try:
            results["postmortem"] = await phase3_postmortem(self._interrupt)
        except Exception as e:
            logger.error(f"[circadian] P3 crash: {e}")
            results["postmortem"] = {"error": str(e)}

        # Phase 4 — toujours executee (epiphanie)
        results["ts_start"] = ts_start
        results["ts_end"] = datetime.datetime.utcnow().isoformat()
        await phase4_epiphany(results)

    def stop(self) -> None:
        self._running = False
        self._interrupt.set()


# Singleton
_loop_instance: Optional[CircadianLoop] = None


def get_circadian_loop() -> CircadianLoop:
    global _loop_instance
    if _loop_instance is None:
        _loop_instance = CircadianLoop()
    return _loop_instance


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    async def _test():
        import sys as _s, os as _o

        _lf = _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
        for _p in [_o.path.join(_lf, "app"), _o.path.join(_lf, "tools")]:
            if _p not in _s.path:
                _s.path.insert(0, _p)
        print("=== forge_circadian_loop self-test ===")
        loop = CircadianLoop()

        # Test detecteur dormance
        dormant = _is_dormant()
        print(f"  Dormant actuellement: {dormant}")

        # Test Phase 1 (dry_run via janitor)
        print("  Phase 1 (janitor dry-run)...")
        from nokido_agent.tools.forge_snapshot_janitor import run_janitor

        r = run_janitor(dry_run=True)
        print(f"    {r}")

        # Test Phase 4 (notification)
        print("  Phase 4 (epiphanie test)...")
        await phase4_epiphany({"janitor": {"r1_update_old": 5}, "dream": {"new_edges": 2}})
        print("    Notification inseree")

        print("Self-test PASS")

    asyncio.run(_test())

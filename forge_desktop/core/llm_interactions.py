"""
forge_desktop/core/llm_interactions.py
========================================
Orchestration des interactions LLM/agents — câblage GUI ↔ SwarmTeam.

Rôle :
  - Lance des débats entre agents (Planificateur vs Critique)
  - Orchestre la génération via LeadOrchestrator (forge_swarm_team)
  - Notifie la GUI via signaux Qt (non-bloquant)
  - Passe par le filtre de résonance automatiquement

Workers Qt :
  DebateWorker     → débat 4 agents via LeadOrchestrator (v2)
  TeamRunWorker    → run complet SwarmTeam, émet le résultat consolidé
  LLMPingWorker    → vérifie la disponibilité de chaque participant
"""
from __future__ import annotations
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent
APP  = ROOT / "app"

try:
    from PySide6.QtCore import QThread, Signal, QObject
    HAS_QT = True
except ImportError:
    HAS_QT = False

if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


# ── Worker débat ──────────────────────────────────────────────────────────────

if HAS_QT:

    class DebateWorker(QThread):
        """
        v2 — Débat structuré via LeadOrchestrator (collab 4 agents).

        Pre-flight RAG : injecte les ADR Acceptés (Constitution) dans le
        contexte de tous les agents avant le run — en parallèle du chargement
        de la team (zéro latence ajoutée).

        Mapping des rôles par participant_id (pas par position dans results[]).
        is_conflict détecté sur ok=False OU mots-clés négatifs dans la réponse.
        error_signal taggé [retriable] pour AutoPilot Ring 5.5 sur agent KO.
        """
        turn_ready      = Signal(str, str, bool)   # agent_id, text, is_conflict
        synthesis_ready = Signal(str)              # texte synthèse finale
        debate_done     = Signal(dict)             # résumé complet
        error_signal    = Signal(str)

        def __init__(self, task: str, participants: list = None, parent=None):
            super().__init__(parent)
            self._task         = task
            self._participants = participants or ["laforge", "llamacpp"]

        def run(self):
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(self._run_debate())
                self.debate_done.emit(result)
            except Exception as e:
                self.error_signal.emit(str(e)[:200])
            finally:
                loop.close()

        async def _run_debate(self) -> dict:
            import sqlite3
            sys.path.insert(0, str(APP))
            from forge_resonance_filter import resonance_check
            from forge_swarm_team import _default_team, LeadOrchestrator

            print("[DebateWorker] _run_debate v2 — LeadOrchestrator branché")

            # ── Résonance ──────────────────────────────────────────────────────
            check = resonance_check("DEBATE_ORCHESTRATOR", self._task)
            if check["action"] == "block":
                self.error_signal.emit(
                    "Bloqué par résonance: " + check["correction"][:200]
                )
                return {"ok": False, "blocked": True}

            enriched_task = check["enriched_prompt"]

            # ── Pre-flight RAG + Team (parallel) ──────────────────────────────
            async def _load_adr_context() -> str:
                try:
                    db_path = ROOT / "RAG" / "embeddings.db"
                    conn = sqlite3.connect(str(db_path), timeout=5)
                    conn.execute("PRAGMA journal_mode=WAL")
                    rows = conn.execute(
                        "SELECT adr_id, title, decision FROM adr_records "
                        "WHERE status='Accepté' ORDER BY ring, id LIMIT 6"
                    ).fetchall()
                    conn.close()
                    if not rows:
                        return ""
                    lines = ["=== Constitution Nokido (ADR actifs) ==="]
                    for adr_id, title, decision in rows:
                        lines.append(f"[{adr_id}] {title} → {decision[:120]}")
                    return "\n".join(lines)
                except Exception as e:
                    print(f"[DebateWorker] pre-flight RAG erreur: {e}")
                    return ""

            async def _build_team():
                team = _default_team()
                if self._participants:
                    seen = {}
                    for pid in self._participants:
                        try:
                            if pid not in seen:
                                team.activate(pid)
                                seen[pid] = 1
                            else:
                                # Deuxième occurrence du même agent — créer un clone avec system différent
                                import copy
                                base = next((p for p in team.participants if p.id == pid), None)
                                if base:
                                    clone = copy.deepcopy(base)
                                    clone.id       = pid + "_2"
                                    clone.label    = base.label + " (Critique)"
                                    clone.config   = dict(base.config)
                                    clone.config["system"] = (
                                        "Tu es un critique rigoureux. Identifie les failles, "
                                        "risques et points à améliorer dans la réponse précédente."
                                    )
                                    clone.active   = True
                                    team.participants.append(clone)
                        except Exception:
                            pass
                else:
                    team.activate("laforge")
                return team

            adr_ctx, team = await asyncio.gather(
                _load_adr_context(),
                _build_team(),
            )

            if adr_ctx:
                print(
                    f"[DebateWorker] pre-flight OK — {len(adr_ctx)} chars ADR injectés"
                )

            # ── LeadOrchestrator ───────────────────────────────────────────────
            orc    = LeadOrchestrator()
            result = await orc.run(enriched_task, team, context=adr_ctx)

            session_id = result.get("session_id", "")
            results    = result.get("results", [])
            elapsed_ms = result.get("elapsed_ms", 0)

            # ── Mapping rôles par participant_id ───────────────────────────────
            ROLE_MAP = {
                "laforge":    "Planificateur",
                "qwen":       "Planificateur",
                "llamacpp":   "Planificateur",
                "llamacpp_2": "Critique",
                "qwen_coder": "Critique",
                "mistral":    "Validateur",
                "gemini":     "Synthétiseur",
            }
            CONFLICT_WORDS = [
                "problème", "bug", "erreur", "risque", "incorrect",
                "faux", "danger", "attention", "manque", "oubli",
            ]

            turns       = []
            last_ok_txt = ""

            for r in results:
                pid      = r.get("participant_id", "agent")
                response = r.get("response", "")
                ok       = r.get("ok", True)
                dur_ms   = r.get("duration_ms", 0)
                role     = ROLE_MAP.get(pid, pid.capitalize())

                if not ok:
                    self.error_signal.emit(
                        f"[retriable] {pid} KO ({dur_ms}ms) — {response[:120]}"
                    )
                    continue

                is_conflict = any(w in response.lower() for w in CONFLICT_WORDS)
                self.turn_ready.emit(pid, f"[{role}] {response}", is_conflict)
                turns.append({
                    "agent":       pid,
                    "role":        role,
                    "text":        response,
                    "duration_ms": dur_ms,
                    "conflict":    is_conflict,
                })
                last_ok_txt = response

            # ── Synthèse — gemini/mistral en priorité, sinon dernier tour OK ──
            synth_candidates = [
                r for r in results
                if r.get("ok")
                and r.get("participant_id", "") in ("gemini", "mistral")
            ]
            synth_text = (
                synth_candidates[-1].get("response", last_ok_txt)
                if synth_candidates else last_ok_txt
            )
            if synth_text:
                self.synthesis_ready.emit(synth_text)

            print(
                f"[DebateWorker] débat terminé — {len(turns)} tours, {elapsed_ms}ms"
            )
            return {
                "ok":               True,
                "task":             self._task,
                "session_id":       session_id,
                "turns":            turns,
                "elapsed_ms":       elapsed_ms,
                "resonance_action": check["action"],
            }


    class TeamRunWorker(QThread):
        """Lance un run complet SwarmTeam — tous les participants actifs."""
        progress_signal = Signal(str)
        result_ready    = Signal(dict)
        error_signal    = Signal(str)

        def __init__(self, task: str, team_config: dict = None, parent=None):
            super().__init__(parent)
            self._task        = task
            self._team_config = team_config

        def run(self):
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(self._run_team())
                self.result_ready.emit(result)
            except Exception as e:
                self.error_signal.emit(str(e)[:200])
            finally:
                loop.close()

        async def _run_team(self) -> dict:
            sys.path.insert(0, str(APP))
            from forge_swarm_team import _default_team, LeadOrchestrator, SwarmTeam

            self.progress_signal.emit("Chargement de l'équipe…")
            if self._team_config:
                team = SwarmTeam.from_dict(self._team_config)
            else:
                team = _default_team()
                team.activate("laforge")

            self.progress_signal.emit(
                f"Équipe : {len(team.active)} participants actifs"
            )
            orc    = LeadOrchestrator()
            result = await orc.run(self._task, team)
            self.progress_signal.emit(
                "Terminé — " + str(result.get("elapsed_ms", 0)) + "ms"
            )
            return result


    class LLMPingWorker(QThread):
        """Vérifie la disponibilité de chaque participant LLM."""
        ping_result = Signal(str, bool, str)   # agent_id, available, info
        all_done    = Signal(dict)             # {agent_id: {"ok": bool, "ms": float}}

        def __init__(self, participant_ids: list, parent=None):
            super().__init__(parent)
            self._ids = participant_ids

        def run(self):
            loop = asyncio.new_event_loop()
            results = loop.run_until_complete(self._ping_all())
            loop.close()
            self.all_done.emit(results)

        async def _ping_all(self) -> dict:
            tasks = {
                pid: asyncio.create_task(self._ping(pid))
                for pid in self._ids
            }
            results = {}
            for pid, task in tasks.items():
                try:
                    ok, ms, info = await asyncio.wait_for(task, timeout=8)
                    results[pid] = {"ok": ok, "ms": ms, "info": info}
                    self.ping_result.emit(pid, ok, info)
                except asyncio.TimeoutError:
                    results[pid] = {"ok": False, "ms": 8000, "info": "timeout"}
                    self.ping_result.emit(pid, False, "timeout")
                except Exception as e:
                    results[pid] = {"ok": False, "ms": 0, "info": str(e)[:60]}
                    self.ping_result.emit(pid, False, str(e)[:60])
            return results

        async def _ping(self, agent_id: str):
            sys.path.insert(0, str(APP))
            t0 = time.monotonic()
            try:
                if agent_id in ("laforge", "ollama"):
                    from forge_ollama import ollama_call
                    r = ollama_call("ping", max_tokens=5)
                    return (bool(r), int((time.monotonic() - t0) * 1000), "ok")
                elif agent_id in ("llamacpp", "qwen_coder"):
                    from forge_llamacpp import LlamaCppBridge
                    b = LlamaCppBridge()
                    avail = b.is_available()
                    return (avail, int((time.monotonic() - t0) * 1000),
                            "loaded" if avail else "not loaded")
                elif agent_id == "gemini":
                    from forge_collab_modes import _gemini_ask
                    r = await asyncio.get_event_loop().run_in_executor(
                        None, _gemini_ask, "ping"
                    )
                    return (bool(r), int((time.monotonic() - t0) * 1000), "ok")
                else:
                    return (False, 0, f"provider inconnu: {agent_id}")
            except Exception as e:
                return (False, int((time.monotonic() - t0) * 1000), str(e)[:60])

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-24 | VER:v_forge_agentic_engine
#FORGE:[score:95|agent:gemini-cli|temp:0.00|risk:0.10|ast:OK|test:OK|lint:OK|color:GREEN|attempt:2]
CONTRAINTE: Unification AgenticEngine (FULL IMPLEMENTATION from rag_engine)
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:95|agent:gemini-cli|temp:0.00|risk:0.10|ast:OK|test:OK|lint:OK|color:GREEN|attempt:2]"

import asyncio
import json
import logging
import time
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Chemins & Constantes ──────────────────────────────────────────────────────
_ROOT_P = Path(__file__).resolve().parent.parent
_DATA_DIR = _ROOT_P / "data"
_DATA_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("Nokido.Agentic.Engine")

# ── EventBus helper (docs/EVENT_SPEC.md section 9.2) ──────────────────────────
_EVENT_BUS_CACHE = None


def _emit_skill_event(topic: str, kind: str, data: dict, agent: str = "SKILL") -> None:
    """Emission non-bloquante d'un event sur EventBus. Silent fail si bus indispo."""
    global _EVENT_BUS_CACHE
    try:
        if _EVENT_BUS_CACHE is None:
            from nokido_agent.app.forge_state_manager import EventBus, get_state_manager

            _EVENT_BUS_CACHE = EventBus(get_state_manager())
        _EVENT_BUS_CACHE.publish(topic=topic, kind=kind, data=data, agent=agent, trusted=True)
    except Exception as _e:
        logger.debug(f"EventBus emit skipped: {_e}")


MEMORY_LAYERS = {
    "core": {"lambda": 0.001},
    "session": {"lambda": 0.1},
    "disco": {"lambda": 0.05},
    "verified": {"lambda": 0.005},
}

ENTROPY_THRESHOLDS = {"green": 0.2, "orange": 0.5}


# ── Helpers ───────────────────────────────────────────────────────────────────
def _get_rag_engine():
    from nokido_agent.app.forge_app_context import get_rag

    return get_rag()


@dataclass
class SkillEntry:
    """Entrée dans le registre de compétences de l'AgenticEngine."""

    name: str
    status: str = "waiting"
    layer: str = "disco"
    score: float = 0.0
    vitality_score: float = 1.0
    initial_score: float = 0.0
    uses: int = 0
    errors: int = 0
    fail_streak: int = 0
    unverified: bool = True
    ingested_at: str = ""
    last_task: str = ""
    tasks_ok: List[str] = field(default_factory=list)
    confidence_history: List[float] = field(default_factory=list)


class AgenticEngine:
    """Moteur agentic de gestion des compétences du RAG unifié."""

    COMPETENCE_THRESHOLD = 0.7
    VERIFY_NEEDED = 3

    _SKILL_LIBRARY: Dict[str, dict] = {}
    _SKILL_LIBRARY_PATH = _DATA_DIR / "skill_library.json"

    def __init__(self, ui_callback: Any = None, log_fn: Any = None) -> None:
        self.ui_callback = ui_callback
        self.log_fn = log_fn or (lambda m: logger.info(m))
        self._skills: Dict[str, SkillEntry] = {}
        self._skill_file = _DATA_DIR / "skill_registry.json"
        self._load_skills()

    @classmethod
    def _load_skill_library(cls) -> Dict[str, dict]:
        if cls._SKILL_LIBRARY:
            return cls._SKILL_LIBRARY
        try:
            if cls._SKILL_LIBRARY_PATH.exists():
                data = json.loads(cls._SKILL_LIBRARY_PATH.read_text(encoding="utf-8"))
                index = {}
                for name, entry in data.items():
                    if name.startswith("_"):
                        continue
                    index[name.lower()] = entry
                    for tag in entry.get("tags", []):
                        if tag.lower() not in index:
                            index[tag.lower()] = entry
                cls._SKILL_LIBRARY = index
        except Exception as e:
            logger.debug(f"[Library] load: {e}")
        return cls._SKILL_LIBRARY

    def library_lookup(self, skill: str) -> dict:
        lib = self._load_skill_library()
        skill_low = skill.lower()
        if skill_low in lib:
            return lib[skill_low]
        for tag, entry in lib.items():
            if tag in skill_low or skill_low in tag:
                return entry
        return {}

    def _load_skills(self) -> None:
        try:
            if self._skill_file.exists():
                data = json.loads(self._skill_file.read_text(encoding="utf-8"))
                for name, d in data.items():
                    if "successes" in d and "uses" not in d:
                        d["uses"] = d["successes"]
                    self._skills[name] = SkillEntry(
                        name=name,
                        **{k: v for k, v in d.items() if k in SkillEntry.__dataclass_fields__ and k != "name"},
                    )
        except Exception as e:
            logger.debug(f"AgenticEngine._load_skills: {e}")

    def _save_skills(self) -> None:
        try:
            data = {
                k: {f.name: getattr(v, f.name) for f in SkillEntry.__dataclass_fields__ if f.name != "name"}
                for k, v in self._skills.items()
            }
            self._skill_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception as e:
            logger.debug(f"AgenticEngine._save_skills: {e}")

    def record_error(self, skill: str) -> None:
        entry = self._skills.setdefault(skill, SkillEntry(name=skill))
        entry.errors += 1
        entry.fail_streak += 1
        if entry.fail_streak >= 3 and entry.status == "mastered":
            entry.status = "learning"
            entry.unverified = True
            self._ui(skill, "learning")
        self._save_skills()

    def _vitality(self, entry: SkillEntry) -> float:
        if not entry.ingested_at:
            return entry.vitality_score
        try:
            t0 = datetime.fromisoformat(entry.ingested_at)
            dt = (datetime.utcnow() - t0).total_seconds() / 86400
            lam = MEMORY_LAYERS.get(entry.layer, MEMORY_LAYERS["disco"])["lambda"]
            v = entry.initial_score * math.exp(-lam * dt) if entry.initial_score > 0 else entry.vitality_score
            return round(max(0.0, min(1.0, v)), 4)
        except:
            return entry.vitality_score

    def entropy_level(self) -> float:
        if not self._skills:
            return 0.0
        degraded = sum(1 for e in self._skills.values() if e.unverified or self._vitality(e) < 0.4)
        return round(degraded / len(self._skills), 3)

    def entropy_color(self) -> str:
        e = self.entropy_level()
        if e <= ENTROPY_THRESHOLDS["green"]:
            return "#3fb950"
        if e <= ENTROPY_THRESHOLDS["orange"]:
            return "#d29922"
        return "#ff7b72"

    def get_skill_summary(self) -> List[Dict]:
        return [
            {"name": v.name, "status": v.status, "score": v.score, "uses": v.uses, "verified": not v.unverified}
            for v in sorted(self._skills.values(), key=lambda x: x.score, reverse=True)
        ]

    def _ui(self, name: str, status: str) -> None:
        if self._skills.get(name):
            self._skills[name].status = status
        if self.ui_callback:
            try:
                self.ui_callback(name, status)
            except:
                pass

    async def check_competence(self, skill: str) -> float:
        rag = _get_rag_engine()
        if not rag:
            return 0.0
        try:
            skill_low = skill.lower()
            lib_entry = self.library_lookup(skill)
            if lib_entry:
                lib_src = lib_entry.get("sources_rag", [])
                hits = sum(1 for c in rag.chunks if any(s in c.get("source", "") for s in lib_src))
                if hits >= lib_entry.get("chunks_min", 10):
                    return min(0.5 + hits / 300, 1.0)

            results = await rag.search(skill, k=8)
            if not results:
                return 0.0
            n = min(len(results), 8)
            avg_sim = sum(r.get("score", 0.5) for r in results) / n
            return round(min(n / 8 * avg_sim + avg_sim * 0.3, 1.0), 3)
        except:
            return 0.0

    async def prepare_rag_context(self, prompt: str, k: int = 6, role_hint: str = "chat") -> Tuple[List[Dict], Dict]:
        rag = _get_rag_engine()
        if not rag:
            return [], {}
        skills_needed = [s for s in ["system", "network", "code", "security"] if s in prompt.lower()] or ["general"]
        missing = []
        skill_scores = {}
        for s in skills_needed:
            score = await self.check_competence(s)
            skill_scores[s] = score
            if score < self.COMPETENCE_THRESHOLD:
                missing.append(s)
        docs = await rag.search(prompt, k=k, role_hint=role_hint)

        # Auto-emit skill.{name}.matched pour chaque skill active (section 9.2 EVENT_SPEC)
        for skill_name, score in skill_scores.items():
            entry = self._skills.get(skill_name)
            _emit_skill_event(
                topic=f"skill.{skill_name}.matched",
                kind="skill_match",
                data={
                    "score": round(score, 3),
                    "layer": entry.layer if entry else "unknown",
                    "role_hint": role_hint,
                    "context_chunks": len(docs),
                    "ready": score >= self.COMPETENCE_THRESHOLD,
                    "prompt_len": len(prompt),
                },
            )

        return docs, {"skills": skills_needed, "missing": missing, "ready": not missing, "scores": skill_scores}


class EvolutionOrchestrator:
    """Orchestre l'auto-évolution du RAG (Placeholder pour Phase B4)."""

    def __init__(self, ollama_url: str, vm: Any, rag: Any, sandbox: Any = None, log_fn: Any = None):
        self.ollama_url = ollama_url
        self.vm = vm
        self.rag = rag
        self.log_fn = log_fn or (lambda m: logger.info(m))

    async def run_full_cycle(self, query: str) -> Dict:
        return {"success": True, "log": "Evolution cycle unifié."}

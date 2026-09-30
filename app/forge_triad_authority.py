"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_triad_authority
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
app/forge_triad_authority.py
LAFORGE_MULTI_AGENT_SYNTAX_V1
Triad_Authority : Auditor->Orchestrator->Worker->Verify
"""

import asyncio, json, sys, time, sqlite3, ast as _ast, os
from dataclasses import dataclass
from pathlib import Path

from nokido_agent.app.forge_utils import _safe_llm_text

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
REPORTS_DIR = ROOT / "RAG" / "triad_reports"

AGENTS = {
    "auditor": "laforge",
    "orchestrator": "gemini",
    "worker": "groq_70b",  # fallback: deepseek_direct -> nokido
}

# Chaine de fallback par role
FALLBACK_CHAIN = {
    "auditor": ["laforge", "llamacpp"],
    "orchestrator": ["gemini", "laforge", "llamacpp"],
    "worker": ["groq_70b", "deepseek_direct", "mistral_direct", "laforge", "llamacpp"],
}


# 2026-09-12 : `@dataclass` etait ici DEUX fois. Meme bombe dormante que sur
# `ParsedIntent` (qui la portait six fois) : l'empilement ne se voit pas et ne
# casse rien tant qu'aucun champ n'a de `default_factory` en derniere position —
# un tel champ est retire des attributs de classe au 1er passage, parait sans
# defaut au 2e, et le module entier tombe a l'IMPORT. Balayage AST du depot le
# meme jour : 2438 fichiers lus, 0 illisible, ces DEUX sites en tout.
@dataclass
class TriadStep:
    """
    Represents a step in a triad process with details about the step, agent, outcome, and timing.
    """

    def __init__(self, step: str, agent: str) -> None:
        """Init.

        Args:
            step: Description.
            agent: Description.
        """
        self.step = step
        self.agent = agent
        self.ok = False
        self.output = ""
        self.elapsed_ms = 0

    def to_dict(self) -> dict:
        """
        Converts the TriadStep object to a dictionary representation.

        Returns:
            dict: A dictionary containing the step, agent, outcome, and timing details.
        """
        return {
            "step": self.step,
            "agent": self.agent,
            "ok": self.ok,
            "elapsed_ms": self.elapsed_ms,
            "output": self.output[:300],
        }


CLOUD_KEYS = {
    "gemini": "GEMINI_API_KEY",
    "groq_70b": "GROQ_API_KEY",
    "groq_direct": "GROQ_API_KEY",
    "deepseek_direct": "DEEPSEEK_API_KEY",
    "mistral_direct": "MISTRAL_API_KEY",
    "xai_grok": "XAI_API_KEY",
}


def _check_available(agent_id: str) -> bool:
    """Check available.

    Args:
        agent_id: Description.
    """
    if agent_id not in CLOUD_KEYS:
        return True  # local toujours dispo
    key = CLOUD_KEYS[agent_id]
    if os.environ.get(key, ""):
        return True
    try:
        import win32cred

        cred = win32cred.CredRead(f"{key}@LaForge", win32cred.CRED_TYPE_GENERIC)
        blob = cred.get("CredentialBlob", b"")
        val = blob.decode("utf-16-le", "replace").rstrip("\x00") if blob else ""
        if val:
            os.environ[key] = val
            return True
    except Exception:
        pass
    return False


def _get_agent_id(role: str) -> str:
    """Retourne le 1er agent disponible dans FALLBACK_CHAIN."""
    chain = FALLBACK_CHAIN.get(role, ["laforge"])
    for candidate in chain:
        if _check_available(candidate):
            return candidate
    return "laforge"


def _run_agent(role: str, prompt: str, system: str = "", max_retries: int = 2) -> tuple:
    """
    Execute un agent avec retry automatique si reponse vide.
    Fallback sur le prochain agent de la chaine si echec persistant.
    """
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    full = (f"[SYSTEM] {system}\n\n{prompt}") if system else prompt
    chain = FALLBACK_CHAIN.get(role, ["laforge"])

    for agent_id in chain:
        if not _check_available(agent_id):
            continue
        for attempt in range(max_retries):
            try:
                from nokido_agent.app.forge_swarm_team import _default_team, LeadOrchestrator

                team = _default_team()
                team.activate(agent_id)
                orc = LeadOrchestrator()
                loop = asyncio.new_event_loop()
                try:
                    res = loop.run_until_complete(orc.run(full, team))
                    turns = res.get("results", [])
                    text = _safe_llm_text(res)
                    text = text.strip()
                finally:
                    loop.close()
                # Guard reponse vide
                if not text or text in ("None", "null", "{}", "[]"):
                    if attempt < max_retries - 1:
                        time.sleep(0.3)
                        continue  # retry
                    break  # essayer agent suivant
                return True, text, agent_id
            except Exception as e:
                if attempt == max_retries - 1:
                    break  # agent suivant
                time.sleep(0.2)

    # Tous les agents ont echoue -> reponse de fallback
    fallback_msg = f"[FALLBACK] Aucun agent disponible pour role={role}"
    return False, fallback_msg, "none"


def step_audit(target: str, on_update=None) -> TriadStep:
    """Step audit.

    Args:
        target: Description.
        on_update: Description.
    """
    t0 = time.time()
    if on_update:
        on_update("audit", "running", "")
    fp = ROOT / target
    if not fp.exists():
        fp = ROOT / "app" / target
    src = fp.read_text(encoding="utf-8", errors="ignore")[:3000] if fp.exists() else f"introuvable: {target}"
    prompt = (
        "Audit securite et architecture de ce module Python:\n"
        f"Fichier: {target}\n```python\n{src}\n```\n\n"
        "Format: 1.SECURITE 2.ARCHITECTURE 3.PRIORITES(3 items) 4.SCORE/100"
    )
    ok, out, aid = _run_agent("auditor", prompt, "Auditeur securite Nokido. Francais. Concis.")
    elapsed = int((time.time() - t0) * 1000)
    if ok:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        (REPORTS_DIR / f"audit_{ts}_{fp.stem}.md").write_text(f"# Audit {target}\n\n{out}", encoding="utf-8")
    if on_update:
        on_update("audit", "done" if ok else "fail", out[:150])
    return TriadStep("Audit", aid, ok, out, elapsed)


def step_plan(audit_out: str, target: str, on_update=None) -> TriadStep:
    """Step plan.

    Args:
        audit_out: Description.
        target: Description.
        on_update: Description.
    """
    t0 = time.time()
    if on_update:
        on_update("plan", "running", "")
    prompt = (
        f"Rapport audit pour {target}:\n{audit_out[:1500]}\n\n"
        "Genere une Task_List JSON (3-5 taches). JSON UNIQUEMENT:\n"
        '[{"id":"T1","priority":"high","type":"refactor|test|security",'
        '"description":"...","file":"...","line_hint":0}]'
    )
    ok, out, aid = _run_agent("orchestrator", prompt, "Orchestrateur technique. JSON valide uniquement.")
    elapsed = int((time.time() - t0) * 1000)
    task_list = []
    if ok:
        start = out.find("[")
        end = out.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                task_list = json.loads(out[start:end])
            except Exception:
                task_list = [
                    {
                        "id": "T1",
                        "priority": "high",
                        "type": "refactor",
                        "description": out[:150],
                        "file": target,
                        "line_hint": 0,
                    }
                ]
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        (REPORTS_DIR / f"tasks_{ts}.json").write_text(
            json.dumps(task_list, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    if on_update:
        on_update("plan", "done" if ok else "fail", json.dumps(task_list)[:150])
    step = TriadStep("Plan", aid, ok, json.dumps(task_list, ensure_ascii=False), elapsed)
    step.task_list = task_list
    return step


def step_execute(task_list: list, target: str, on_update=None) -> TriadStep:
    """Step execute.

    Args:
        task_list: Description.
        target: Description.
        on_update: Description.
    """
    t0 = time.time()
    if on_update:
        on_update("execute", "running", "")
    fp = ROOT / target
    if not fp.exists():
        fp = ROOT / "app" / target
    src = fp.read_text(encoding="utf-8", errors="ignore")[:2500] if fp.exists() else ""
    tasks_str = json.dumps(task_list[:3], indent=2, ensure_ascii=False)
    prompt = (
        f"Taches a executer pour {target}:\n{tasks_str}\n\n"
        f"Code actuel:\n```python\n{src}\n```\n\n"
        "Pour type=test: genere fonctions pytest. Pour type=refactor: patch minimal. Code Python uniquement."
    )
    ok, out, aid = _run_agent("worker", prompt, "Developpeur Python expert. Code propre.")
    elapsed = int((time.time() - t0) * 1000)
    if ok and len(out) > 50:
        code = out.split("```python")[1].split("```")[0] if "```python" in out else out
        try:
            _ast.parse(code)
            ts = time.strftime("%Y%m%d_%H%M%S")
            patch = ROOT / "sandbox" / f"patch_{ts}_{fp.stem}.py"
            patch.write_text(code, encoding="utf-8")
            out = f"[PATCH] {patch.name}\n{out[:300]}"
        except SyntaxError as e:
            out = f"[SYNTAX ERR] {e}\n{out[:300]}"
    if on_update:
        on_update("execute", "done" if ok else "fail", out[:150])
    return TriadStep("Execute", aid, ok, out, elapsed)


def step_verify(exec_out: str, task_list: list, on_update=None) -> TriadStep:
    """Step verify.

    Args:
        exec_out: Description.
        task_list: Description.
        on_update: Description.
    """
    t0 = time.time()
    if on_update:
        on_update("verify", "running", "")
    tasks_str = json.dumps(task_list[:3], ensure_ascii=False)
    prompt = (
        f"Final_Sign_Off. Taches demandees:\n{tasks_str}\n\n"
        f"Travail soumis:\n{exec_out[:1200]}\n\n"
        'JSON: {"conformite":0-10,"qualite":0-10,"verdict":"APPROVED|REJECTED|PARTIAL","raison":""}'
    )
    ok, out, aid = _run_agent("auditor", prompt, "Auditeur strict. JSON uniquement.")
    elapsed = int((time.time() - t0) * 1000)
    verdict = "UNKNOWN"
    try:
        start = out.find("{")
        end = out.rfind("}") + 1
        if start >= 0 and end > start:
            d = json.loads(out[start:end])
            verdict = d.get("verdict", "UNKNOWN")
    except Exception:
        pass
    if on_update:
        on_update("verify", "done" if ok else "fail", f"{verdict}: {out[:100]}")
    step = TriadStep("Verify", aid, ok, out, elapsed)
    step.verdict = verdict
    return step


class TriadOrchestrator:
    def __init__(self, on_update=None) -> None:
        """Init.

        Args:
            on_update: Description.
        """
        self._on_update = on_update

    def run(self, target: str) -> dict:
        """Run.

        Args:
            target: Description.
        """
        t0 = time.time()
        results = {}
        s1 = step_audit(target, self._on_update)
        results["audit"] = s1.to_dict()
        if not s1.ok:
            return self._finish(results, target, t0, "audit_failed")
        s2 = step_plan(s1.output, target, self._on_update)
        results["plan"] = s2.to_dict()
        tl = getattr(s2, "task_list", [])
        if not s2.ok or not tl:
            return self._finish(results, target, t0, "plan_failed")
        s3 = step_execute(tl, target, self._on_update)
        results["execute"] = s3.to_dict()
        if not s3.ok:
            return self._finish(results, target, t0, "execute_failed")
        s4 = step_verify(s3.output, tl, self._on_update)
        results["verify"] = s4.to_dict()
        return self._finish(results, target, t0, getattr(s4, "verdict", "UNKNOWN"))

    def _finish(self, results, target, t0, status) -> dict:
        """Finish.

        Args:
            results: Description.
            target: Description.
            t0: Description.
            status: Description.
        """
        elapsed = int((time.time() - t0) * 1000)
        try:
            db = ROOT / "RAG" / "embeddings.db"
            conn = sqlite3.connect(str(db))
            conn.execute("PRAGMA journal_mode=WAL")
            last = conn.execute("SELECT MAX(sequence_id) FROM event_log").fetchone()[0] or 0
            conn.execute(
                "INSERT INTO event_log (timecode,sequence_id,session_id,agent_id,event_type,target,payload,status) VALUES (?,?,?,?,?,?,?,?)",
                (
                    time.strftime("%Y-%m-%dT%H:%M:%S"),
                    int(last) + 1,
                    "triad",
                    "CLAUDE",
                    "triad_run",
                    target,
                    json.dumps({"elapsed_ms": elapsed}, ensure_ascii=False),
                    "ok" if status in ("APPROVED", "PARTIAL") else "err",
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
        return {
            "target": target,
            "status": status,
            "elapsed_ms": elapsed,
            "steps": results,
            "passed": status in ("APPROVED", "PARTIAL"),
        }


def get_triad(on_update=None) -> object:
    """Get triad.

    Args:
        on_update: Description.
    """
    return TriadOrchestrator(on_update)


def run_triad(target: str) -> dict:
    """Run triad.

    Args:
        target: Description.
    """
    return TriadOrchestrator().run(target)

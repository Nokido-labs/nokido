#!/usr/bin/env python3
"""forge_cowork.py — collegue IA persistant ("Cowork" souverain internalise).

Design : docs/cowork_internalization_design.md (panel multi-LLM 3 tours, 2026-06-09).
Compose les organes existants (task_queue/mailbox/blackboard/GOAP/swarm/acp) ; le neuf =
l'entite CoworkProject + la boucle coworker.

P1 (ce fichier) : CoworkProject + boucle doc REVERSIBLE end-to-end :
    backlog -> draft (LLM local) -> checkpoint generalise (fichier + sha256) -> digest review inbox.

PARADE R3 (anti-contention mono-writer, UNANIME panel adversarial) : ce module N'ECRIT PAS sur
le mono-writer du hub. DB DEDIEE (RAG/cowork.db), artefacts en FICHIERS (sandbox/cowork/<id>/),
seul un RESUME LEGER part en mailbox (notify). Zero pression sur le verrou hub/blackboard.

Modes : --selftest (stub LLM, zero hub/cloud) | --once <project_id> | (nu) = daemon supervise.
"""
from __future__ import annotations

__FORGE_COLOR__ = "cognition/agent collegue persistant, panel multi-LLM"  # declare le 2026-09-06 (audit : REGULE sans organe)

import hashlib
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = str(ROOT / "RAG" / "cowork.db")  # DEDIE : jamais le mono-writer hub (parade R3)
ART_DIR = ROOT / "sandbox" / "cowork"
HEARTBEAT = ROOT / "sandbox" / "cowork_daemon.heartbeat"
INTERVAL = 30
_VALID_STATUS = ("idle", "running", "awaiting_approval", "completed", "failed")


def init_db() -> None:
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        """CREATE TABLE IF NOT EXISTS cowork_projects (
            id TEXT PRIMARY KEY,
            goal TEXT NOT NULL,
            context_refs TEXT NOT NULL DEFAULT '{}',
            backlog TEXT NOT NULL DEFAULT '[]',
            review_thread TEXT,
            status TEXT NOT NULL DEFAULT 'idle',
            created_at REAL DEFAULT (unixepoch()),
            updated_at REAL )"""
    )
    con.commit()
    con.close()


# ── Entite CoworkProject ────────────────────────────────────────────────────
def create_project(goal: str, backlog: list[dict], context_refs: dict | None = None) -> str:
    """backlog = [{id?, description, type('doc'|'code'|'research'), reversible:bool}, ...]."""
    init_db()
    pid = "proj_" + uuid.uuid4().hex[:10]
    for i, t in enumerate(backlog):
        t.setdefault("id", f"{pid}_t{i}")
        t.setdefault("type", "doc")
        t.setdefault("reversible", True)
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        "INSERT INTO cowork_projects (id, goal, context_refs, backlog, status, updated_at) "
        "VALUES (?,?,?,?,?,?)",
        (pid, goal, json.dumps(context_refs or {}), json.dumps(backlog), "idle", time.time()),
    )
    con.commit()
    con.close()
    _mem = _cowork_memory(pid)
    if _mem is not None:
        try:
            _mem.set_persona(
                "Cowork — collegue IA persistant Nokido (souverain, local-first)",
                user_persona="user",
                facts=f"Projet: {goal}",
            )
        except Exception:
            pass
    return pid


def get_project(pid: str) -> dict | None:
    init_db()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    r = con.execute("SELECT * FROM cowork_projects WHERE id=?", (pid,)).fetchone()
    con.close()
    if not r:
        return None
    d = dict(r)
    d["context_refs"] = json.loads(d["context_refs"] or "{}")
    d["backlog"] = json.loads(d["backlog"] or "[]")
    return d


def _set_status(pid: str, status: str) -> None:
    assert status in _VALID_STATUS, status
    con = sqlite3.connect(DB)
    con.execute("UPDATE cowork_projects SET status=?, updated_at=? WHERE id=?", (status, time.time(), pid))
    con.commit()
    con.close()


def list_active() -> list[str]:
    init_db()
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT id FROM cowork_projects WHERE status='idle' ORDER BY created_at").fetchall()
    con.close()
    return [r[0] for r in rows]


# ── Checkpoint generalise (type-dispatche ; artefact = FICHIER, pas le mono-writer) ──
def checkpoint(cowork_id: str, task: dict, content: str) -> dict:
    """Ecrit l'artefact (fichier + sha256). type=code -> validation AST (P3) ; doc/research -> .md.
    ROLLBACK (P3) : sauve .prev avant ecrasement ; code AST KO + prev existe -> restore .prev
    (ne casse jamais le bon artefact precedent). Retourne un RESUME LEGER (seul truc qui sort)."""
    ttype = task.get("type", "doc")
    ext = ".py" if ttype == "code" else ".md"
    d = ART_DIR / cowork_id
    d.mkdir(parents=True, exist_ok=True)
    path = d / (task["id"] + ext)
    prev_path = d / (task["id"] + ext + ".prev")
    prev_sha = None
    if path.exists():
        prev = path.read_text(encoding="utf-8")
        prev_sha = hashlib.sha256(prev.encode("utf-8")).hexdigest()
        prev_path.write_text(prev, encoding="utf-8")
    path.write_text(content, encoding="utf-8")
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    summary = {"cowork_id": cowork_id, "task_id": task["id"], "type": ttype, "path": str(path),
               "sha256": sha, "prev_sha256": prev_sha, "bytes": len(content.encode("utf-8")),
               "reversible": bool(task.get("reversible", True)), "ts": time.time()}
    if ttype == "code":
        try:
            import ast as _ast

            _ast.parse(content)
            summary["ast_ok"] = True
        except SyntaxError as e:
            summary["ast_ok"] = False
            summary["ast_error"] = f"{e.msg} L{e.lineno}"
            if prev_sha:
                path.write_text(prev_path.read_text(encoding="utf-8"), encoding="utf-8")
                summary["rolled_back"] = True
    return summary


def _digest(cowork_id: str, summary: dict) -> None:
    """Resume LEGER vers la review inbox. Durable = review.jsonl (fichier) ;
    notify = mailbox best-effort. AUCUNE ecriture lourde sur le mono-writer hub."""
    rj = ART_DIR / cowork_id / "review.jsonl"
    rj.parent.mkdir(parents=True, exist_ok=True)
    with rj.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    try:  # notify best-effort (ne bloque jamais la boucle)
        from nokido_agent.app.forge_mailbox import push as _mbpush

        _mbpush(agent="user", sender="cowork_daemon",
                payload={"kind": "cowork_review", **summary}, ring=2)
    except Exception:
        pass


def _draft_local(task: dict, goal: str, mem_context: str = "") -> str:
    """Draft via LLM LOCAL (ollama :11434, souverain, zero cloud). Fallback = stub.
    mem_context = memoire Letta du projet (persona + rappels) injectee en tete."""
    _mc = f"{mem_context}\n\n" if mem_context else ""
    prompt = f"{_mc}Goal: {goal}\nTask: {task.get('description', task.get('id'))}\nProduce the deliverable content only."
    try:
        import urllib.request

        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            data=json.dumps({"model": "qwen2.5-coder:7b", "prompt": prompt, "stream": False}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read()).get("response", "").strip() or f"# {goal}\n\n(empty)"
    except Exception as e:
        return f"# {goal}\n\n(local LLM unavailable: {type(e).__name__}) — task {task.get('id')}"


# ── Boucle coworker ───────────────────────────────────────────────────────────
def _cowork_memory(pid: str):
    """Memoire Letta persistante du projet cowork (agent_id='cowork', session=pid).
    async_writes=True -> archivage en thread (parade R3 : jamais bloquer/contendre
    le mono-writer hub depuis la boucle cowork). Kill-switch LAFORGE_COWORK_MEMORY=0."""
    import os as _os

    if _os.environ.get("LAFORGE_COWORK_MEMORY", "1") == "0":
        return None
    try:
        from nokido_agent.app.forge_memory_archival import get_agent_memory

        return get_agent_memory("cowork", session_id=pid, async_writes=True)
    except Exception:
        return None


def run_task(proj: dict, task: dict, *, llm=None) -> dict:
    """1 tache : draft -> checkpoint -> digest. Code AST invalide -> raise (rollback deja fait, pas de digest)."""
    _mem = _cowork_memory(proj["id"])
    _ctx = ""
    if _mem is not None:
        try:
            _ctx = _mem.compose_context(
                recall_query=str(task.get("description") or task.get("id") or ""), max_chars=2000
            )
        except Exception:
            _ctx = ""
    drafter = llm or (lambda t: _draft_local(t, proj["goal"], mem_context=_ctx))
    content = drafter(task)
    cp = checkpoint(proj["id"], task, content)
    if cp.get("ast_ok") is False:  # P3 : ne "complete" jamais du code casse
        raise ValueError(f"code AST invalide: {cp.get('ast_error')} (rolled_back={cp.get('rolled_back', False)})")
    _digest(proj["id"], cp)
    if _mem is not None:
        try:
            _mem.remember("user", f"Task: {task.get('description', task.get('id'))}")
            _mem.remember("assistant", content[:4000])
        except Exception:
            pass
    return cp


def _ground(claim: str):
    """Vet via forge_grounder (best-effort). None si grounder indispo -> propose_next traite comme UNCERTAIN."""
    try:
        from nokido_agent.app.forge_grounder import ground

        return ground(claim)
    except Exception:
        return None


def propose_next(pid: str, *, max_tasks: int = 3, llm=None, ground_fn=None) -> dict:
    """INITIATIVE BORNEE (P3) : propose <=max_tasks taches, chacune VETTEE par le grounder
    (rejet si verdict REFUTED = hors-scope/non-sense). Reversible -> auto-backlog ; irreversible ->
    backlog + gate au run (P2). Bornes : max_tasks + jugement grounder. Sovereign (LLM local + ground)."""
    proj = get_project(pid)
    if not proj:
        return {"error": "no such project", "id": pid}
    gen = llm or (lambda prompt: _draft_local({"description": prompt}, proj["goal"]))
    prompt = (f"Goal: {proj['goal']}\nContext: {json.dumps(proj.get('context_refs', {}))[:400]}\n"
              f"Existing backlog: {len(proj['backlog'])} tasks.\n"
              f"Propose up to {max_tasks} concrete NEXT tasks. JSON list ONLY: "
              '[{"description":"...","type":"doc|code|research","reversible":true|false}].')
    raw = gen(prompt)
    try:
        cand = json.loads(raw[raw.index("["):raw.rindex("]") + 1])
    except Exception:
        cand = []
    vet = ground_fn or _ground
    accepted, rejected = [], []
    for c in cand[:max_tasks]:
        desc = str(c.get("description", ""))[:200]
        if not desc:
            continue
        v = vet(f"La tache '{desc}' est un prochain pas SENSE et DANS LE SCOPE pour l'objectif '{proj['goal']}'.")
        verdict = (v or {}).get("verdict", "UNCERTAIN")
        if verdict == "REFUTED":
            rejected.append({"description": desc, "verdict": verdict})
            continue
        accepted.append({"id": f"{pid}_p{len(proj['backlog']) + len(accepted)}", "description": desc,
                         "type": c.get("type", "doc"), "reversible": bool(c.get("reversible", True)),
                         "proposed": True, "verdict": verdict})
    proj["backlog"].extend(accepted)
    _persist_backlog(pid, proj["backlog"])
    if accepted and get_project(pid)["status"] == "completed":
        _set_status(pid, "idle")  # nouveau travail -> reactive le projet
    return {"id": pid, "proposed": len(cand), "accepted": len(accepted), "rejected": len(rejected),
            "tasks": [t["description"] for t in accepted]}


def run_once(pid: str, *, llm=None) -> dict:
    """Execute le backlog d'UN projet. Reversible OU approuve -> run ; irreversible non-approuve
    -> PARK (awaiting_approval + notify), s'arrete sur CE projet (le daemon continue les AUTRES).
    Tache 'done' persistee -> idempotent entre ticks. Reprise = approve() (event) -> idle -> tick."""
    proj = get_project(pid)
    if not proj:
        return {"error": "no such project", "id": pid}
    _set_status(pid, "running")
    done = []
    parked = None
    try:
        for t in proj["backlog"]:
            if t.get("done") or t.get("rejected"):
                continue
            if not t.get("reversible", True) and not t.get("approved"):
                parked = t                       # P2 : gate irreversible
                plan_id = _notify_approval(proj, t)   # mailbox + review + file hub
                if plan_id:
                    t["pending_plan_id"] = plan_id    # P4 : pont reprise via promotion_queue
                _set_status(pid, "awaiting_approval")
                break                            # PARK : ne bloque pas les AUTRES projets
            done.append(run_task(proj, t, llm=llm))
            t["done"] = True
        _persist_backlog(pid, proj["backlog"])
        if parked:
            return {"id": pid, "status": "awaiting_approval", "parked": parked["id"], "checkpoints": done}
        _set_status(pid, "completed")
        return {"id": pid, "goal": proj["goal"], "status": "completed", "checkpoints": done}
    except Exception as e:
        _set_status(pid, "failed")
        return {"id": pid, "error": str(e), "status": "failed", "checkpoints": done}


def _persist_backlog(pid: str, backlog: list[dict]) -> None:
    con = sqlite3.connect(DB)
    con.execute("UPDATE cowork_projects SET backlog=?, updated_at=? WHERE id=?",
                (json.dumps(backlog), time.time(), pid))
    con.commit()
    con.close()


def _notify_approval(proj: dict, task: dict) -> str | None:
    """Remonte une demande d'approbation (tache irreversible). Durable=review.jsonl ; notify=mailbox ;
    file hub=_queue_for_approval (rare+leger -> OK vs mono-writer). Retourne le plan_id (pont reprise P4)."""
    payload = {"kind": "cowork_approval_request", "project": proj["id"], "goal": proj["goal"],
               "task": task["id"], "description": task.get("description"), "reason": "irreversible"}
    rj = ART_DIR / proj["id"] / "review.jsonl"
    rj.parent.mkdir(parents=True, exist_ok=True)
    with rj.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    try:
        from nokido_agent.app.forge_mailbox import push as _mbpush

        _mbpush(agent="user", sender="cowork_daemon", payload=payload, ring=2)
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        # Une demande d'APPROBATION perdue n'atteint jamais l'humain, et rien ne
        # distingue « pas de demande » de « demande evaporee ». Le travail reste alors
        # en attente d'un accord que personne ne sait devoir donner.
        _lg.getLogger(__name__).error(
            "[cowork] demande d'approbation NON deposee dans la boite de user "
            "(%s: %s) | consequence: personne ne sera sollicite, et l'attente passera "
            "pour un silence de l'owner", type(e).__name__, str(e)[:100])
    try:
        import asyncio
        import re as _re

        from nokido_agent.app.forge_meta_tools import _queue_for_approval

        r = asyncio.run(_queue_for_approval(name="cowork_task",
                                            args={"project": proj["id"], "task": task["id"]},
                                            entity_id="cowork_daemon", reason=task.get("description", "irreversible")))
        m = _re.search(r"id=([0-9a-fA-F]+)", str(r))
        return m.group(1) if m else None
    except Exception:
        return None


TRUSTED_RING = 2  # forge_integrity.IntegrityRing.TRUSTED — approuver/rejeter une tache irreversible = privilegie


def approve(pid: str, task_id: str, *, ring: int = TRUSTED_RING) -> dict:
    """Resume (event d'approbation) : marque la tache approuvee + repasse 'idle' -> le daemon reprend.
    TRUST-RING : approuver une tache IRREVERSIBLE = privilegie -> ring <= TRUSTED requis (ACP/untrusted refuse)."""
    if int(ring) > TRUSTED_RING:
        return {"error": "ring insuffisant pour approve (irreversible) — valider via flux trusted",
                "ring": int(ring), "id": pid}
    proj = get_project(pid)
    if not proj:
        return {"error": "no such project", "id": pid}
    hit = False
    for t in proj["backlog"]:
        if t["id"] == task_id:
            t["approved"] = True
            hit = True
    _persist_backlog(pid, proj["backlog"])
    _set_status(pid, "idle")
    return {"id": pid, "approved": task_id, "found": hit, "status": "idle"}


def reject(pid: str, task_id: str, *, ring: int = TRUSTED_RING) -> dict:
    """Rejette la tache (skip) + repasse 'idle'. TRUST-RING : ring <= TRUSTED requis."""
    if int(ring) > TRUSTED_RING:
        return {"error": "ring insuffisant pour reject — valider via flux trusted", "ring": int(ring), "id": pid}
    proj = get_project(pid)
    if not proj:
        return {"error": "no such project", "id": pid}
    for t in proj["backlog"]:
        if t["id"] == task_id:
            t["rejected"] = True
    _persist_backlog(pid, proj["backlog"])
    _set_status(pid, "idle")
    return {"id": pid, "rejected": task_id, "status": "idle"}


def _promotion_status(plan_id: str) -> str | None:
    """Lit le statut d'une demande dans la promotion_queue du hub (read-only, best-effort)."""
    try:
        edb = str(ROOT / "RAG" / "embeddings.db")
        con = sqlite3.connect(f"file:{edb}?mode=ro", uri=True)
        row = con.execute("SELECT status FROM promotion_queue WHERE chunk_id=?", (plan_id,)).fetchone()
        con.close()
        return row[0] if row else None
    except Exception:
        return None


def _poll_approvals(status_fn=None) -> int:
    """P4 : pont approbation hub -> reprise cowork. Scanne les projets awaiting_approval, lit le
    statut de leur demande (promotion_queue) ; approved -> approve() (reprise), rejected -> reject().
    Rend la reprise EVENT-driven sans approve() CLI : l'humain valide via le flux hub natif."""
    sf = status_fn or _promotion_status
    n = 0
    init_db()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT id, backlog FROM cowork_projects WHERE status='awaiting_approval'").fetchall()
    con.close()
    for r in rows:
        try:
            backlog = json.loads(r["backlog"] or "[]")
        except Exception:
            continue
        for t in backlog:
            plan_id = t.get("pending_plan_id")
            if not plan_id:
                continue
            st = sf(plan_id)
            if st == "approved":
                approve(r["id"], t["id"])
                n += 1
            elif st == "rejected":
                reject(r["id"], t["id"])
                n += 1
    return n


# ── Daemon supervise (single-instance guard + heartbeat, pattern NokidoTraceCollectorRich) ──
def _another_instance_alive() -> bool:
    try:
        import os as _os
        import psutil  # type: ignore

        me = _os.getpid()
        for p in psutil.process_iter(["pid", "cmdline"]):
            if p.info["pid"] == me:
                continue
            cl = " ".join(p.info.get("cmdline") or [])
            if "forge_cowork" in cl and "--selftest" not in cl and "--once" not in cl:
                return True
    except Exception:
        pass
    return False


def _beat(tick: int, active: int) -> None:
    try:
        import os as _os

        HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT.write_text(json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "pid": _os.getpid(),
            "tick": tick, "interval_s": INTERVAL, "active_projects": active}))
    except Exception:
        pass


def run_daemon(max_ticks: int | None = None) -> int:
    init_db()
    ticks = 0
    if max_ticks is None:
        # Guard GRACIEUX (idle-wait, comme NokidoTraceCollectorRich) : si une instance vit deja
        # (ex: orphan survivant a un restart superviseur), on reste VIVANT (heartbeat tick=-1) au lieu
        # d'exit -> evite la quick-fail quarantine ; relais auto quand l'orphan meurt (reboot).
        while _another_instance_alive():
            _beat(-1, 0)
            time.sleep(INTERVAL)
    while max_ticks is None or ticks < max_ticks:
        try:
            _poll_approvals()  # P4 : reprise auto sur approbation hub (promotion_queue)
        except Exception:
            pass
        active = list_active()
        for pid in active:
            try:
                run_once(pid)
            except Exception as e:
                print(f"[cowork] {pid} error: {e}", file=sys.stderr)
        ticks += 1
        if max_ticks is None:
            _beat(ticks, len(active))
        if max_ticks is None or ticks < max_ticks:
            time.sleep(INTERVAL)
    return 0


def _selftest() -> int:
    """Chaine end-to-end SANS hub/cloud (LLM stubbe) : create -> run_once -> assert artefact+checkpoint+digest."""
    init_db()
    pid = create_project("Draft README for the cowork PoC",
                         [{"description": "Draft a short README.md", "type": "doc", "reversible": True}])
    stub = lambda t: "# Cowork PoC\n\nGenerated by the cowork loop (selftest stub).\n"
    res = run_once(pid, llm=stub)
    assert res.get("status") == "completed", res
    cp = res["checkpoints"][0]
    assert Path(cp["path"]).exists() and cp["sha256"] and cp["bytes"] > 0, cp
    review = ART_DIR / pid / "review.jsonl"
    assert review.exists() and review.read_text(encoding="utf-8").strip(), "digest review.jsonl manquant"
    proj = get_project(pid)
    assert proj["status"] == "completed", proj
    print(f"COWORK-P1 OK | project={pid} status=completed | artifact={Path(cp['path']).name} "
          f"sha={cp['sha256'][:12]} bytes={cp['bytes']} | digest=review.jsonl | DB dediee (mono-writer hub intact)")
    # P2 : gate irreversible + park / resume
    pid2 = create_project("Deploy a config change",
                          [{"description": "reversible note", "type": "doc", "reversible": True},
                           {"description": "irreversible deploy", "type": "doc", "reversible": False}])
    r = run_once(pid2, llm=stub)
    assert r["status"] == "awaiting_approval" and r.get("parked"), r
    assert get_project(pid2)["status"] == "awaiting_approval", get_project(pid2)
    tid = [t["id"] for t in get_project(pid2)["backlog"] if not t["reversible"]][0]
    approve(pid2, tid)
    assert get_project(pid2)["status"] == "idle", get_project(pid2)
    r2 = run_once(pid2, llm=stub)
    assert r2["status"] == "completed", r2
    print(f"COWORK-P2 OK | task1 run -> task2 irreversible PARK (awaiting_approval) "
          f"-> approve -> resume -> completed (park-and-continue + event resume)")
    # P3 : initiative bornee (grounder-vettee) + checkpoint code AST + rollback
    gen_stub = ('[{"description":"write changelog","type":"doc","reversible":true},'
                '{"description":"BAD risky deploy","type":"code","reversible":false}]')
    ground_stub = lambda claim: {"verdict": "REFUTED" if "BAD" in claim else "GROUNDED"}
    pid3 = create_project("Maintain docs", [])
    pr = propose_next(pid3, llm=lambda p: gen_stub, ground_fn=ground_stub)
    assert pr["accepted"] == 1 and pr["rejected"] == 1, pr  # 'BAD' rejete par le grounder
    okcp = checkpoint(pid3, {"id": "c_ok", "type": "code"}, "x = 1\n")
    assert okcp.get("ast_ok") is True, okcp
    badcp = checkpoint(pid3, {"id": "c_bad", "type": "code"}, "def (:\n")
    assert badcp.get("ast_ok") is False, badcp
    print(f"COWORK-P3 OK | initiative bornee grounder-vettee (1 accepte / 1 REFUTED) "
          f"+ checkpoint code AST (valide ok / invalide ko) + rollback prev")
    # P4 : pont approbation hub (promotion_queue) -> reprise auto
    pid4 = create_project("P4 deploy", [{"description": "irrev step", "type": "doc", "reversible": False}])
    run_once(pid4, llm=stub)
    assert get_project(pid4)["status"] == "awaiting_approval", get_project(pid4)
    p4 = get_project(pid4)
    p4["backlog"][0]["pending_plan_id"] = "testplan"
    _persist_backlog(pid4, p4["backlog"])
    nres = _poll_approvals(status_fn=lambda pl: "approved" if pl == "testplan" else None)
    assert nres == 1 and get_project(pid4)["status"] == "idle", get_project(pid4)
    # TRUST-RING : approve depuis un ring non-trusted (ACP/untrusted=4) refuse
    assert "ring insuffisant" in approve("x", "t", ring=4).get("error", ""), "trust-ring gate KO"
    print(f"COWORK-P4 OK | poll auto-resume (event-driven) + TRUST-RING gate (approve ring>TRUSTED refuse)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    if "--propose" in sys.argv:
        i = sys.argv.index("--propose")
        print(json.dumps(propose_next(sys.argv[i + 1]), ensure_ascii=True))
        raise SystemExit(0)
    if "--approve" in sys.argv:
        i = sys.argv.index("--approve")
        print(json.dumps(approve(sys.argv[i + 1], sys.argv[i + 2]), ensure_ascii=False))
        raise SystemExit(0)
    if "--reject" in sys.argv:
        i = sys.argv.index("--reject")
        print(json.dumps(reject(sys.argv[i + 1], sys.argv[i + 2]), ensure_ascii=False))
        raise SystemExit(0)
    if "--once" in sys.argv:
        i = sys.argv.index("--once")
        pid = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
        print(json.dumps(run_once(pid), ensure_ascii=False, indent=2))
        raise SystemExit(0)
    raise SystemExit(run_daemon())

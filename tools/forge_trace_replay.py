"""
AMI — Experience Replay: parse mcp_audit.log historical entries → execution_traces.db.
"L'expérience nourrit l'intelligence."

State_t  = encode(prev_tool output context)
Action   = {tool, agent, args_preview}
State_t1 = encode(current tool output context)

Skips INSPECTOR / poll / noise. Groups consecutive OUT lines into transitions.

⚠️ L'IMPORT DE CE MODULE NE DOIT PRODUIRE AUCUN EFFET DE BORD FICHIER.
Mesure 2026-09-16 : `logging.basicConfig(handlers=[RotatingFileHandler(...)])`
s'executait AU NIVEAU MODULE, donc a l'import. Or `logs/trace_replay.log` est
lisible mais NON inscriptible par les comptes sandbox (verifie sous
LaForgeSbxOffline ET LaForgeSbxOnline) : le module etait donc inimportable, et
son propre test de chargement mesurait les ACL du compte au lieu du code.
Un import DEFINIT des capacites ; il ne reclame pas de privilege.
"""
import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def configurer_journal() -> str:
    """Installe le journal. A appeler depuis un point d'entree, JAMAIS a l'import.

    Rend le motif quand le fichier n'a pas pu etre ouvert, et le DIT sur la
    sortie standard : un journal qui echoue en silence est indistinguable d'un
    journal muet. La console reste branchee dans tous les cas -- perdre le
    fichier ne doit pas faire perdre la trace.
    """
    poignees = [logging.StreamHandler()]
    motif = ""
    try:
        poignees.insert(0, RotatingFileHandler(
            str(ROOT / "logs" / "trace_replay.log"),
            maxBytes=10485760, backupCount=5))
    except OSError as e:
        motif = "journal fichier indisponible (%s) — la console prend le relais" % type(e).__name__
        print("[trace_replay] %s" % motif)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [trace_replay] %(message)s",
        handlers=poignees,
    )
    return motif

from nokido_agent.app.forge_cost_module import total_cost
from nokido_agent.app.forge_execution_tracer import count_traces, init_db, record_trace
from nokido_agent.app.forge_state_encoder import encode_state

AUDIT_LOG = ROOT / "logs" / "mcp_audit.log"
GOAL_TEXT = "system stable, all tasks completed, hub healthy, no errors"

SKIP_TOOLS = {"poll", "heartbeat", "port", "cycle", "heal", "netcfg_ping", "inspector", "kill"}
SKIP_AGENTS = {"INSPECTOR", "OPENAI_PROXY"}
SKIP_STATUSES = set()  # include all statuses (OK + ERR = both teach something)

# Only tools that carry semantic meaning worth learning from
VALUABLE_TOOLS = {
    "run",
    "ask",
    "query",
    "rag",
    "task",
    "hub",
    "biblio",
    "research_agent",
    "orchestrate",
    "web_search",
    "crawl",
    "bundle",
    "event",
    "skill",
    "route_task",
    "plan",
    "loop_orchestrate",
    "trigger_autonomous_evolution",
    "read",
    "write",
}

# Log lines have TRUNCATED JSON — cannot parse as JSON. Extract fields via regex.
_TOOL_RE = re.compile(r"\|\s*[^|]+:(\w+)\s*\|")
_AGENT_RE = re.compile(r'"agent":\s*"([^"]+)"')
_IN_RE = re.compile(r'"in":\s*"((?:[^"\\]|\\.)*)')  # may be truncated
_OUT_RE = re.compile(r'"out":\s*"((?:[^"\\]|\\.)*)')  # may be truncated
_STATUS_RE = re.compile(r"\|\s*(\w+)\s*$")


def parse_audit_log(path: Path):
    """Yield (tool, agent, args_preview, out_preview, status) for valuable OUT lines."""
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "Direction.OUT" not in line:
                continue

            # Tool
            mt = _TOOL_RE.search(line)
            if not mt:
                continue
            tool = mt.group(1)
            if tool not in VALUABLE_TOOLS:
                continue

            # Agent
            ma = _AGENT_RE.search(line)
            if not ma:
                continue
            agent = ma.group(1)
            if agent in SKIP_AGENTS:
                continue

            # Status (last field)
            ms = _STATUS_RE.search(line)
            status = ms.group(1) if ms else "UNK"

            # Args + out (may be truncated — that's OK, we just want context)
            mi = _IN_RE.search(line)
            mo = _OUT_RE.search(line)
            args_preview = mi.group(1)[:300] if mi else ""
            out_preview = mo.group(1)[:300] if mo else ""

            yield tool, agent, args_preview, out_preview, status


def build_transitions(events: list) -> list:
    """
    Convert consecutive (tool, agent, args, out, status) events into
    (state_t_ctx, action, state_t1_ctx, success) transitions.
    """
    transitions = []
    for i in range(1, len(events)):
        prev = events[i - 1]
        cur = events[i]
        # state_t context = prev tool's output
        state_t_ctx = f"after {prev[0]}({prev[1]}): {prev[3][:200]}"
        # state_t1 context = current tool's output
        state_t1_ctx = f"after {cur[0]}({cur[1]}): {cur[3][:200]}"
        action = {
            "type": "replay",
            "tool": cur[0],
            "agent": cur[1],
            "args": cur[2][:200],
            "result_preview": cur[3][:100],
            "status": cur[4],
        }
        transitions.append((state_t_ctx, action, state_t1_ctx, cur[4] == "OK"))
    return transitions


def main():
    # Le journal se configure ICI, au point d'entree, et non a l'import : c'est
    # ce qui rend le module importable sans privilege filesystem. Retirer
    # l'effet de bord sans brancher cet appel aurait fait perdre le journal en
    # silence -- le remede serait devenu le defaut suivant.
    configurer_journal()
    init_db()
    n_before = count_traces()
    logging.info(f"start — {n_before} existing traces")

    goal_emb = encode_state(GOAL_TEXT)

    logging.info(f"Parsing {AUDIT_LOG} ({AUDIT_LOG.stat().st_size / 1024 / 1024:.1f} MB)...")
    events = list(parse_audit_log(AUDIT_LOG))
    logging.info(f"Valuable OUT events: {len(events):,}")

    if len(events) < 2:
        logging.warning("Too few events to build transitions")
        return

    transitions = build_transitions(events)
    logging.info(f"Transitions to replay: {len(transitions):,}")

    inserted = 0
    errors = 0

    for state_t_ctx, action, state_t1_ctx, success in tqdm(transitions, desc="replay"):
        try:
            state_t_emb = encode_state(state_t_ctx)
            state_t1_emb = encode_state(state_t1_ctx)
            cost_before = total_cost(state_t_emb, goal_emb)
            cost_after = total_cost(state_t1_emb, goal_emb)

            record_trace(
                state_t_emb=state_t_emb,
                action=action,
                state_t1_emb=state_t1_emb,
                cost_before=cost_before,
                cost_after=cost_after,
                task_type=f"replay_{action['tool']}",
                success=success,
            )
            inserted += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                logging.warning(f"trace err: {e}")

    n_after = count_traces()
    logging.info(
        f"Done — inserted={inserted} errors={errors} total_traces={n_after} (was {n_before})"
    )

    # Anchor to lessons
    try:
        from nokido_agent.app.forge_self_correction import anchor_solution

        anchor_solution(
            problem="AMI trace replay from mcp_audit.log",
            solution=f"Replayed {inserted} historical transitions from {len(events)} valuable tool calls. Total traces now: {n_after}",
            example="python tools/forge_trace_replay.py  # re-run anytime to add new history",
            domain="mpc",
        )
    except Exception:
        pass

    return inserted


if __name__ == "__main__":
    main()

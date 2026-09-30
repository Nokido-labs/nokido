"""
forge_planbench_runner.py — PlanBench benchmark runner pour Nokido.

Évalue la capacité de planification LLM sur BlocksWorld.
Validation déterministe : simulation step-by-step, pas de LLM-as-judge.

Dataset: karthikv792/LLMs-Planning (GitHub) / PlanBench paper (Valmeekam 2022)

Metric: plan_accuracy — % de plans valides ET atteignant le goal state.

Usage:
    python tools/forge_planbench_runner.py --provider mistral [--max 50]
"""

import argparse
import json
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field
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
PB_DIR = ROOT / "RAG" / "planbench"
PB_DIR.mkdir(exist_ok=True)

# HuggingFace rows API — tasksource/planbench
# task_1 = plan generation (what we benchmark), task_3+ = verification/other
_HF_ROWS_URL = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=tasksource%2Fplanbench&config=default&split=train&offset={offset}&limit={limit}"
)


# ── BlocksWorld State Machine ─────────────────────────────────────────────────


@dataclass
class BWState:
    """
    BlocksWorld state.
    on[block] = "table" | "block_name"
    holding = None | block_name
    """

    on: dict = field(default_factory=dict)  # block -> what it sits on
    clear: set = field(default_factory=set)  # blocks with nothing on top
    holding: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "BWState":
        s = cls()
        s.on = dict(d.get("on", {}))
        s.clear = set(d.get("clear", []))
        s.holding = d.get("holding")
        # Derive clear: all blocks that aren't under another block
        if s.on and not s.clear:
            under = set(s.on.values()) - {"table"}
            all_blocks = set(s.on.keys())
            s.clear = all_blocks - under
        return s

    def copy(self) -> "BWState":
        return BWState(dict(self.on), set(self.clear), self.holding)

    def hand_empty(self) -> bool:
        return self.holding is None


def _bw_execute(state: BWState, step: str) -> tuple[BWState | None, str]:
    """
    Execute one BlocksWorld action. Returns (new_state, error) or (None, error).
    PDDL actions: pickup X, putdown X, stack X Y, unstack X Y
    Also accepts natural variants: pick up X, put down X, etc.
    """
    s = step.strip().lower()
    s = re.sub(r"\s+", " ", s)

    # Normalize variants
    s = re.sub(r"^pick up ", "pickup ", s)
    s = re.sub(r"^put down ", "putdown ", s)

    ns = state.copy()

    # pickup X — pick block X from table
    m = re.match(r"^pickup (\w+)$", s)
    if m:
        x = m.group(1)
        if not ns.hand_empty():
            return None, f"hand not empty (holding {ns.holding})"
        if x not in ns.on:
            return None, f"unknown block {x}"
        if ns.on[x] != "table":
            return None, f"{x} not on table (on {ns.on[x]})"
        if x not in ns.clear:
            return None, f"{x} not clear"
        ns.holding = x
        ns.clear.discard(x)
        del ns.on[x]
        # table becomes clear where x was (no op needed for table)
        return ns, ""

    # putdown X — place held block on table
    m = re.match(r"^putdown (\w+)$", s)
    if m:
        x = m.group(1)
        if ns.holding != x:
            return None, f"not holding {x} (holding {ns.holding})"
        ns.on[x] = "table"
        ns.clear.add(x)
        ns.holding = None
        return ns, ""

    # unstack X Y — pick X off Y
    m = re.match(r"^unstack (\w+) (\w+)$", s)
    if m:
        x, y = m.group(1), m.group(2)
        if not ns.hand_empty():
            return None, f"hand not empty (holding {ns.holding})"
        if x not in ns.on:
            return None, f"unknown block {x}"
        if ns.on[x] != y:
            return None, f"{x} not on {y} (on {ns.on[x]})"
        if x not in ns.clear:
            return None, f"{x} not clear"
        ns.holding = x
        ns.clear.discard(x)
        ns.clear.add(y)
        del ns.on[x]
        return ns, ""

    # stack X Y — place held block on Y
    m = re.match(r"^stack (\w+) (\w+)$", s)
    if m:
        x, y = m.group(1), m.group(2)
        if ns.holding != x:
            return None, f"not holding {x} (holding {ns.holding})"
        if y not in ns.clear:
            return None, f"{y} not clear"
        ns.on[x] = y
        ns.clear.add(x)
        ns.clear.discard(y)
        ns.holding = None
        return ns, ""

    return None, f"unknown action: {step!r}"


def _bw_goal_reached(state: BWState, goal_on: dict) -> bool:
    """Check if goal_on conditions are all satisfied in current state."""
    for block, target in goal_on.items():
        if state.on.get(block) != target:
            return False
    return state.holding is None


# ── Dataset download & normalization ─────────────────────────────────────────


def _fetch(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LaForge/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except Exception:
        return None


def _normalize_entry(raw: dict) -> dict | None:
    """
    Normalize various PlanBench/LLMs-Planning formats to canonical:
    {id, init_state, goal_state, init_on, goal_on, optimal_plan, n_steps}
    """
    # Format A: {instance_id, init_state (text), goal_state (text), plan}
    if "init_state" in raw or "initial_state" in raw:
        init_text = raw.get("init_state") or raw.get("initial_state", "")
        goal_text = raw.get("goal_state") or raw.get("goal", "")
        plan_text = raw.get("plan") or raw.get("solution") or raw.get("answer") or ""
        return {
            "id": raw.get("instance_id") or raw.get("id", ""),
            "init_text": init_text,
            "goal_text": goal_text,
            "init_on": _parse_bw_text(init_text),
            "goal_on": _parse_bw_text(goal_text),
            "optimal_plan": plan_text,
            "n_steps": raw.get("n_steps") or raw.get("optimum") or len(plan_text.splitlines()),
        }
    # Format B: {question, answer} — NLP problem
    if "question" in raw or "problem" in raw:
        q = raw.get("question") or raw.get("problem", "")
        a = raw.get("answer") or raw.get("plan") or ""
        init_on, goal_on = _parse_bw_problem(q)
        return {
            "id": raw.get("id") or raw.get("instance_id", ""),
            "init_text": q,
            "goal_text": "",
            "init_on": init_on,
            "goal_on": goal_on,
            "optimal_plan": a,
            "n_steps": len(a.splitlines()) if a else 0,
        }
    return None


def _parse_bw_text(text: str) -> dict:
    """
    Parse BlocksWorld state description to on-dict.
    'Block A is on Block B' -> {'a': 'b'}
    'Block A is on the table' -> {'a': 'table'}
    """
    on = {}
    text = text.lower()
    # "X is on Y" patterns
    for m in re.finditer(r"block\s+(\w+)\s+is\s+on\s+(?:top\s+of\s+)?(?:block\s+)?(\w+)", text):
        x, y = m.group(1), m.group(2)
        on[x] = "table" if y in ("table", "the") else y
    # "X is on the table"
    for m in re.finditer(r"block\s+(\w+)\s+is\s+on\s+the\s+table", text):
        on[m.group(1)] = "table"
    return on


def _parse_bw_problem(text: str) -> tuple[dict, dict]:
    """Split a combined problem description into init_on and goal_on."""
    text_lower = text.lower()
    # Find goal section
    goal_idx = max(
        text_lower.find("goal"),
        text_lower.find("your goal"),
        text_lower.find("the objective"),
    )
    if goal_idx > 0:
        init_text = text[:goal_idx]
        goal_text = text[goal_idx:]
    else:
        init_text = text
        goal_text = ""
    return _parse_bw_text(init_text), _parse_bw_text(goal_text)


def _pddl_to_natural(plan_str: str) -> str:
    """Convert PDDL plan '(unstack a b)\n(put-down a)' to natural 'unstack a b\nputdown a'."""
    steps = []
    for token in re.findall(r"\(([^)]+)\)", plan_str.lower()):
        parts = token.strip().split()
        if not parts:
            continue
        action = parts[0].replace("-", "")  # put-down → putdown, pick-up → pickup
        args = " ".join(parts[1:])
        steps.append(f"{action} {args}".strip())
    return "\n".join(steps)


def _hf_fetch_planbench(n: int = 500) -> list:
    """Fetch task_1 (plan generation) entries from tasksource/planbench via HF rows API."""
    entries = []
    batch = 100
    offset = 0
    while len(entries) < n:
        url = _HF_ROWS_URL.format(offset=offset, limit=batch)
        raw = _fetch(url)
        if not raw:
            break
        try:
            data = json.loads(raw)
            rows = data.get("rows", [])
            if not rows:
                break
            for r in rows:
                row = r.get("row", r)
                # Filter to task_1 = plan generation, blocksworld domain
                task = row.get("task", "")
                domain = row.get("domain", "")
                if "task_1" not in task:
                    continue
                if "blocksworld" not in domain.lower():
                    continue
                query = row.get("query", "")
                gt_raw = row.get("ground_truth_plan", "")
                gt_plan = _pddl_to_natural(gt_raw)
                # Parse init/goal from query
                init_on, goal_on = _parse_bw_problem(query)
                entries.append(
                    {
                        "id": row.get("instance_id", f"pb_{len(entries)}"),
                        "task": task,
                        "domain": domain,
                        "init_text": query,
                        "goal_text": "",
                        "init_on": init_on,
                        "goal_on": goal_on,
                        "optimal_plan": gt_plan,
                        "n_steps": len(gt_plan.splitlines()),
                        "query": query,
                    }
                )
            offset += batch
            if len(rows) < batch:
                break
        except Exception as e:
            print(f"[planbench] HF fetch error: {e}")
            break
    return entries


def ensure_dataset(dataset_path: Path | None = None) -> list:
    cached = PB_DIR / "planbench.jsonl"

    if dataset_path and Path(dataset_path).exists():
        raw = json.loads(Path(dataset_path).read_bytes())
        data = raw if isinstance(raw, list) else raw.get("instances", [raw])
        entries = [_normalize_entry(e) for e in data]
        return [e for e in entries if e]

    if cached.exists():
        entries = [json.loads(l) for l in cached.read_text().splitlines() if l.strip()]
        print(f"[planbench] cached: {len(entries)} entries")
        return entries

    print("[planbench] downloading from HuggingFace tasksource/planbench...")
    entries = _hf_fetch_planbench(n=500)

    if entries:
        print(f"[planbench] downloaded {len(entries)} task_1 blocksworld entries")
        cached.write_text("\n".join(json.dumps(e) for e in entries))
        return entries

    print("[planbench] HF unavailable — generating synthetic instances...")
    entries = _generate_synthetic(30)
    cached.write_text("\n".join(json.dumps(e) for e in entries))
    return entries


def _generate_synthetic(n: int) -> list:
    """Generate small BlocksWorld instances for testing."""
    import random

    random.seed(42)
    entries = []
    blocks = ["a", "b", "c", "d"]
    for i in range(n):
        nb = random.randint(2, 4)
        bks = blocks[:nb]
        # Random initial stack
        random.shuffle(bks)
        init_on = {}
        for j, b in enumerate(bks):
            init_on[b] = "table" if j == 0 else bks[j - 1]
        # Random goal (different arrangement)
        random.shuffle(bks)
        goal_on = {}
        for j, b in enumerate(bks):
            goal_on[b] = "table" if j == 0 else bks[j - 1]

        init_text = " ".join(
            f"Block {b.upper()} is on {'the table' if v == 'table' else 'Block ' + v.upper()}."
            for b, v in init_on.items()
        )
        goal_text = " ".join(
            f"Block {b.upper()} is on {'the table' if v == 'table' else 'Block ' + v.upper()}."
            for b, v in goal_on.items()
        )
        entries.append(
            {
                "id": f"synthetic_{i}",
                "init_text": init_text,
                "goal_text": goal_text,
                "init_on": init_on,
                "goal_on": goal_on,
                "optimal_plan": "",
                "n_steps": 0,
            }
        )
    return entries


# ── Prompt & LLM ─────────────────────────────────────────────────────────────


def _build_prompt(entry: dict) -> str:
    # Use original query if available (already includes domain description)
    if entry.get("query"):
        return (
            f"{entry['query']}\n\n"
            "Output ONLY the plan — one action per line (e.g. 'unstack a b'), "
            "no explanations, no numbering, no parentheses."
        )
    # Fallback: build from parsed states
    init = entry["init_text"] or _on_to_text(entry["init_on"])
    goal = entry["goal_text"] or _on_to_text(entry["goal_on"])
    return (
        "You are a BlocksWorld planning agent. Generate a valid sequence of actions.\n\n"
        "ACTIONS: pickup X | putdown X | unstack X Y | stack X Y\n\n"
        f"INITIAL STATE:\n{init}\n\n"
        f"GOAL STATE:\n{goal}\n\n"
        "Output ONLY the plan — one action per line, no explanations, no numbering."
    )


def _on_to_text(on: dict) -> str:
    return " ".join(
        f"Block {b.upper()} is on {'the table' if v == 'table' else 'Block ' + v.upper()}."
        for b, v in on.items()
    )


def _read_env(key: str) -> str:
    val = __import__("os").environ.get(key, "")
    if val:
        return val
    env_file = ROOT / "Nokido.env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip()
    return ""


def _http_post(url: str, body: dict, headers: dict | None = None, timeout: int = 45) -> dict:
    from nokido_agent.tools.forge_bench_http import http_post  # source unique (cliquet clones 21/08)
    return http_post(url, body, headers=headers, timeout=timeout)


def _retry_post(
    url: str, body: dict, headers: dict, timeout: int = 45, max_retries: int = 4
) -> dict:
    import urllib.error

    delay = 2.0
    for attempt in range(max_retries):
        try:
            return _http_post(url, body, headers, timeout)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise


def call_llm(prompt: str, provider: str = "mistral") -> str:
    if provider == "mistral":
        key = _read_env("MISTRAL_API_KEY")
        if not key:
            return "[ERR] MISTRAL_API_KEY absent"
        d = _retry_post(
            "https://api.mistral.ai/v1/chat/completions",
            {
                "model": "mistral-small-latest",
                "messages": [{"role": "user", "content": prompt[:5000]}],
                "max_tokens": 512,
                "temperature": 0.0,
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        return d["choices"][0]["message"]["content"].strip()
    return f"[ERR] Unknown provider: {provider}"


# ── Plan parsing & validation ─────────────────────────────────────────────────


def _parse_plan(text: str) -> list[str]:
    """Extract plan steps from LLM response."""
    lines = []
    for line in text.strip().splitlines():
        line = line.strip().lower()
        line = re.sub(r"^[\d\.\-\*\)]+\s*", "", line)  # strip numbering
        line = re.sub(r"\s+", " ", line)
        # Accept only valid action prefixes
        if re.match(r"^(pickup|putdown|unstack|stack|pick up|put down)\s+\w", line):
            # Normalize
            line = re.sub(r"^pick up ", "pickup ", line)
            line = re.sub(r"^put down ", "putdown ", line)
            lines.append(line)
    return lines


def _validate_plan(entry: dict, steps: list[str]) -> tuple[bool, str]:
    """
    Simulate plan execution. Returns (goal_reached, reason).
    """
    init_on = entry.get("init_on", {})
    goal_on = entry.get("goal_on", {})

    if not init_on:
        return False, "no_init_state"
    if not goal_on:
        return False, "no_goal_state"
    if not steps:
        return False, "empty_plan"

    # Build initial state
    all_blocks = set(init_on.keys()) | set(init_on.values()) - {"table"}
    under = set(init_on.values()) - {"table"}
    state = BWState(
        on=dict(init_on),
        clear=set(init_on.keys()) - under,
        holding=None,
    )

    for i, step in enumerate(steps):
        new_state, err = _bw_execute(state, step)
        if new_state is None:
            return False, f"step_{i + 1}_invalid:{err[:60]}"
        state = new_state

    if _bw_goal_reached(state, goal_on):
        return True, "ok"
    return False, "goal_not_reached"


# ── Runner ────────────────────────────────────────────────────────────────────


def run(provider: str = "mistral", max_entries: int = 50, dataset_path: Path | None = None) -> dict:
    entries = ensure_dataset(dataset_path)
    subset = entries[:max_entries]
    print(f"[planbench] {len(subset)} entries | provider={provider} | deterministic validation")

    results = []
    t0 = time.time()
    errors = 0
    fail_reasons: dict[str, int] = {}

    for i, entry in enumerate(subset):
        prompt = _build_prompt(entry)

        try:
            t_call = time.time()
            response = call_llm(prompt, provider)
            elapsed = round(time.time() - t_call, 2)
        except Exception as e:
            response = f"[ERR] {e}"
            elapsed = 0.0
            errors += 1

        if response.startswith("[ERR]"):
            passed, reason = False, "llm_error"
            errors += 1
            steps = []
        else:
            steps = _parse_plan(response)
            passed, reason = _validate_plan(entry, steps)

        if not passed:
            key = reason.split(":")[0].split("_")[0][:20]
            fail_reasons[key] = fail_reasons.get(key, 0) + 1

        status = "PASS" if passed else "FAIL"
        detail = f" [{reason[:50]}]" if not passed else ""
        n_steps_pred = len(steps)
        n_steps_opt = entry.get("n_steps") or "?"
        print(
            f"  [{i + 1}/{len(subset)}] {status} {elapsed}s{detail} | "
            f"steps={n_steps_pred}/{n_steps_opt} | {entry['id']}"
        )

        results.append(
            {
                "idx": i,
                "id": entry["id"],
                "pass": passed,
                "elapsed_s": elapsed,
                "steps_pred": n_steps_pred,
                "steps_opt": n_steps_opt,
                "reason": reason,
                "plan": "\n".join(steps),
            }
        )
        time.sleep(0.8)

    elapsed_total = round(time.time() - t0, 1)
    passed_n = sum(1 for r in results if r["pass"])
    pass_rate = round(passed_n / len(results) * 100, 1) if results else 0.0

    summary = {
        "provider": provider,
        "n_total": len(subset),
        "passed": passed_n,
        "pass_rate": pass_rate,
        "errors": errors,
        "elapsed_s": elapsed_total,
        "fail_reasons": fail_reasons,
        "results": results,
    }

    out = PB_DIR / f"planbench_{provider}_{len(subset)}.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str))

    print(f"\n{'=' * 50}")
    print(f"PLANBENCH pass : {pass_rate}%  ({passed_n}/{len(subset)})")
    print(f"Errors         : {errors}")
    print(f"Avg latency    : {round(sum(r['elapsed_s'] for r in results) / len(results), 2)}s")
    if fail_reasons:
        print(f"Fail breakdown : {dict(sorted(fail_reasons.items(), key=lambda x: -x[1]))}")
    print(f"Saved -> {out}")

    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_self_correction import anchor_solution

        anchor_solution(
            problem=f"PlanBench BlocksWorld — {len(subset)} instances",
            solution=f"pass_rate={pass_rate}% provider={provider} errors={errors} fails={fail_reasons}",
            example=f"python tools/forge_planbench_runner.py --provider {provider} --max {len(subset)}",
            domain="systeme",
        )
    except Exception:
        pass

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="mistral", choices=["mistral", "ollama", "cerebras"])
    parser.add_argument("--max", type=int, default=50)
    parser.add_argument("--dataset", default=None)
    args = parser.parse_args()
    run(
        provider=args.provider,
        max_entries=args.max,
        dataset_path=Path(args.dataset) if args.dataset else None,
    )

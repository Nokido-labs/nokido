"""
forge_terminal_bench_runner.py — Terminal-Bench 2.0 pour Nokido.

Évalue la capacité d'un agent à interagir avec le terminal pour résoudre
des tâches système réelles : debug, compilation, scripts, grep, git.

Inspiré de Terminal-Bench / Epoch AI (2026) + InterCode (Yang et al., NeurIPS 2023).

Scoring: task_complete@K — tâche résolue en ≤ K tours shell.
Sandboxing: tmpdir isolé + timeout subprocess par commande.
Environnement: Windows PowerShell ou bash (détecté auto).

Architecture agent-loop :
  1. Présenter tâche + état initial au LLM
  2. LLM propose une commande shell
  3. Exécuter la commande (sandboxé dans tmpdir)
  4. Retourner stdout/stderr au LLM
  5. LLM propose commande suivante ou déclare DONE
  6. Valider : critère de succès de la tâche

Usage:
    python tools/forge_terminal_bench_runner.py --provider mistral [--max 20]
    python tools/forge_terminal_bench_runner.py --provider mistral --max 50 --rounds 6
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
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
TB_DIR = ROOT / "RAG" / "terminal_bench"
TB_DIR.mkdir(exist_ok=True)

LAFORGE_PYTHON = __import__("os").path.expanduser(r"~\miniforge3\python.exe")

# ── Task definitions ───────────────────────────────────────────────────────────


def _make_tasks() -> list[dict]:
    """
    30 terminal tasks covering: debug, script, grep, git, install, file ops.
    Each task has:
      - id, category, description
      - setup(tmpdir) -> None     : creates initial state
      - validate(tmpdir) -> bool  : checks success criterion
    """
    tasks = []

    # ── Category: debug (fix broken Python script) ──────────────────────────

    def _setup_debug_syntax(d):
        Path(d, "broken.py").write_text(
            "def add(a, b)\n    return a + b\nprint(add(1, 2))\n", encoding="utf-8"
        )

    def _validate_debug_syntax(d):
        r = subprocess.run(
            [LAFORGE_PYTHON, "broken.py"],
            cwd=d,
            capture_output=True,
            text=True,
            timeout=10,
        errors="replace")
        return r.returncode == 0 and "3" in r.stdout

    tasks.append(
        {
            "id": "debug_syntax_01",
            "category": "debug",
            "description": (
                "The file broken.py contains a Python syntax error. "
                "Fix it so that running `python broken.py` prints 3."
            ),
            "setup": _setup_debug_syntax,
            "validate": _validate_debug_syntax,
        }
    )

    def _setup_debug_logic(d):
        Path(d, "factorial.py").write_text(
            "def factorial(n):\n    if n == 0:\n        return 0\n"
            "    return n * factorial(n - 1)\nprint(factorial(5))\n",
            encoding="utf-8",
        )

    def _validate_debug_logic(d):
        r = subprocess.run(
            [LAFORGE_PYTHON, "factorial.py"],
            cwd=d,
            capture_output=True,
            text=True,
            timeout=10,
        errors="replace")
        return r.returncode == 0 and "120" in r.stdout

    tasks.append(
        {
            "id": "debug_logic_02",
            "category": "debug",
            "description": (
                "factorial.py has a logic bug — factorial(0) should return 1, not 0. "
                "Fix it so `python factorial.py` prints 120."
            ),
            "setup": _setup_debug_logic,
            "validate": _validate_debug_logic,
        }
    )

    def _setup_debug_import(d):
        Path(d, "app.py").write_text("import mathx\nprint(mathx.sqrt(16))\n", encoding="utf-8")

    def _validate_debug_import(d):
        r = subprocess.run(
            [LAFORGE_PYTHON, "app.py"],
            cwd=d,
            capture_output=True,
            text=True,
            timeout=10,
        errors="replace")
        return r.returncode == 0 and "4" in r.stdout

    tasks.append(
        {
            "id": "debug_import_03",
            "category": "debug",
            "description": (
                "app.py imports 'mathx' which doesn't exist. "
                "Fix the import so it uses the correct stdlib module and `python app.py` prints 4.0."
            ),
            "setup": _setup_debug_import,
            "validate": _validate_debug_import,
        }
    )

    def _setup_debug_indentation(d):
        Path(d, "compute.py").write_text(
            "def compute(x):\nreturn x * 2\nprint(compute(7))\n", encoding="utf-8"
        )

    def _validate_debug_indentation(d):
        r = subprocess.run(
            [LAFORGE_PYTHON, "compute.py"],
            cwd=d,
            capture_output=True,
            text=True,
            timeout=10,
        errors="replace")
        return r.returncode == 0 and "14" in r.stdout

    tasks.append(
        {
            "id": "debug_indent_04",
            "category": "debug",
            "description": (
                "compute.py has an indentation error. Fix it so `python compute.py` prints 14."
            ),
            "setup": _setup_debug_indentation,
            "validate": _validate_debug_indentation,
        }
    )

    # ── Category: file ops ───────────────────────────────────────────────────

    def _setup_file_create(d):
        pass  # nothing to setup

    def _validate_file_create(d):
        f = Path(d, "hello.txt")
        return f.exists() and "Hello, Nokido!" in f.read_text(encoding="utf-8")

    tasks.append(
        {
            "id": "file_create_05",
            "category": "file_ops",
            "description": "Create a file named hello.txt containing exactly: Hello, Nokido!",
            "setup": _setup_file_create,
            "validate": _validate_file_create,
        }
    )

    def _setup_file_count(d):
        for i in range(7):
            Path(d, f"data_{i}.csv").write_text(f"id,value\n{i},{i * 10}\n")

    def _validate_file_count(d):
        f = Path(d, "count.txt")
        return f.exists() and "7" in f.read_text()

    tasks.append(
        {
            "id": "file_count_06",
            "category": "file_ops",
            "description": (
                "Count the number of .csv files in the current directory and save the count to count.txt."
            ),
            "setup": _setup_file_count,
            "validate": _validate_file_count,
        }
    )

    def _setup_file_rename(d):
        Path(d, "oldname.txt").write_text("content")

    def _validate_file_rename(d):
        return (not Path(d, "oldname.txt").exists()) and Path(d, "newname.txt").exists()

    tasks.append(
        {
            "id": "file_rename_07",
            "category": "file_ops",
            "description": "Rename the file oldname.txt to newname.txt.",
            "setup": _setup_file_rename,
            "validate": _validate_file_rename,
        }
    )

    def _setup_file_concat(d):
        Path(d, "a.txt").write_text("Hello ")
        Path(d, "b.txt").write_text("World")

    def _validate_file_concat(d):
        f = Path(d, "merged.txt")
        return f.exists() and f.read_text(encoding="utf-8").strip() == "Hello World"

    tasks.append(
        {
            "id": "file_concat_08",
            "category": "file_ops",
            "description": "Concatenate a.txt and b.txt into merged.txt (content: 'Hello World').",
            "setup": _setup_file_concat,
            "validate": _validate_file_concat,
        }
    )

    # ── Category: grep / search ──────────────────────────────────────────────

    def _setup_grep_count(d):
        lines = [
            "ERROR: disk full\n",
            "INFO: started\n",
            "ERROR: timeout\n",
            "WARNING: slow\n",
            "ERROR: crash\n",
        ]
        Path(d, "app.log").write_text("".join(lines))

    def _validate_grep_count(d):
        f = Path(d, "error_count.txt")
        return f.exists() and "3" in f.read_text()

    tasks.append(
        {
            "id": "grep_count_09",
            "category": "grep",
            "description": (
                "app.log contains log lines. Count the number of lines containing 'ERROR' "
                "and save that count to error_count.txt."
            ),
            "setup": _setup_grep_count,
            "validate": _validate_grep_count,
        }
    )

    def _setup_grep_extract(d):
        Path(d, "config.ini").write_text(
            "[server]\nhost=localhost\nport=8080\n[db]\nhost=localhost\nport=5432\n"
        )

    def _validate_grep_extract(d):
        f = Path(d, "hosts.txt")
        if not f.exists():
            return False
        content = f.read_text()
        return "localhost" in content and "localhost" in content

    tasks.append(
        {
            "id": "grep_extract_10",
            "category": "grep",
            "description": (
                "Extract all lines containing 'host=' from config.ini and save them to hosts.txt."
            ),
            "setup": _setup_grep_extract,
            "validate": _validate_grep_extract,
        }
    )

    # ── Category: script (write + run) ──────────────────────────────────────

    def _setup_script_sum(d):
        Path(d, "numbers.txt").write_text("10\n20\n30\n40\n")

    def _validate_script_sum(d):
        f = Path(d, "result.txt")
        return f.exists() and "100" in f.read_text()

    tasks.append(
        {
            "id": "script_sum_11",
            "category": "script",
            "description": (
                "Write a Python script that reads numbers.txt (one integer per line), "
                "sums them, and writes the result to result.txt."
            ),
            "setup": _setup_script_sum,
            "validate": _validate_script_sum,
        }
    )

    def _setup_script_reverse(d):
        Path(d, "words.txt").write_text("alpha\nbeta\ngamma\n")

    def _validate_script_reverse(d):
        f = Path(d, "reversed.txt")
        if not f.exists():
            return False
        lines = f.read_text().strip().splitlines()
        return lines == ["gamma", "beta", "alpha"]

    tasks.append(
        {
            "id": "script_reverse_12",
            "category": "script",
            "description": (
                "Write a script that reads words.txt and writes reversed.txt "
                "with the lines in reverse order."
            ),
            "setup": _setup_script_reverse,
            "validate": _validate_script_reverse,
        }
    )

    def _setup_script_json(d):
        data = [{"name": "Alice", "score": 90}, {"name": "Bob", "score": 75}]
        Path(d, "data.json").write_text(json.dumps(data))

    def _validate_script_json(d):
        f = Path(d, "summary.txt")
        if not f.exists():
            return False
        t = f.read_text()
        return "Alice" in t and "90" in t

    tasks.append(
        {
            "id": "script_json_13",
            "category": "script",
            "description": (
                "Parse data.json (list of {name, score}), find the highest scorer, "
                "and write 'Name: <name> Score: <score>' to summary.txt."
            ),
            "setup": _setup_script_json,
            "validate": _validate_script_json,
        }
    )

    # ── Category: git ────────────────────────────────────────────────────────

    def _setup_git_init(d):
        Path(d, "README.md").write_text("# MyProject\n")

    def _validate_git_init(d):
        r = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=d,
            capture_output=True,
            text=True,
            timeout=10,
        errors="replace")
        return r.returncode == 0 and len(r.stdout.strip()) > 0

    tasks.append(
        {
            "id": "git_init_14",
            "category": "git",
            "description": (
                "Initialize a git repository in the current directory, "
                "add README.md, and create an initial commit."
            ),
            "setup": _setup_git_init,
            "validate": _validate_git_init,
        }
    )

    def _setup_git_branch(d):
        subprocess.run(["git", "init"], cwd=d, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=d, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=d, capture_output=True)
        Path(d, "main.py").write_text("# main\n")
        subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=d, capture_output=True)

    def _validate_git_branch(d):
        r = subprocess.run(
            ["git", "branch"],
            cwd=d,
            capture_output=True,
            text=True,
            timeout=10,
        errors="replace")
        return "feature" in r.stdout

    tasks.append(
        {
            "id": "git_branch_15",
            "category": "git",
            "description": "Create a git branch named 'feature' and switch to it.",
            "setup": _setup_git_branch,
            "validate": _validate_git_branch,
        }
    )

    # ── Category: environment / system ──────────────────────────────────────

    def _setup_env_python_version(d):
        pass

    def _validate_env_python_version(d):
        f = Path(d, "python_version.txt")
        if not f.exists():
            return False
        return "Python 3" in f.read_text()

    tasks.append(
        {
            "id": "env_pyver_16",
            "category": "system",
            "description": ("Run python --version and save the output to python_version.txt."),
            "setup": _setup_env_python_version,
            "validate": _validate_env_python_version,
        }
    )

    def _setup_env_ls(d):
        for n in ("a.py", "b.py", "c.txt"):
            Path(d, n).write_text("")

    def _validate_env_ls(d):
        f = Path(d, "filelist.txt")
        if not f.exists():
            return False
        t = f.read_text()
        return "a.py" in t and "b.py" in t

    tasks.append(
        {
            "id": "env_ls_17",
            "category": "system",
            "description": "List all files in the current directory and save the listing to filelist.txt.",
            "setup": _setup_env_ls,
            "validate": _validate_env_ls,
        }
    )

    # ── Category: iterative debug (multi-turn) ───────────────────────────────

    def _setup_multi_fix(d):
        Path(d, "pipeline.py").write_text(
            "def process(items):\n"
            "    results = []\n"
            "    for item in items:\n"
            "        if item > 0\n"
            "            results.append(item * 2)\n"
            "    return results\n\n"
            "print(process([1, -2, 3, 4]))\n",
            encoding="utf-8",
        )

    def _validate_multi_fix(d):
        r = subprocess.run(
            [LAFORGE_PYTHON, "pipeline.py"],
            cwd=d,
            capture_output=True,
            text=True,
            timeout=10,
        errors="replace")
        return r.returncode == 0 and "[2, 6, 8]" in r.stdout

    tasks.append(
        {
            "id": "multi_fix_18",
            "category": "debug",
            "description": (
                "pipeline.py has syntax errors. Fix it so `python pipeline.py` prints [2, 6, 8]. "
                "You may need multiple iterations: run the script, read the error, fix, repeat."
            ),
            "setup": _setup_multi_fix,
            "validate": _validate_multi_fix,
        }
    )

    def _setup_multi_test(d):
        Path(d, "sorter.py").write_text(
            "def sort_desc(lst):\n    return sorted(lst)\n\n"
            "assert sort_desc([3,1,2]) == [3,2,1], 'Should be descending'\n"
            "print('OK')\n",
            encoding="utf-8",
        )

    def _validate_multi_test(d):
        r = subprocess.run(
            [LAFORGE_PYTHON, "sorter.py"],
            cwd=d,
            capture_output=True,
            text=True,
            timeout=10,
        errors="replace")
        return r.returncode == 0 and "OK" in r.stdout

    tasks.append(
        {
            "id": "multi_test_19",
            "category": "debug",
            "description": (
                "sorter.py has a logic bug — sort_desc should sort in descending order. "
                "Fix the function so the assertion passes and it prints 'OK'."
            ),
            "setup": _setup_multi_test,
            "validate": _validate_multi_test,
        }
    )

    def _setup_multi_pipeline(d):
        Path(d, "data.csv").write_text("name,age\nAlice,30\nBob,25\nCarol,35\n")

    def _validate_multi_pipeline(d):
        f = Path(d, "oldest.txt")
        return f.exists() and "Carol" in f.read_text()

    tasks.append(
        {
            "id": "multi_pipeline_20",
            "category": "script",
            "description": (
                "data.csv contains name,age columns. "
                "Write and run a script that finds the oldest person and writes their name to oldest.txt."
            ),
            "setup": _setup_multi_pipeline,
            "validate": _validate_multi_pipeline,
        }
    )

    return tasks


# ── LLM backends ─────────────────────────────────────────────────────────────


def _read_env(key: str) -> str:
    val = os.environ.get(key, "")
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


def call_llm(messages: list, provider: str = "mistral") -> str:
    if provider == "mistral":
        key = _read_env("MISTRAL_API_KEY")
        if not key:
            return "[ERR] MISTRAL_API_KEY absent"
        d = _retry_post(
            "https://api.mistral.ai/v1/chat/completions",
            {
                "model": "mistral-small-latest",
                "messages": messages,
                "max_tokens": 512,
                "temperature": 0.0,
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        return d["choices"][0]["message"]["content"].strip()

    if provider == "ollama":
        model = _read_env("OLLAMA_MODEL") or "qwen2.5-coder:latest"
        flat = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
        d = _http_post(
            "http://127.0.0.1:11434/api/generate",
            {"model": model, "prompt": flat, "stream": False},
            timeout=120,
        )
        return d.get("response", "").strip()

    if provider == "cerebras":
        key = _read_env("CEREBRAS_API_KEY")
        if not key:
            return "[ERR] CEREBRAS_API_KEY absent"
        d = _retry_post(
            "https://api.cerebras.ai/v1/chat/completions",
            {"model": "llama3.1-70b", "messages": messages, "max_tokens": 512, "temperature": 0.0},
            headers={"Authorization": f"Bearer {key}"},
        )
        return d["choices"][0]["message"]["content"].strip()

    return f"[ERR] Unknown provider: {provider}"


# ── Command extraction ────────────────────────────────────────────────────────

_DONE_RE = re.compile(r"\b(DONE|COMPLETE|FINISHED|SOLVED|TASK COMPLETE)\b", re.IGNORECASE)


def _extract_command(response: str) -> tuple[str, bool]:
    """
    Returns (command, is_done).
    Agent signals completion with DONE or by outputting only DONE.
    """
    if _DONE_RE.search(response.strip()):
        # Check if the entire response is just a done signal
        clean = _DONE_RE.sub("", response).strip(" \t\n`")
        if not clean:
            return "", True

    # Extract from code fence
    if "```" in response:
        m = re.search(r"```(?:bash|shell|powershell|cmd|)?\n?(.*?)```", response, re.DOTALL)
        if m:
            cmd = m.group(1).strip().splitlines()[0].strip()
            return cmd, False

    # Take first non-empty line that looks like a command
    for line in response.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("//"):
            return line, False

    return "", False


# ── Command execution sandbox ─────────────────────────────────────────────────


def _exec_command(cmd: str, cwd: str, timeout: int = 15) -> str:
    """Execute one shell command in cwd, return stdout+stderr (truncated)."""
    if not cmd.strip():
        return "[empty command]"

    # Replace bare 'python' with LAFORGE_PYTHON
    cmd = re.sub(r"\bpython(?:3)?\b", LAFORGE_PYTHON.replace("\\", "/"), cmd)

    try:
        r = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        out = (r.stdout + r.stderr).strip()
        return out[:800] if out else f"[exit {r.returncode}]"
    except subprocess.TimeoutExpired:
        return "[timeout]"
    except Exception as e:
        return f"[error: {e}]"


# ── Agent interaction loop ────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a terminal agent solving a task by executing shell commands.

Rules:
- Output ONE shell command per turn — nothing else, no explanations before it.
- Wrap the command in a ```bash fence.
- After the command you may add a brief comment on ONE line.
- When the task is complete, output only: DONE
- You are in a Windows environment but PowerShell and Python are available.
- Use python (will be mapped to the correct interpreter).
- Do not ask questions — act.
"""


def run_task(
    task: dict, provider: str = "mistral", max_rounds: int = 6, tmpdir: str | None = None
) -> dict:
    """Run one task in agent loop. Returns result dict."""
    own_dir = tmpdir is None
    if own_dir:
        tmpdir = tempfile.mkdtemp(prefix="tb_")

    try:
        task["setup"](tmpdir)
    except Exception as e:
        return {"id": task["id"], "solved": False, "rounds": 0, "error": f"setup: {e}"}

    history = [{"role": "system", "content": _SYSTEM_PROMPT}]
    history.append(
        {
            "role": "user",
            "content": (
                f"TASK: {task['description']}\n\n"
                "Current directory contains the files you need to work with. "
                "Start solving the task."
            ),
        }
    )

    rounds_used = 0
    solved = False
    trace = []

    for rnd in range(max_rounds):
        try:
            response = call_llm(history, provider)
        except Exception as e:
            trace.append({"round": rnd + 1, "cmd": "", "output": f"[llm_error: {e}]"})
            break

        cmd, is_done = _extract_command(response)

        if is_done:
            rounds_used = rnd + 1
            break

        if not cmd:
            trace.append({"round": rnd + 1, "cmd": "", "output": "[no command extracted]"})
            history.append({"role": "assistant", "content": response})
            history.append(
                {
                    "role": "user",
                    "content": "[no command found — output a command in ```bash fence or DONE]",
                }
            )
            continue

        output = _exec_command(cmd, tmpdir)
        trace.append({"round": rnd + 1, "cmd": cmd, "output": output})

        history.append({"role": "assistant", "content": f"```bash\n{cmd}\n```"})
        history.append({"role": "user", "content": f"Output:\n{output}"})
        rounds_used = rnd + 1

        # Early termination check
        try:
            if task["validate"](tmpdir):
                solved = True
                break
        except Exception:
            pass

        time.sleep(0.5)

    # Final validation
    if not solved:
        try:
            solved = task["validate"](tmpdir)
        except Exception:
            solved = False

    if own_dir:
        import shutil

        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

    return {
        "id": task["id"],
        "category": task["category"],
        "solved": solved,
        "rounds": rounds_used,
        "max_rounds": max_rounds,
        "trace": trace,
    }


# ── Runner ────────────────────────────────────────────────────────────────────


def run(provider: str = "mistral", max_entries: int = 20, max_rounds: int = 6) -> dict:
    tasks = _make_tasks()[:max_entries]
    print(f"[terminal_bench] {len(tasks)} tasks | provider={provider} | max_rounds={max_rounds}")

    results = []
    t0 = time.time()
    by_cat: dict[str, list[bool]] = {}

    for i, task in enumerate(tasks):
        t_task = time.time()
        res = run_task(task, provider=provider, max_rounds=max_rounds)
        elapsed = round(time.time() - t_task, 2)
        res["elapsed_s"] = elapsed

        cat = task["category"]
        by_cat.setdefault(cat, []).append(res["solved"])

        status = "PASS" if res["solved"] else "FAIL"
        trace_short = f"r={res['rounds']}"
        print(f"  [{i + 1}/{len(tasks)}] {status} {elapsed}s {trace_short} | {task['id']}")
        results.append(res)

    elapsed_total = round(time.time() - t0, 1)
    solved_n = sum(1 for r in results if r["solved"])
    solve_rate = round(solved_n / len(results) * 100, 1) if results else 0.0

    cat_scores = {cat: f"{sum(v)}/{len(v)}" for cat, v in by_cat.items()}

    summary = {
        "provider": provider,
        "n_total": len(results),
        "solved": solved_n,
        "solve_rate": solve_rate,
        "max_rounds": max_rounds,
        "elapsed_s": elapsed_total,
        "by_category": cat_scores,
        "results": results,
    }

    out = TB_DIR / f"terminal_bench_{provider}_{len(results)}.json"
    out.write_text(json.dumps(summary, indent=2, default=str))

    print(f"\n{'=' * 55}")
    print(f"TERMINAL-BENCH task_complete@{max_rounds} : {solve_rate}%  ({solved_n}/{len(results)})")
    avg_r = round(sum(r["rounds"] for r in results) / len(results), 1) if results else 0
    print(f"Avg rounds / task : {avg_r}")
    print(f"By category       : {cat_scores}")
    print(f"Saved -> {out}")

    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_self_correction import anchor_solution

        anchor_solution(
            problem=f"Terminal-Bench — {len(results)} tasks, task_complete@{max_rounds}",
            solution=f"solve_rate={solve_rate}% provider={provider} by_cat={cat_scores}",
            example=f"python tools/forge_terminal_bench_runner.py --provider {provider} --max {len(results)}",
            domain="systeme",
        )
    except Exception:
        pass

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="mistral", choices=["mistral", "ollama", "cerebras"])
    parser.add_argument("--max", type=int, default=20)
    parser.add_argument("--rounds", type=int, default=6, help="Max shell rounds per task")
    args = parser.parse_args()
    run(provider=args.provider, max_entries=args.max, max_rounds=args.rounds)

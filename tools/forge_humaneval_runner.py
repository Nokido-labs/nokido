"""
forge_humaneval_runner.py — HumanEval benchmark runner pour Nokido.

Évalue la capacité de génération de code Python (pass@1).
164 fonctions, chacune avec signature + docstring + unit tests.

Scoring: pass@1 — le code généré passe TOUS les unit tests à la première tentative.
Exécution sandboxée : subprocess Python avec timeout 10s.

Usage:
    python tools/forge_humaneval_runner.py --provider mistral [--max 50]
    python tools/forge_humaneval_runner.py --provider mistral --max 164
"""

import argparse
import gzip
import json
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
HE_DIR = ROOT / "RAG" / "humaneval"
# PAS de mkdir a l'import : sur le checkout du runner CI, RAG/ n'existe pas et
# mkdir sans parents MOURAIT a l'IMPORT (CI rouge e706dfa2, attrape par
# test_bench_http_nr). Cree paresseusement aux points d'ecriture.

# sys.executable D'ABORD : le chemin expanduser(~) depend du COMPTE — sous le
# sandbox (LaForgeSbx*), ~\miniforge3 n'existe pas -> WinError 2 sur CHAQUE
# test (mesure 2026-08-21 : 2/2 echecs a 1.2s, le code etait genere mais
# jamais execute). L'interpreteur qui fait tourner ce runner EST miniforge.
import os as _os
import sys as _sys
LAFORGE_PYTHON = _sys.executable or _os.path.expanduser(r"~\miniforge3\python.exe")

_HE_URL = "https://raw.githubusercontent.com/openai/human-eval/master/data/HumanEval.jsonl.gz"

# Modules stdlib que le modele utilise parfois SANS les importer (mesure
# 2026-08-21 : NameError hashlib sur HumanEval/162). L'oubli d'import est un
# artefact de generation, pas une erreur de logique : on l'injecte et on
# re-teste AVANT de payer un appel repair LLM. Fix deterministe, 0 token.
_STDLIB_INJECT = frozenset({
    "hashlib", "math", "re", "itertools", "collections", "functools",
    "datetime", "json", "string", "bisect", "heapq", "random",
})
_HE_URL_ALT = "https://huggingface.co/datasets/openai/openai_humaneval/resolve/main/openai_humaneval/test-00000-of-00001.parquet"


# ── Dataset ───────────────────────────────────────────────────────────────────


def _fetch(url: str, timeout: int = 60) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LaForge/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


def ensure_dataset() -> list:
    HE_DIR.mkdir(parents=True, exist_ok=True)
    cached = HE_DIR / "humaneval.jsonl"
    if cached.exists():
        entries = [json.loads(l) for l in cached.read_text().splitlines() if l.strip()]
        print(f"[humaneval] cached: {len(entries)} entries")
        return entries

    print("[humaneval] downloading...")
    raw = _fetch(_HE_URL)
    if not raw:
        print("[humaneval] ERROR: download failed")
        sys.exit(1)

    try:
        text = gzip.decompress(raw).decode("utf-8")
    except Exception:
        text = raw.decode("utf-8")

    entries = [json.loads(l) for l in text.splitlines() if l.strip()]
    print(f"[humaneval] downloaded: {len(entries)} entries")
    cached.write_text(text if text.endswith("\n") else text + "\n")
    return entries


# ── Prompt ────────────────────────────────────────────────────────────────────


def _build_prompt(entry: dict) -> str:
    return (
        "Complete the following Python function. "
        "Return the COMPLETE function (def line + body) in a single ```python fence. "
        "No explanations. No extra functions.\n\n"
        f"```python\n{entry['prompt']}# YOUR IMPLEMENTATION HERE\n```"
    )


# ── LLM call (same backends as BFCL runner) ──────────────────────────────────


def _read_env(key: str) -> str:
    # VAULT D'ABORD (politique owner 2026-08-19 : tous les clients par le coffre,
    # les secrets ne vivent plus dans l'env ni Nokido.env). Mesure 2026-08-21 :
    # sans cette branche, MISTRAL_API_KEY introuvable -> 50/50 llm_error en 0.0s,
    # un faux 0% qui ne disait jamais sa cause.
    try:
        import sys as _sys
        _app = str(ROOT / "app")
        if _app not in _sys.path:
            _sys.path.insert(0, _app)
        from nokido_agent.app.forge_secrets import get_secret as _gs
        val = _gs(key)
        if val:
            return val
    except Exception:  # muet-ok : fallback env/Nokido.env ci-dessous
        pass
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
    import urllib.error  # _retry_post attrape urllib.error.HTTPError via cet import

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


_ROUTER_SLOTS = ["openrouter_gpt_oss", "hf_llama"]  # gpt-oss-120b fort ; hf fallback (clés vault)


def _router_call(prompt: str, max_tokens: int = 1024) -> str:
    """Génère via forge_llm_router._call_slot sur slots cloud forts. Clé tirée du vault.
    HumanEval = katas publics bénins → pas de firewall (0 PII/secret). Retry backoff sur 429."""
    import time as _t
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_llm_router import get_router

    r = get_router()
    last = "no slot"
    for name in _ROUTER_SLOTS:
        slot = r._slots.get(name)
        if not slot:
            continue
        for attempt in range(3):
            res = r._call_slot(slot, prompt[:12000], "", max_tokens, 0.0, 60, "code")
            if res.get("ok") and res.get("text"):
                return res["text"].strip()
            last = f"{name}: {res.get('error')}"
            e = (res.get("error") or "").lower()
            if ("ratelimit" in e or "429" in e) and attempt < 2:
                _t.sleep(2.0 * (attempt + 1))
                continue
            break
    return f"[ERR] router cloud KO ({last})"


def _msg_content(d: dict) -> str:
    """Mesure 21/08 : openrouter peut rendre 200 avec content **null** ->
    AttributeError sur .strip() qui devient un faux crash d'escalade."""
    try:
        return (d["choices"][0]["message"].get("content") or "").strip()
    except (KeyError, IndexError, TypeError):
        return ""


def call_llm(prompt: str, provider: str = "mistral") -> str:
    if provider == "router":
        return _router_call(prompt)
    if provider == "mistral":
        key = _read_env("MISTRAL_API_KEY")
        if not key:
            return "[ERR] MISTRAL_API_KEY absent"
        d = _retry_post(
            "https://api.mistral.ai/v1/chat/completions",
            {
                "model": "mistral-small-latest",
                "messages": [{"role": "user", "content": prompt[:6000]}],
                # 1024 : a 512 la REPARATION (fonction + docstring recopiee)
                # sortait TRONQUEE -> 7 'unterminated triple-quoted' (21/08)
                "max_tokens": 1024,
                "temperature": 0.0,
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        return _msg_content(d)

    if provider == "ollama":
        model = _read_env("OLLAMA_MODEL") or "qwen2.5-coder:latest"
        d = _http_post(
            "http://127.0.0.1:11434/api/generate",
            {"model": model, "prompt": prompt[:6000], "stream": False},
            timeout=120,
        )
        return d.get("response", "").strip()

    if provider == "openrouter":
        # Doc RAG watch:openrouter:docs/quickstart (ingeree 21/08) : endpoint
        # OpenAI-compatible. Meme modele que le slot routeur VIVANT
        # openrouter_gpt_oss (grade A au whoami) — appel direct, sans litellm.
        key = _read_env("OPENROUTER_API_KEY")
        if not key:
            return "[ERR] OPENROUTER_API_KEY absent"
        d = _retry_post(
            "https://openrouter.ai/api/v1/chat/completions",
            {
                # catalogue :free reel du compte (GET /models 21/08) — le
                # 120b:free a disparu ; glm-5.2 = fort en code
                "model": "z-ai/glm-5.2:free",
                "messages": [{"role": "user", "content": prompt[:6000]}],
                "max_tokens": 1024,
                "temperature": 0.0,
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        return _msg_content(d)

    if provider == "groq":
        # Mesure 2026-08-21 : groq etait dans les choices CLI mais PAS implemente
        # ici -> "[ERR] Unknown provider" silencieux. Groq marche tres bien (llama-3.3-70b).
        key = _read_env("GROQ_API_KEY")
        if not key:
            return "[ERR] GROQ_API_KEY absent"
        d = _retry_post(
            "https://api.groq.com/openai/v1/chat/completions",
            {
                # catalogue Groq 2026 (mesure GET /models 21/08)
                "model": "openai/gpt-oss-120b",
                "messages": [{"role": "user", "content": prompt[:6000]}],
                "max_tokens": 1024,
                "temperature": 0.0,
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        return _msg_content(d)

    if provider == "cerebras":
        key = _read_env("CEREBRAS_API_KEY")
        if not key:
            return "[ERR] CEREBRAS_API_KEY absent"
        d = _retry_post(
            "https://api.cerebras.ai/v1/chat/completions",
            {
                # catalogue Cerebras 2026 (mesure GET /models 21/08)
                "model": "gpt-oss-120b",
                "messages": [{"role": "user", "content": prompt[:4000]}],
                "max_tokens": 1024,
                "temperature": 0.0,
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        return _msg_content(d)

    if provider == "nvidia":
        # NVIDIA NIM (build.nvidia.com, free tier, cle vault active -> 07/2027).
        # Catalogue reel du compte (GET /models 21/08) : kimi-k3 = famille
        # moonshot — la cascade varie la FAMILLE (gpt-oss deja couvert par
        # router/groq ; deepseek-v4-flash-0731 = alternative du meme catalogue).
        key = _read_env("NVIDIA_API_KEY")
        if not key:
            return "[ERR] NVIDIA_API_KEY absent"
        d = _retry_post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            {
                "model": "moonshotai/kimi-k3",
                "messages": [{"role": "user", "content": prompt[:6000]}],
                # kimi-k3 recopie la docstring entiere -> 2048 anti-troncature ;
                # latence MESUREE 76,5s sur HumanEval/0 -> timeout 180 (le 90
                # transformait la variance en llm_error au smoke)
                "max_tokens": 2048,
                "temperature": 0.0,
            },
            headers={"Authorization": f"Bearer {key}"},
            timeout=180,
        )
        return _msg_content(d)

    return f"[ERR] Unknown provider: {provider}"


# ── Code extraction ───────────────────────────────────────────────────────────


def _extract_code(response: str, entry: dict) -> str:
    """Extract function body, normalize to 4-space base indent."""
    text = response.strip()

    # Strip markdown fences
    if "```" in text:
        blocks = re.findall(r"```(?:python)?\n?(.*?)```", text, re.DOTALL)
        if blocks:
            text = blocks[0].strip()

    fn_name = entry["entry_point"]
    lines = text.splitlines()

    # Collect lines after the def signature line
    body_lines = []
    found_def = False
    for line in lines:
        if re.match(rf"\s*def\s+{re.escape(fn_name)}\s*\(", line):
            found_def = True
            continue
        if found_def:
            # Stop at next top-level def/class
            if body_lines and line.strip() and not line[0].isspace():
                break
            body_lines.append(line)

    if not body_lines:
        body_lines = lines  # fallback: treat whole response as body

    # Trim trailing blank lines
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()

    if not body_lines:
        return "    pass"

    non_empty = [l for l in body_lines if l.strip()]
    if not non_empty:
        return "    pass"

    # Detect indent unit (GCD of all indents >= 2), default 4
    from functools import reduce
    from math import gcd

    raw_indents = [len(l) - len(l.lstrip()) for l in non_empty]
    unit_candidates = [i for i in raw_indents if i >= 2]
    unit = reduce(gcd, unit_candidates) if unit_candidates else 4
    if unit < 2:
        unit = 4

    # Snap each line's indent to the nearest multiple of unit.
    # Non-zero indents snap to at least `unit` (avoids rounding 1→0).
    def _snap(indent: int) -> int:
        s = round(indent / unit) * unit
        return max(unit, s) if indent > 0 else 0

    snapped = [_snap(len(l) - len(l.lstrip())) for l in non_empty]
    min_snapped = min(snapped) if snapped else 0

    result = []
    for line in body_lines:
        if not line.strip():
            result.append("")
        else:
            raw_ind = len(line) - len(line.lstrip())
            s = _snap(raw_ind)
            target = 4 + (s - min_snapped)
            result.append(" " * target + line.lstrip())

    return "\n".join(result)


def _compiles(entry: dict, code_body: str) -> bool:
    """Refus d'adoption d'un candidat qui ne compile pas (mesure 21/08 : 7
    reparations tronquees ont remplace du code sain par des SyntaxError
    'unterminated triple-quoted string' — l'original devait rester)."""
    try:
        compile(f"{entry['prompt']}{code_body}\n", "<cand>", "exec")
        return True
    except SyntaxError:
        return False


def _run_capped(cmd: list, timeout: int, rss_cap_mb: int = 1500):
    """subprocess.run + CAP RSS. Mesure 21/08 : un code genere (entree ~44) a
    alloue 11 Go en 90 s dans le test — le timeout seul ne protege pas d'un
    malloc fou, et la detresse RAM fait tuer le RUN ENTIER par la regulation.
    Retourne un objet a la CompletedProcess (returncode/stdout/stderr) ;
    leve subprocess.TimeoutExpired comme subprocess.run."""
    try:
        import psutil as _ps
    except Exception:  # muet-ok : sans psutil on retombe sur timeout seul
        _ps = None
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    t0 = time.time()
    killed_mem = False
    while proc.poll() is None:
        if time.time() - t0 > timeout:
            proc.kill()
            try:
                proc.communicate(timeout=5)
            except Exception:  # muet-ok : kill fait, nettoyage best-effort
                pass
            raise subprocess.TimeoutExpired(cmd, timeout)
        if _ps is not None:
            try:
                if _ps.Process(proc.pid).memory_info().rss > rss_cap_mb * 1024 * 1024:
                    proc.kill()
                    killed_mem = True
                    break
            except Exception:  # muet-ok : process fini entre poll et mesure
                pass
        time.sleep(0.25)
    out, err = proc.communicate()
    rc = 1 if killed_mem else proc.returncode
    if killed_mem:
        err = "MemoryError: rss cap %d MB depasse (test tue)" % rss_cap_mb

    class _R:
        returncode = rc
        stdout = out or ""
        stderr = err or ""
    return _R


# ── Execution sandbox ─────────────────────────────────────────────────────────


def _run_tests(entry: dict, code_body: str, timeout: int = 10) -> tuple[bool, str]:
    """
    Execute generated code + unit tests in a subprocess.
    Returns (passed, reason).
    """
    prompt = entry["prompt"]  # includes signature
    test_code = entry["test"]  # check(candidate) function
    fn_name = entry["entry_point"]

    # Build full script: prompt (signature+docstring) + body + tests + check call
    script = (
        "import sys, math, re, collections, itertools, functools, heapq, bisect\n"
        "from typing import *\n\n"
        f"{prompt}{code_body}\n\n"
        f"{test_code}\n\n"
        f"check({fn_name})\n"
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(script)
        tmp_path = f.name

    try:
        result = _run_capped([LAFORGE_PYTHON, tmp_path], timeout)
        if result.returncode == 0:
            return True, "ok"
        err = (result.stderr or result.stdout or "non-zero exit").strip()
        # Extract last meaningful line
        last_err = [l for l in err.splitlines() if l.strip()][-1] if err else "unknown"
        return False, last_err[:120]
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)[:80]
    finally:
        try:
            Path(tmp_path).unlink()
        except Exception:  # muet-ok: cleanup temp best-effort
            pass


# ── Runner ────────────────────────────────────────────────────────────────────


def _extract_doctests(entry: dict) -> list[str]:
    """Asserts tires des exemples `>>> expr` / resultat de la docstring du PROMPT
    (visibles par tout developpeur -- legitimes, contrairement aux tests caches)."""
    import re as _re
    lines = entry["prompt"].splitlines()
    out = []
    for i, ln in enumerate(lines):
        m = _re.match(r"\s*>>>\s*(.+)$", ln)
        if not m:
            continue
        expr = m.group(1).strip()
        if i + 1 < len(lines):
            exp = lines[i + 1].strip()
            if exp and not exp.startswith(">>>") and not exp.startswith('"""'):
                out.append("assert (%s) == (%s)" % (expr, exp))
    return out[:8]


def _autotest_quarantine() -> set:
    """Tâches dont l'auto-test a déjà menti (vert, éval rouge, 0 réparation).

    Source : tools/autotest_quarantine.json (VERSIONNÉ — RAG/ est gitignoré ;
    fallback RAG/humaneval/ pour les sorties de qualification). Pour ces tâches,
    un auto-test vert est NON CONCLUANT : l'entrée est marquée autotest_untrusted.
    """
    for base in (ROOT / "tools", HE_DIR):
        try:
            q = json.loads((base / "autotest_quarantine.json").read_text(encoding="utf-8"))
            return set(q.get("quarantine", []))
        except Exception:  # muet-ok: emplacement absent, on tente le suivant
            continue
    return set()


def _gen_selftests(entry: dict, provider: str) -> list[str]:
    """Demande au LLM des asserts de test depuis la SPEC seule (jamais la solution).
    C'est le pattern Reflexion : le modele se fabrique son propre harnais."""
    fn = entry["entry_point"]
    p = (
        "Voici la spécification d'une fonction Python (signature + docstring).\n"
        "SANS l'implémenter, écris 4 à 6 lignes `assert %s(...) == ...` qui testent la spec.\n"
        "Réponds UNIQUEMENT par les lignes assert, rien d'autre.\n\n%s"
    ) % (fn, entry["prompt"])
    try:
        resp = call_llm(p, provider)
    except Exception:
        return []
    if resp.startswith("[ERR]"):
        return []
    return [ln.strip() for ln in resp.splitlines()
            if ln.strip().startswith("assert") and fn in ln][:8]


def _run_selftests(entry: dict, code_body: str, asserts: list[str], timeout: int = 10) -> tuple[bool, str]:
    """Execute le code contre les tests AUTO-GENERES (jamais les tests d'eval)."""
    if not asserts:
        return True, "no_selftests"
    script = (
        "import sys, math, re, collections, itertools, functools, heapq, bisect\n"
        "from typing import *\n\n"
        f"{entry['prompt']}{code_body}\n\n" + "\n".join(asserts) + "\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(script)
        tmp = f.name
    try:
        r = _run_capped([LAFORGE_PYTHON, tmp], timeout)
        if r.returncode == 0:
            return True, "ok"
        err = (r.stderr or r.stdout or "non-zero exit").strip()
        last = [l for l in err.splitlines() if l.strip()][-1] if err else "unknown"
        return False, last[:120]
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)[:80]
    finally:
        try:
            Path(tmp).unlink()
        except Exception:  # muet-ok : nettoyage best-effort d'un temporaire
            pass


def _run_identity(quarantine: set, escalate: str) -> dict:
    """Identité de l'évaluateur, embarquée dans chaque JSON de run.

    Un score sans identité exacte de l'évaluateur est INDECIDABLE (verdict
    d'un garde = son compte, mesuré 20/08) : compte, hôte, python, commit,
    quarantaine active et canal d'escalade voyagent avec la mesure.
    Imports locaux : autonome vis-à-vis du header du module.
    """
    import getpass
    import os as _os
    import platform
    import subprocess as _sp
    import sys as _sys

    def _git(args):
        try:
            r = _sp.run(["git", "-c", "safe.directory=*", "-C", str(ROOT)] + args,
                        capture_output=True, text=True, errors="replace", timeout=10)
            return r.stdout.strip(), r.stderr.strip()
        except Exception as e:
            return "", str(e)[:60]

    head, head_err = _git(["rev-parse", "--short=8", "HEAD"])
    dirty, dirty_err = _git(["status", "--porcelain", "--untracked-files=no"])
    commit = head or f"inconnu ({head_err})"
    if dirty:
        commit += "+dirty"
    elif dirty_err:
        commit += "+dirty?"
    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "host": platform.node(),
        "user": getpass.getuser(),
        "python": _sys.version.split()[0],
        "nokido_commit": commit,
        "job_id": _os.environ.get("LAFORGE_JOB_ID"),
        "quarantine_active": sorted(quarantine),
        "escalate_csv": escalate or None,
    }


def run(provider: str = "mistral", max_entries: int = 50, repair: int = 0,
        self_repair: int = 0, escalate: str = "", tag: str = "") -> dict:
    entries = ensure_dataset()
    subset = entries[:max_entries]
    mode = ("self_repair=%d (HONNETE: feedback = doctests + auto-tests, verdict final unique)" % self_repair
            if self_repair else "repair=%d%s" % (repair, " (ORACLE: feedback = tests d'eval)" if repair else ""))
    print(f"[humaneval] {len(subset)} entries | provider={provider} | {mode} | pass@1 STRICT")

    results = []
    t0 = time.time()
    errors = 0
    fail_reasons: dict[str, int] = {}
    _quarantine = _autotest_quarantine()
    if _quarantine:
        print(f"[humaneval] quarantaine auto-tests : {sorted(_quarantine)}")

    # Barre de progression live (dashboard /api/vital/jobs_progress) : best-effort.
    _emit = None
    try:
        from nokido_agent.tools.forge_job_progress import emit as _emit  # noqa: PLC0415
    except Exception:  # muet-ok : la barre est un enrichissement, jamais bloquant
        pass
    _jid = __import__("os").environ.get("LAFORGE_JOB_ID") or f"humaneval_{provider}"

    for i, entry in enumerate(subset):
        if _emit:
            try:
                _emit(_jid, i, len(subset))
            except Exception:  # muet-ok : idem
                pass
        task_id = entry["task_id"]
        prompt = _build_prompt(entry)
        # Reset par itération : sans ça, locals() fuyait les valeurs de la
        # tâche précédente dans les entrées llm_error.
        auto = None
        escalated_to = None
        escalade_errs = None

        t_call = time.time()
        attempts = 0
        try:
            response = call_llm(prompt, provider)
        except Exception as e:
            response = f"[ERR] {e}"

        if response.startswith("[ERR]"):
            passed, reason, code_body = False, "llm_error", ""
            errors += 1
        elif self_repair > 0:
            # Chemin HONNETE : la boucle ne voit QUE les tests auto-generes
            # (doctests de la docstring + asserts LLM ecrits sans la solution).
            code_body = _extract_code(response, entry)
            auto = _extract_doctests(entry) + _gen_selftests(entry, provider)
            sp, sreason = _run_selftests(entry, code_body, auto)
            if sp and task_id in _quarantine:
                print(f"  [quarantine] {task_id}: auto-tests verts NON CONCLUANTS (historique faux-vert)")
            while not sp and attempts < self_repair:
                attempts += 1
                fb = (
                    f"{prompt}\n\n# TA TENTATIVE PRÉCÉDENTE A ÉCHOUÉ à un test ({sreason[:160]}).\n"
                    f"# Code précédent:\n{code_body}\n\n"
                    f"# Renvoie la fonction COMPLÈTE corrigée (def + corps)."
                )
                try:
                    response = call_llm(fb, provider)
                except Exception as e:
                    sreason = f"repair_err: {e}"
                    break
                if response.startswith("[ERR]"):
                    break
                cand = _extract_code(response, entry)
                if not _compiles(entry, cand):
                    sreason = "candidate SyntaxError (non adopte)"
                    continue
                code_body = cand
                sp, sreason = _run_selftests(entry, code_body, auto)
            # ESCALADE multi-modeles (honnete) : si les AUTO-tests echouent encore
            # apres le budget, re-tenter avec CHAQUE provider de la cascade (CSV) --
            # la diversite recupere ce qu'un modele unique rate systematiquement.
            # Decision sur les auto-tests SEULS. Les erreurs de providers sont
            # COLLECTEES (jamais avalees : l'escalade muette du 21/08 a coute une
            # fausse conclusion sur la cascade entiere).
            escalated_to = None
            escalade_errs = []
            if not sp and escalate:
                for esc_prov in [p.strip() for p in escalate.split(",") if p.strip() and p.strip() != provider]:
                    fb = (
                        f"{prompt}\n\n# UNE AUTRE TENTATIVE A ÉCHOUÉ à un test ({sreason[:160]}).\n"
                        f"# Code précédent:\n{code_body}\n\n"
                        f"# Renvoie la fonction COMPLÈTE corrigée (def + corps)."
                    )
                    try:
                        response = call_llm(fb, esc_prov)
                    except Exception as e:
                        escalade_errs.append(f"{esc_prov}: {type(e).__name__} {str(e)[:60]}")
                        continue
                    if response.startswith("[ERR]"):
                        escalade_errs.append(f"{esc_prov}: {response[:80]}")
                        continue
                    cand = _extract_code(response, entry)
                    sp2, sreason2 = _run_selftests(entry, cand, auto)
                    attempts += 1
                    if sp2:
                        code_body, sp, sreason = cand, True, "ok"
                        escalated_to = esc_prov
                        break
                    escalade_errs.append(f"{esc_prov}: autotests {sreason2[:60]}")
                    # NE PAS adopter un candidat non prouve : mesure 21/08, ~30
                    # des 50 escalades partaient d'un AUTO-TEST FAUX (assert LLM
                    # condamnant du code correct) — adopter le candidat remplacait
                    # du bon code par du mauvais (8 nouveaux fails). Sans preuve
                    # (auto-tests verts), l'original reste.
            # VERDICT FINAL : un seul passage sur les tests d'eval, aucun feedback.
            passed, reason = _run_tests(entry, code_body)
            if not passed:
                import re as _re
                _m = _re.search(r"NameError: name '(\w+)' is not defined", reason or "")
                if _m and _m.group(1) in _STDLIB_INJECT:
                    _ind = _re.match(r"\s*", code_body.lstrip("\n")).group(0) or "    "
                    code_body = "%simport %s\n%s" % (_ind, _m.group(1), code_body)
                    passed, reason = _run_tests(entry, code_body)
                    if passed:
                        reason = "ok (stdlib_fix)"
        else:
            code_body = _extract_code(response, entry)
            passed, reason = _run_tests(entry, code_body)
            # Fix deterministe 0-token : import stdlib manquant (NameError).
            # code_body est un CORPS de fonction INDENTE : l'import s'injecte
            # avec l'indentation du corps, jamais en colonne 0 (mesure 21/08 :
            # l'injection col-0 cassait l'indentation -> le fix ne mordait pas).
            if not passed:
                import re as _re
                _m = _re.search(r"NameError: name '(\w+)' is not defined", reason or "")
                if _m and _m.group(1) in _STDLIB_INJECT:
                    _ind = _re.match(r"\s*", code_body.lstrip("\n")).group(0) or "    "
                    code_body = "%simport %s\n%s" % (_ind, _m.group(1), code_body)
                    passed, reason = _run_tests(entry, code_body)
                    if passed:
                        reason = "ok (stdlib_fix)"
            # repair-loop test-feedback : sur échec, régénère avec le message d'erreur
            while not passed and attempts < repair:
                attempts += 1
                fb = (
                    f"{prompt}\n\n# TA TENTATIVE PRÉCÉDENTE A ÉCHOUÉ au test ({reason[:160]}).\n"
                    f"# Code précédent:\n{code_body}\n\n"
                    f"# Renvoie la fonction COMPLÈTE corrigée (def + corps)."
                )
                try:
                    response = call_llm(fb, provider)
                except Exception as e:
                    reason = f"repair_err: {e}"
                    break
                if response.startswith("[ERR]"):
                    break
                cand = _extract_code(response, entry)
                if not _compiles(entry, cand):
                    reason = "candidate SyntaxError (non adopte)"
                    continue
                code_body = cand
                passed, reason = _run_tests(entry, code_body)
        elapsed = round(time.time() - t_call, 2)

        if not passed:
            key = reason.split(":")[0].split("(")[0].strip()[:30]
            fail_reasons[key] = fail_reasons.get(key, 0) + 1

        status = "PASS" if passed else "FAIL"
        detail = f" [{reason[:50]}]" if not passed else ""
        print(f"  [{i + 1}/{len(subset)}] {status} {elapsed}s{detail} | {task_id}")

        results.append(
            {
                "idx": i,
                "task_id": task_id,
                "pass": passed,
                "elapsed_s": elapsed,
                "repairs": attempts,
                "reason": reason if not passed else "ok",
                # GOLDEN SFT : sur PASS, sauve (prompt, solution validée) pour le fine-tune.
                # Eval déterministe subprocess = paire FIABLE (pas de flakiness type Docker).
                "prompt": entry["prompt"] if passed else None,
                "code_body": code_body if passed else None,
                "escalated_to": escalated_to,
                "escalade_errs": escalade_errs or None,
                "autotest_untrusted": task_id in _quarantine,
                "selftests": auto or None,
            }
        )
        time.sleep(0.8)

    # Frame FINAL : la boucle emet AVANT chaque entree -> jamais total/total,
    # et les watchers concluent « fige » sur un run pourtant termine (21/08).
    if _emit:
        try:
            _emit(_jid, len(subset), len(subset))
        except Exception:  # muet-ok
            pass
    elapsed_total = round(time.time() - t0, 1)
    passed_n = sum(1 for r in results if r["pass"])
    pass_rate = round(passed_n / len(results) * 100, 1) if results else 0.0

    repaired_fixed = sum(1 for r in results if r["pass"] and r.get("repairs", 0) > 0)
    summary = {
        "run_identity": _run_identity(_quarantine, escalate),
        "provider": provider,
        "n_total": len(subset),
        "passed": passed_n,
        "pass_rate": pass_rate,
        "repair_budget": repair,
        "self_repair_budget": self_repair,
        "repaired_fixed": repaired_fixed,
        "errors": errors,
        "elapsed_s": elapsed_total,
        "fail_reasons": fail_reasons,
        "results": results,
    }

    suffix = ("_sr%d" % self_repair) if self_repair else (("_r%d" % repair) if repair else "")
    # Nom UNIQUE par run : le 21/08 un run d'escalade fautif a ECRASE le JSON
    # du 91,5 % (meme nom) — la preuve publiee n'existait plus sur disque.
    stamp = tag or time.strftime("%Y%m%d-%H%M")
    HE_DIR.mkdir(parents=True, exist_ok=True)
    out = HE_DIR / f"humaneval_{provider}_{len(subset)}{suffix}_{stamp}.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    print(f"\n{'=' * 50}")
    print(f"HUMANEVAL pass@1 : {pass_rate}%  ({passed_n}/{len(subset)})")
    if repair:
        print(f"Repair-loop      : +{repaired_fixed} corrigés par feedback (budget {repair})")
    print(f"Errors           : {errors}")
    print(f"Avg latency      : {round(sum(r['elapsed_s'] for r in results) / len(results), 2)}s")
    if fail_reasons:
        print(f"Fail breakdown   : {dict(sorted(fail_reasons.items(), key=lambda x: -x[1]))}")
    print(f"Saved -> {out}")

    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_self_correction import anchor_solution

        anchor_solution(
            problem=f"HumanEval benchmark — {len(subset)} entries, pass@1",
            solution=f"pass_rate={pass_rate}% provider={provider} errors={errors} fails={fail_reasons}",
            example=f"python tools/forge_humaneval_runner.py --provider {provider} --max {len(subset)}",
            domain="systeme",
        )
    except Exception as e:
        print(f"[humaneval] anchor_solution non persiste ({e})")

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--provider", default="mistral",
        choices=["mistral", "ollama", "cerebras", "groq", "openrouter", "router", "nvidia"],
        help="router = gpt-oss-120b cloud via forge_llm_router (clé vault)",
    )
    parser.add_argument("--max", type=int, default=50)
    parser.add_argument("--repair", type=int, default=0, help="budget repair-loop test-feedback sur échec (ORACLE: tests d'eval)")
    parser.add_argument("--self-repair", type=int, default=0, dest="self_repair",
                        help="budget repair HONNETE : feedback = doctests + auto-tests (jamais les tests d'eval)")
    parser.add_argument("--escalate", default="",
                        help="provider de secours (ex: router) si les AUTO-tests echouent apres budget -- cascade honnete")
    parser.add_argument("--tag", default="",
                        help="suffixe du JSON de sortie (defaut: horodatage — jamais ecraser un resultat)")
    args = parser.parse_args()
    run(provider=args.provider, max_entries=args.max, repair=args.repair,
        self_repair=args.self_repair, escalate=args.escalate, tag=args.tag)

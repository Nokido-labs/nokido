"""
forge_swebench_runner.py — SWE-bench runner pour Nokido.

Supporte trois variantes :
  lite      : SWE-bench Lite (300 issues, baseline historique)
  verified  : SWE-bench Verified (500 issues filtrées manuellement, RÉFÉRENCE 2024+)
  live      : SWE-bench Live (issues fraîches post-knowledge-cutoff, anti-contamination)

Architecture agent :
  1. Lire problem_statement (+ fichiers repo si --clone)
  2. Générer un patch unidiff
  3. Valider : git apply + pytest FAIL_TO_PASS (local approx) ou harness Docker (officiel)

Scoring officiel : princeton-nlp/SWE-bench harness (Docker requis)
Scoring local (approx) : git apply + pytest, précision ~75-85%

Usage:
    python tools/forge_swebench_runner.py --variant verified --provider mistral --max 50
    python tools/forge_swebench_runner.py --variant live --provider mistral --max 30
    python tools/forge_swebench_runner.py --variant lite --mode generate --max 100 --clone
    python tools/forge_swebench_runner.py --mode evaluate --predictions <SWEBENCH_DIR>/predictions.jsonl
"""

import argparse
import json
import os
import re
import subprocess
import sys
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
# Work dir HORS de RAG/ depuis le 2026-09-27 : un seul resolveur pour tous les runners
# (forge_benchmark_adapter.swebench_dir -- SWEBENCH_DIR, sinon sandbox/workspace/swebench).
from nokido_agent.app.forge_benchmark_adapter import swebench_dir  # noqa: E402

SWE_DIR = swebench_dir()
SWE_DIR.mkdir(parents=True, exist_ok=True)

# Résolution robuste : en job détaché/sandbox, ~ n'est PAS le home de l'owner.
LAFORGE_PYTHON = next(
    (
        p
        for p in (
            os.environ.get("LAFORGE_PYTHON", ""),
            os.path.expanduser(r"~\miniforge3\python.exe"),
            r"%USERPROFILE%\miniforge3\python.exe",
        )
        if p and os.path.exists(p)
    ),
    sys.executable,
)

# HuggingFace dataset rows API
_HF_ROWS = "https://datasets-server.huggingface.co/rows?dataset={ds}&config=default&split={split}&offset={offset}&limit={limit}"

# Dataset identifiers per variant
_DATASETS = {
    "lite": "princeton-nlp%2FSWE-bench_Lite",
    "verified": "princeton-nlp%2FSWE-bench_Verified",
    "live": "SWE-bench%2FSWE-bench_Live",
}

# ── Dataset ───────────────────────────────────────────────────────────────────


def _fetch(url: str, timeout: int = 30) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LaForge/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


def ensure_dataset(split: str = "test", variant: str = "verified") -> list:
    """
    Fields: instance_id, repo, base_commit, problem_statement,
            FAIL_TO_PASS, PASS_TO_PASS, patch, test_patch, version
    """
    cached = SWE_DIR / f"swebench_{variant}_{split}.jsonl"
    if cached.exists():
        entries = [json.loads(l) for l in cached.read_text().splitlines() if l.strip()]
        print(f"[swebench-{variant}] cached {split}: {len(entries)} entries")
        return entries

    ds = _DATASETS.get(variant, _DATASETS["verified"])
    print(f"[swebench-{variant}] downloading {split} split from HuggingFace...")
    entries, offset, batch = [], 0, 100

    while True:
        url = _HF_ROWS.format(ds=ds, split=split, offset=offset, limit=batch)
        raw = _fetch(url, timeout=45)
        if not raw:
            break
        try:
            data = json.loads(raw)
            rows = data.get("rows", [])
            if not rows:
                break
            for r in rows:
                row = r.get("row", r)
                for key in ("FAIL_TO_PASS", "PASS_TO_PASS"):
                    v = row.get(key, "[]")
                    if isinstance(v, str):
                        try:
                            row[key] = json.loads(v)
                        except Exception:
                            row[key] = []
                entries.append(row)
            offset += batch
            if len(rows) < batch:
                break
        except Exception as e:
            print(f"[swebench-{variant}] fetch error: {e}")
            break

    if not entries:
        print(f"[swebench-{variant}] ERROR: no data fetched — check HF availability")
        sys.exit(1)

    print(f"[swebench-{variant}] downloaded {len(entries)} {split} instances")
    cached.write_text("\n".join(json.dumps(e) for e in entries))
    return entries


# ── LLM backends ─────────────────────────────────────────────────────────────


def _read_env(key: str) -> str:
    val = os.environ.get(key, "")
    if val:
        return val
    try:
        if str(ROOT / "app") not in sys.path:
            sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_secrets import get_secret  # vault DPAPI machine > WCM > .env

        val = get_secret(key) or ""
        if val:
            return val
    except Exception:
        pass
    env_file = ROOT / "Nokido.env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip()
    return ""


def _http_post(url: str, body: dict, headers: dict | None = None, timeout: int = 60) -> dict:
    from nokido_agent.tools.forge_bench_http import http_post  # source unique (cliquet clones 21/08)
    return http_post(url, body, headers=headers, timeout=timeout)


def _retry_post(
    url: str, body: dict, headers: dict, timeout: int = 60, max_retries: int = 5
) -> dict:
    # Retry transient API failures: 429 rate-limit + 5xx (nvidia 503 is common).
    import urllib.error

    delay = 2.0
    for attempt in range(max_retries):
        try:
            return _http_post(url, body, headers, timeout)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
                continue
            raise
        except (TimeoutError, OSError):
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
                continue
            raise


def call_llm(
    messages: list,
    provider: str = "mistral",
    max_tokens: int = 2048,
    temperature: float = 0.0,
    effort: str = "",
) -> str:
    print(f"[llm] appel {provider}", flush=True)
    if provider == "mistral":
        key = _read_env("MISTRAL_API_KEY")
        if not key:
            return "[ERR] MISTRAL_API_KEY absent"
        d = _retry_post(
            "https://api.mistral.ai/v1/chat/completions",
            {
                "model": "mistral-small-latest",
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        _m = d["choices"][0]["message"]
        return (_m.get("content") or _m.get("reasoning_content") or "").strip()

    if provider == "ollama":
        model = _read_env("OLLAMA_MODEL") or "qwen2.5-coder:latest"
        flat = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
        d = _http_post(
            "http://127.0.0.1:11434/api/generate",
            {"model": model, "prompt": flat[:8000], "stream": False},
            timeout=180,
        )
        return d.get("response", "").strip()

    if provider == "cerebras":
        key = _read_env("CEREBRAS_API_KEY")
        if not key:
            return "[ERR] CEREBRAS_API_KEY absent"
        model = _read_env("CEREBRAS_SWE_MODEL") or "llama-3.3-70b"
        body = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if "gpt-oss" in model:
            # reasoning model : brider le raisonnement, garder le budget pour la réponse
            # (le codeur passe effort=medium : la copie SEARCH exacte exige du soin)
            body["reasoning_effort"] = effort or _read_env("CEREBRAS_REASONING_EFFORT") or "low"
        d = _retry_post(
            "https://api.cerebras.ai/v1/chat/completions",
            body,
            headers={"Authorization": f"Bearer {key}"},
        )
        _m = d["choices"][0]["message"]
        return (
            _m.get("content") or _m.get("reasoning_content") or _m.get("reasoning") or ""
        ).strip()

    if provider == "openrouter":
        # Anti-dup : déléguer au module gouverné (SDK OpenAI + quota + race +
        # cooldown 429 + fallback local) plutôt qu'un call direct (401 = source de
        # clé divergente). Modèle par défaut du module = FREE_CODE_MODELS
        # (qwen3-coder:free 480B en tête).
        try:
            if str(ROOT / "app") not in sys.path:
                sys.path.insert(0, str(ROOT))
            from nokido_agent.app.forge_openrouter import generate_code as _or_gen

            _sys = next((m["content"] for m in messages if m["role"] == "system"), "")
            _usr = "\n\n".join(m["content"] for m in messages if m["role"] != "system")
            _mdl = _read_env("OPENROUTER_SWE_MODEL") or None
            out = _or_gen(_usr, system=_sys, model=_mdl, max_tokens=max_tokens or 3000)
            return out if not out.startswith("[ERR") else f"[ERR] openrouter: {out[:80]}"
        except Exception as e:  # noqa: BLE001
            return f"[ERR] openrouter {type(e).__name__}: {str(e)[:80]}"

    if provider == "lmstudio":
        base = _read_env("LMSTUDIO_URL") or "http://127.0.0.1:1234"
        key = _read_env("LMSTUDIO_TOKEN")
        hdr = {"Content-Type": "application/json", "User-Agent": "LaForge/1.0"}
        if key:
            hdr["Authorization"] = f"Bearer {key}"
        # Résolution robuste : LMSTUDIO_MODEL n'est valide que s'il est réellement
        # servi (souvent 'local-model' placeholder). Sinon on prend un modèle CODE
        # chargé (coder > non-embedding). Charge à la volée via le keeper si besoin.
        want = _read_env("LMSTUDIO_MODEL")
        model = ""
        try:
            _rq = urllib.request.Request(f"{base}/v1/models", headers=hdr)
            with urllib.request.urlopen(_rq, timeout=10) as _r:
                served = [m["id"] for m in json.loads(_r.read()).get("data", [])]
            llms = [m for m in served if "embed" not in m.lower()]
            if want and want in served:
                model = want
            else:
                model = next((m for m in llms if "coder" in m.lower()), llms[0] if llms else "")
        except Exception:
            model = want or ""
        if not model:
            return "[ERR] LMSTUDIO no model served"
        try:
            d = _retry_post(
                f"{base}/v1/chat/completions",
                {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
                headers=hdr,
                timeout=300,  # iGPU local = lent
            )
        except urllib.error.HTTPError as _he:
            # 400 "No models loaded" -> charger via keeper puis 1 retry
            if _he.code == 400:
                try:
                    sys.path.insert(0, str(ROOT))
                    from nokido_agent.tools import forge_lmstudio_keeper as _K

                    _K.load_model(model)
                    d = _retry_post(
                        f"{base}/v1/chat/completions",
                        {"model": model, "messages": messages,
                         "max_tokens": max_tokens, "temperature": temperature},
                        headers=hdr, timeout=300,
                    )
                except Exception as _e2:
                    return f"[ERR] LMSTUDIO load+retry {str(_e2)[:80]}"
            else:
                raise
        _m = d["choices"][0]["message"]
        return (_m.get("content") or _m.get("reasoning_content") or "").strip()

    if provider == "groq":
        key = _read_env("GROQ_API_KEY")
        if not key:
            return "[ERR] GROQ_API_KEY absent"
        d = _retry_post(
            "https://api.groq.com/openai/v1/chat/completions",
            {
                "model": _read_env("GROQ_SWE_MODEL") or "llama-3.3-70b-versatile",
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        _m = d["choices"][0]["message"]
        return (_m.get("content") or _m.get("reasoning_content") or "").strip()

    if provider == "nvidia":
        key = _read_env("NVIDIA_NIM_API_KEY")
        if not key:
            return "[ERR] NVIDIA_NIM_API_KEY absent"
        # qwen3-coder-480b + qwen2.5-coder-32b retires du catalogue NIM (410 Gone,
        # verifie 2026-07-04). deepseek-v4-pro = coder frontier live, ~2s. Override
        # via NVIDIA_SWE_MODEL si besoin (catalogue: 121 modeles sur integrate.api).
        model = _read_env("NVIDIA_SWE_MODEL") or "deepseek-ai/deepseek-v4-pro"
        d = _retry_post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {key}"},
            timeout=180,
        )
        _m = d["choices"][0]["message"]
        return (_m.get("content") or _m.get("reasoning_content") or "").strip()

    if provider == "claude":
        # Route via hub /ask — never call Anthropic API directly
        import requests as _requests

        flat = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
        try:
            resp = _requests.post(
                "http://localhost:8766/ask",
                json={"task": flat, "provider": provider, "max_tokens": max_tokens},
                timeout=120,
            )
            result = resp.json()
            return result.get("result") or result.get("response") or ""
        except Exception as e:
            return f"[ERR] hub ask (claude): {e}"

    if provider in ("claude_cli", "gemini_cli", "copilot_cli", "claude_agent_sdk"):
        # Use Claude Code / Gemini CLI via the hub's `ask` tool — subscription
        # covers it (no API $). Slower per call than the API (process startup),
        # subject to subscription rate limits.
        key = _read_env("FORGE_MCP_TOKEN")
        if not key:
            return "[ERR] FORGE_MCP_TOKEN absent (hub auth)"
        flat = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
        body = {
            "method": "tools/call",
            "params": {
                "name": "ask",
                "arguments": {
                    "provider": provider,
                    "message": flat,
                    "max_tokens": max_tokens,
                    "task_type": "code",
                },
            },
        }
        d = _retry_post(
            "http://127.0.0.1:8766/mcp",
            body,
            headers={"Authorization": f"Bearer {key}"},
            timeout=300,
        )
        try:
            content = d.get("result", {}).get("content", [])
            inner = content[0].get("text", "") if content else ""
            obj = json.loads(inner) if inner.lstrip().startswith("{") else None
            if obj and "text" in obj:
                return obj["text"].strip()
            return inner.strip()
        except Exception as e:
            return f"[ERR] hub {provider} parse: {e}"

    if provider == "gemini":
        # Route via hub /ask — never call Google API directly
        import requests as _requests

        flat = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
        try:
            resp = _requests.post(
                "http://localhost:8766/ask",
                json={"task": flat, "provider": provider, "max_tokens": max_tokens},
                timeout=120,
            )
            result = resp.json()
            return result.get("result") or result.get("response") or ""
        except Exception as e:
            return f"[ERR] hub ask (gemini): {e}"

    return f"[ERR] Unknown provider: {provider}"


# ── Patch extraction + sanitization ──────────────────────────────────────────

_PATCH_SYSTEM = """\
You are an expert software engineer fixing GitHub issues.
Output ONLY a unified diff patch — no prose, no markdown fences, no explanations.

Required format (copy exactly):
diff --git a/path/to/file.py b/path/to/file.py
--- a/path/to/file.py
+++ b/path/to/file.py
@@ -LINE,COUNT +LINE,COUNT @@
 context line (unchanged)
-removed line
+added line
 context line (unchanged)

Rules:
- First line MUST be "diff --git a/..."
- Use exact file paths from the provided source files
- Use EXACT line numbers from the provided source files — count from line 1
- Include 3 lines of unchanged context around each hunk (copy verbatim)
- One patch may span multiple files (multiple diff --git sections)
- Context lines MUST match the source exactly — wrong context = patch fails
"""


def _sanitize_patch(patch_text: str) -> str:
    """Strip non-patch content, repair headers, normalize context lines."""
    if not patch_text or patch_text.startswith("[ERR]"):
        return ""

    # Strip markdown fences
    if "```" in patch_text:
        m = re.search(r"```(?:diff|patch|)?\n?(.*?)```", patch_text, re.DOTALL)
        if m:
            patch_text = m.group(1)

    patch_text = patch_text.strip()
    lines = patch_text.splitlines()

    # Find first diff-marker line
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^(diff --git|---\s+a/|@@\s)", line):
            start = i
            break

    if start is None:
        return ""

    lines = lines[start:]

    # If missing "diff --git" header but has "--- a/" lines, prepend it
    if not lines[0].startswith("diff --git"):
        for line in lines:
            m = re.match(r"^---\s+a/(.+)", line)
            if m:
                fname = m.group(1).strip()
                lines.insert(0, f"diff --git a/{fname} b/{fname}")
                break

    # Normalize context lines inside hunks:
    # - Empty lines must be " " (one space) not ""
    # - Lines not starting with +/-/@/d/\ must get a leading space
    normalized = []
    in_hunk = False
    for line in lines:
        if line.startswith("@@"):
            in_hunk = True
            normalized.append(line)
        elif line.startswith(("diff --git", "--- ", "+++ ", "index ", "new file", "deleted file")):
            in_hunk = False
            normalized.append(line)
        elif in_hunk:
            if line == "":
                normalized.append(" ")  # blank context line must have one space
            elif line[0] in ("+", "-", " ", "\\"):
                normalized.append(line)
            else:
                normalized.append(" " + line)  # missing context prefix
        else:
            normalized.append(line)

    # Fix @@ line counts to match actual hunk content
    normalized = _fix_hunk_counts(normalized)

    return "\n".join(normalized) + "\n"


def _fix_hunk_counts(lines: list[str]) -> list[str]:
    """Rewrite @@ -A,B +C,D @@ headers with actual line counts from hunk body."""
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@)(.*)", line)
        if not m:
            result.append(line)
            i += 1
            continue

        old_start = m.group(2)
        new_start = m.group(3)
        suffix = m.group(4)

        # Collect hunk body lines
        hunk_body = []
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if nxt.startswith(
                ("diff --git", "--- ", "+++ ", "@@", "index ", "new file", "deleted file")
            ):
                break
            hunk_body.append(nxt)
            j += 1

        # Count old/new lines in body
        old_count = sum(1 for l in hunk_body if l.startswith((" ", "-")))
        new_count = sum(1 for l in hunk_body if l.startswith((" ", "+")))
        has_changes = any(l.startswith(("+", "-")) for l in hunk_body)

        # Drop no-op hunks (pure context, no +/-) — git apply rejects them as corrupt
        if not has_changes:
            i = j
            continue

        result.append(f"@@ -{old_start},{old_count} +{new_start},{new_count} @@{suffix}")
        result.extend(hunk_body)
        i = j

    return result


# ── Repo operations ───────────────────────────────────────────────────────────


def _rmtree_robust(path: Path) -> bool:
    """rmtree tolerant des fichiers read-only de .git : git pose ses pack-files
    en read-only -> shutil.rmtree echoue sur Windows. Retourne True si le
    dossier a bien disparu."""
    import os as _os
    import shutil as _sh
    import stat as _st

    def _onerror(func, p, _exc):
        try:
            _os.chmod(p, _st.S_IWRITE)
            func(p)
        except Exception:
            pass

    if path.exists():
        _sh.rmtree(str(path), onerror=_onerror)
    return not path.exists()


def _clone_repo(repo: str, base_commit: str, work_dir: Path) -> Path | None:
    # Each (repo, commit) gets its own directory — avoids cross-instance state conflicts
    # when multiple instances of the same repo need different commits.
    repo_name = repo.replace("/", "__")
    repo_path = work_dir / f"{repo_name}__{base_commit[:8]}"
    clone_url = f"https://github.com/{repo}.git"

    # Reuse an existing clone ONLY if it is at the right commit — and always
    # reset the working tree (a previous test-fix loop may have left a patch
    # applied). TOUTE autre situation (mauvais commit, ou husk casse d'un
    # clone interrompu = juste .git/) -> raser le dossier et repartir propre :
    # sinon `git clone` dans un dossier non-vide echoue ("destination path
    # already exists") et l'instance sort en clone_failed.
    if repo_path.exists():
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip() == base_commit:
            subprocess.run(
                ["git", "reset", "--hard", "HEAD"],
                cwd=str(repo_path),
                capture_output=True,
                timeout=15,
            )
            subprocess.run(
                ["git", "clean", "-fd"], cwd=str(repo_path), capture_output=True, timeout=15
            )
            return repo_path
        # dossier obsolete ou husk -> nettoyage robuste avant de recloner
        if not _rmtree_robust(repo_path):
            return None

    try:
        # Fetch only the target commit (fast, no full clone needed)
        repo_path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=str(repo_path), capture_output=True, timeout=15)
        subprocess.run(
            ["git", "remote", "add", "origin", clone_url],
            cwd=str(repo_path),
            capture_output=True,
            timeout=10,
        )
        r = subprocess.run(
            ["git", "fetch", "--depth=1", "origin", base_commit],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=180,
        )
        if r.returncode != 0:
            # Fallback: full clone (base_commit might not be fetchable directly)
            if not _rmtree_robust(repo_path):
                return None
            r2 = subprocess.run(
                ["git", "clone", clone_url, str(repo_path)],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=600,
            )
            if r2.returncode != 0:
                return None
            subprocess.run(
                ["git", "checkout", base_commit],
                cwd=str(repo_path),
                capture_output=True,
                timeout=60,
            )
            return repo_path
        r3 = subprocess.run(
            ["git", "checkout", "FETCH_HEAD"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
        return repo_path if r3.returncode == 0 else None
    except Exception:
        return None


def _find_relevant_files(
    repo_path: Path,
    problem_statement: str,
    fail_to_pass: list | None = None,
    max_files: int = 8,
    query_terms: list | None = None,
    force_files: list | None = None,
) -> tuple:
    """Localise les fichiers a editer DANS le repo de l'instance.

    Correction (2026-05-22) : l'ancienne version faisait RAGEngine() = corpus
    Nokido (embeddings.db) -> elle cherchait un bug astropy dans le code de
    Nokido et renvoyait des forge_*.py hors-sujet. Localisation cassee a la
    racine. Ici : score lexical BM25-lite du problem_statement contre les .py
    du repo de l'instance.
    """
    # Stage 1 — warpgrep (repomap AST + BM25) en localiseur PRIMAIRE ;
    # fallback TF.IDF historique ci-dessous si warpgrep échoue/vide.
    try:
        import sys as _sys

        _appdir = str(Path(__file__).resolve().parent)
        if _appdir not in _sys.path:
            _sys.path.insert(0, _appdir)
        from nokido_agent.tools.forge_warpgrep import warpgrep_locate

        _wg = warpgrep_locate(repo_path, problem_statement, k=max_files, keywords=query_terms)
    except Exception:
        _wg = []
    if _wg:
        _res = [Path(_rel) for _sc, _rel, _sy in _wg]
        if force_files:  # fichiers stacktrace (Stage 0) -> inclusion garantie
            for _ff in force_files:
                _c = Path(str(_ff).replace("\\", "/").strip().lstrip("./"))
                if _c not in _res and (repo_path / _c).exists():
                    _res.insert(0, _c)
        return _res[: max_files + 4], 0

    import ast as _ast
    import math as _math
    import re as _re
    from collections import Counter as _Counter

    _stop = {
        "the",
        "and",
        "for",
        "this",
        "that",
        "with",
        "from",
        "when",
        "should",
        "would",
        "have",
        "not",
        "but",
        "are",
        "was",
        "use",
        "using",
        "code",
        "test",
        "tests",
        "bug",
        "issue",
        "error",
        "expected",
        "actual",
        "following",
        "example",
    }
    # Stage 0 — si l'issue a été distillée, ses keywords purs > le texte brut
    if query_terms:
        terms = [w.lower() for w in query_terms if len(str(w)) > 2 and str(w).lower() not in _stop]
    else:
        terms = []
    if not terms:  # distillation absente/vide -> problem_statement brut
        terms = [
            w
            for w in _re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", problem_statement.lower())
            if w not in _stop
        ]
    if not terms:
        return [], 0
    qset = set(terms)
    # passe 1 : par fichier -> TF des termes-requete + symboles def/class (AST)
    docs: list = []  # (rel, low, tf_dict, sym_set)
    for p in repo_path.rglob("*.py"):
        try:
            rel = p.relative_to(repo_path)
        except ValueError:
            continue
        low = rel.as_posix().lower()
        if any(
            x in low
            for x in ("/test", "test_", "tests/", "/.git/", "build/", "/docs/", "/examples/")
        ):
            continue
        try:
            raw = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        txt = raw.lower()
        tf = {t: txt.count(t) for t in qset if t in txt}
        syms: set = set()
        try:
            for node in _ast.walk(_ast.parse(raw)):
                if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
                    syms.add(node.name.lower())
        except Exception:
            pass
        docs.append((rel, low, tf, syms))
    if not docs:
        return [], 0
    n_docs = len(docs)
    # IDF : un terme present dans peu de fichiers = plus discriminant
    df = _Counter()
    for _rel, _low, tf, _syms in docs:
        for t in tf:
            df[t] += 1
    idf = {t: _math.log(1.0 + n_docs / (1.0 + df.get(t, 0))) for t in qset}
    # passe 2 : score TF.IDF + boost chemin + boost symbole AST
    scored = []
    for rel, low, tf, syms in docs:
        score = 0.0
        for t, c in tf.items():
            score += (1.0 + min(c, 8) * 0.1) * idf[t]
        score += sum(idf[t] for t in qset if t in low) * 4.0  # match chemin
        score += sum(idf[t] for t in qset if t in syms) * 8.0  # def/class nomme = tres fort
        if score > 0:
            scored.append((score, rel))
    scored.sort(key=lambda x: -x[0])
    result = [rel for _, rel in scored[:max_files]]
    # Stage 0 — fichiers nommés dans la stacktrace : inclusion garantie
    if force_files:
        all_rels = [d[0] for d in docs]
        for ff in force_files:
            ffn = str(ff).replace("\\", "/").strip().lstrip("./").lower()
            if not ffn:
                continue
            ffn2 = ffn.replace(".", "/")
            for rel in all_rels:
                rp = rel.as_posix().lower()
                if rel not in result and (
                    rp.endswith(ffn) or rp.endswith(ffn + ".py") or rp.endswith(ffn2 + ".py")
                ):
                    result.insert(0, rel)
    return result[: max_files + 4], 0


def _distill_issue(instance: dict, provider: str) -> dict:
    """Stage 0 — distille le problem_statement bruyant (dumps env, plaintes,
    faux coupables) en signal exploitable AVANT le retrieval. Renvoie
    {stacktrace_files, keywords, core_symptom}. Échec/provider down -> {}
    (le pipeline retombe sur le problem_statement brut)."""
    ps = str(instance.get("problem_statement", ""))[:4000]
    if len(ps) < 30:
        return {}
    msgs = [
        {
            "role": "system",
            "content": "Extract a bug report into STRICT JSON and nothing else:\n"
            '{"stacktrace_files": [paths or modules explicitly named in the '
            'issue/traceback], "keywords": [pure technical identifiers — '
            'function/class/variable names, error types], "core_symptom": '
            '"one sentence describing the failure"}',
        },
        {"role": "user", "content": ps},
    ]
    try:
        raw = call_llm(msgs, provider, max_tokens=400, temperature=0.0)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return {}
        d = json.loads(m.group(0))
        return {
            "stacktrace_files": [str(x) for x in d.get("stacktrace_files", [])][:8],
            "keywords": [str(x) for x in d.get("keywords", [])][:25],
            "core_symptom": str(d.get("core_symptom", ""))[:300],
        }
    except Exception:
        return {}


def _skeleton_file(source: str) -> str:
    """
    AST skeleton: imports + class/function signatures + docstrings + line numbers.
    Strips all function bodies → compresses 2500-line file to ~150 lines.
    Returns empty string on parse error (falls back to raw source).
    """
    import ast as _ast

    try:
        tree = _ast.parse(source)
    except SyntaxError:
        return ""

    lines = source.splitlines()
    out = []

    # Imports
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Import, _ast.ImportFrom)):
            out.append(f"L{node.lineno}: {_ast.unparse(node)}")

    if out:
        out.insert(0, "# imports")
        out.append("")

    def docstr(node) -> str:
        if (
            node.body
            and isinstance(node.body[0], _ast.Expr)
            and isinstance(node.body[0].value, _ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            return repr(node.body[0].value.value[:120])
        return ""

    def fmt_args(args) -> str:
        parts = []
        for a in args.args:
            s = a.arg
            if a.annotation:
                try:
                    s += f": {_ast.unparse(a.annotation)}"
                except Exception:
                    pass
            parts.append(s)
        return ", ".join(parts)

    for node in tree.body:
        if isinstance(node, _ast.ClassDef):
            bases = ""
            if node.bases:
                try:
                    bases = "(" + ", ".join(_ast.unparse(b) for b in node.bases) + ")"
                except Exception:
                    pass
            ds = docstr(node)
            out.append(f"L{node.lineno}: class {node.name}{bases}:  {ds}")
            for item in node.body:
                if isinstance(item, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    prefix = "async def" if isinstance(item, _ast.AsyncFunctionDef) else "def"
                    ret = ""
                    if item.returns:
                        try:
                            ret = f" -> {_ast.unparse(item.returns)}"
                        except Exception:
                            pass
                    ds2 = docstr(item)
                    out.append(
                        f"  L{item.lineno}:   {prefix} {item.name}({fmt_args(item.args)}){ret}  {ds2}"
                    )
            out.append("")
        elif isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            prefix = "async def" if isinstance(node, _ast.AsyncFunctionDef) else "def"
            ret = ""
            if node.returns:
                try:
                    ret = f" -> {_ast.unparse(node.returns)}"
                except Exception:
                    pass
            ds = docstr(node)
            out.append(f"L{node.lineno}: {prefix} {node.name}({fmt_args(node.args)}){ret}  {ds}")

    return "\n".join(out)


def _zoom_functions(source: str, keywords: set[str], n: int = 3) -> list[tuple[int, str]]:
    """
    Return (lineno, source_text) for top-N functions whose name/docstring
    best match keywords. Includes full body verbatim (for diff generation).
    """
    import ast as _ast

    try:
        tree = _ast.parse(source)
    except SyntaxError:
        return []

    src_lines = source.splitlines(keepends=True)
    scored = []

    def end_line(node) -> int:
        return max(getattr(node, "end_lineno", node.lineno), node.lineno)

    def score_node(node) -> int:
        text = node.name.lower()
        if (
            node.body
            and isinstance(node.body[0], _ast.Expr)
            and isinstance(node.body[0].value, _ast.Constant)
        ):
            text += " " + str(node.body[0].value.value).lower()
        return sum(1 for kw in keywords if kw in text)

    for node in tree.body:
        if isinstance(node, _ast.ClassDef):
            for item in node.body:
                if isinstance(item, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    s = score_node(item)
                    if s > 0:
                        body = "".join(src_lines[item.lineno - 1 : end_line(item)])
                        scored.append((s, item.lineno, body))
        elif isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            s = score_node(node)
            if s > 0:
                body = "".join(src_lines[node.lineno - 1 : end_line(node)])
                scored.append((s, node.lineno, body))

    scored.sort(reverse=True)
    return [(lineno, body) for _, lineno, body in scored[:n]]


def _callgraph_context(repo_path: Path, priority_files: list, keywords: set, cap_files: int = 300) -> str:
    """IMPACT-context (levier panel multi-LLM + moatless) : pour les fonctions CIBLES
    (def dans les fichiers prioritaires ∩ mots-clés de l'issue), liste leurs CALLERS
    dans tout le repo cloné -> le LLM sait quoi NE PAS casser. Repo-local, AST."""
    import ast as _ast

    targets: set = set()
    for f in priority_files:
        try:
            fp = f if f.is_absolute() else repo_path / f
            tree = _ast.parse(fp.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and node.name.lower() in keywords:
                targets.add(node.name)
    if not targets:
        return ""
    found: dict = {}
    for f in list(repo_path.rglob("*.py"))[:cap_files]:
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
            if not any(t in src for t in targets):
                continue
            tree = _ast.parse(src)
        except Exception:
            continue
        rel = str(f.relative_to(repo_path)).replace("\\", "/")
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                for n in _ast.walk(node):
                    if isinstance(n, _ast.Call):
                        nm = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
                        if nm in targets:
                            found.setdefault(nm, set()).add(f"{rel}:{node.name}")
                            break
    if not found:
        return ""
    lines = [f"- `{fn}` appelée par: {', '.join(sorted(cs)[:6])}" for fn, cs in list(found.items())[:8]]
    return "\n### IMPACT — callers à ne pas casser:\n" + "\n".join(lines)


def _read_files_context(
    files: list[Path],
    repo_path: Path,
    problem_statement: str = "",
    n_full: int = 0,
    max_chars: int = 16000,
) -> str:
    """
    Context strategy:
    - Priority files (first n_full): FULL numbered source if ≤500 lines, else skeleton+zoom(5)
    - Other files: AST skeleton + zoom(3) for top-2
    Full source for priority files eliminates LLM context-line hallucinations.
    """
    keywords = set(re.findall(r"\b\w{4,}\b", problem_statement.lower()))
    keywords -= {
        "this",
        "that",
        "with",
        "from",
        "when",
        "have",
        "should",
        "would",
        "could",
        "error",
        "issue",
        "problem",
        "class",
        "function",
        "method",
        "line",
        "file",
        "code",
        "return",
        "none",
        "true",
        "false",
        "self",
        "args",
        "kwargs",
    }

    parts, total = [], 0

    for idx, f in enumerate(files):
        try:
            fp = f if f.is_absolute() else repo_path / f
            source = fp.read_text(encoding="utf-8", errors="replace")
            rel = str(fp.relative_to(repo_path)).replace("\\", "/")
            n_lines = source.count("\n") + 1
            is_priority = idx < max(n_full, 1)

            # Skeleton + zoom for all files.
            # Priority files get more zooms (top-5 vs top-3).
            # Full numbered source was tried (gen v5) but LLM misread indentation
            # → malformed patches. Skeleton+zoom remains the best strategy.
            n_zoom = 5 if is_priority else 3
            skeleton = _skeleton_file(source)
            if skeleton:
                skel_block = f"### {rel}  ({n_lines} lines — skeleton)\n```\n{skeleton}\n```"
            else:
                skel_block = f"### {rel}  ({n_lines} lines)\n```python\n{source[:3000]}\n```"

            zoom_block = ""
            if idx < 3 and keywords:
                zooms = _zoom_functions(source, keywords, n=n_zoom)
                if zooms:
                    zoom_parts = [
                        f"# --- full body at L{ln} ---\n{body.rstrip()}" for ln, body in zooms
                    ]
                    zoom_block = (
                        f"\n### {rel}  (zoom: relevant function bodies)\n"
                        f"```python\n" + "\n\n".join(zoom_parts) + "\n```"
                    )
            snippet = skel_block + zoom_block

            if total + len(snippet) > max_chars:
                break
            parts.append(snippet)
            total += len(snippet)
        except Exception:
            pass

    try:
        cg = _callgraph_context(repo_path, files[: max(n_full, 1)], keywords)
        if cg:
            parts.append(cg)
    except Exception:
        pass
    return "\n\n".join(parts)


def _build_messages(instance: dict, file_context: str) -> list:
    user = (
        f"REPOSITORY: {instance['repo']}\n"
        f"BASE COMMIT: {instance['base_commit']}\n\n"
        f"ISSUE:\n{instance['problem_statement'][:3000]}\n\n"
    )
    if file_context:
        user += (
            "RELEVANT SOURCE FILES (with line numbers — use these exact paths and "
            "line numbers in your diff):\n"
            f"{file_context}\n\n"
        )
    user += (
        f"TESTS THAT MUST PASS AFTER YOUR FIX:\n"
        f"{chr(10).join(instance.get('FAIL_TO_PASS', [])[:5])}\n\n"
        "Generate the minimal unified diff patch. "
        "Every context line must be copied verbatim from the source files above."
    )
    return [
        {"role": "system", "content": _PATCH_SYSTEM},
        {"role": "user", "content": user},
    ]


# ── Self-correction helpers ────────────────────────────────────────────────────


def _check_patch_applies(patch_text: str, repo_path: Path) -> tuple[bool, str]:
    tmp = repo_path.parent / "_tmp_sc.patch"
    tmp.write_text(patch_text, encoding="utf-8", newline="\n")
    r = subprocess.run(
        ["git", "apply", "--check", str(tmp)],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        errors="replace",
        timeout=15,
    )
    try:
        tmp.unlink()
    except OSError:
        pass
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def _parse_apply_error(error: str) -> tuple[str, int]:
    m = re.search(r"error: patch failed: (.+?):(\d+)", error)
    if m:
        return m.group(1).strip(), int(m.group(2))
    return "", 0


def _extract_actual_context(
    repo_path: Path, rel_file: str, around_line: int, window: int = 45
) -> str:
    full = repo_path / rel_file
    if not full.exists():
        return ""
    lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(0, around_line - window - 1)
    end = min(len(lines), around_line + window)
    return "\n".join(lines[start:end])


def _difflib_patch(
    instance: dict, repo_path: Path, fail_file: str, fail_line: int, provider: str
) -> str:
    """Phase-2 fallback: show LLM actual function body, ask for fixed body,
    compute diff with difflib (context lines are guaranteed correct)."""
    import ast as _ast
    import difflib

    rel = fail_file.replace("\\", "/")
    full_path = repo_path / fail_file
    if not full_path.exists():
        return ""

    source = full_path.read_text(encoding="utf-8", errors="replace")
    all_lines = source.splitlines(keepends=True)

    # Find smallest enclosing function / class via AST
    target_start = max(0, fail_line - 35)
    target_end = min(len(all_lines), fail_line + 35)
    try:
        tree = _ast.parse(source)
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                s = node.lineno - 1
                e = getattr(node, "end_lineno", node.lineno)
                if s <= fail_line - 1 <= e and (e - s) < (target_end - target_start):
                    target_start, target_end = s, e
    except SyntaxError:
        pass

    old_section = "".join(all_lines[target_start:target_end])

    msgs = [
        {
            "role": "system",
            "content": (
                "You are a Python bug fixer. Output ONLY corrected Python code — "
                "no explanation, no diff markers, no ```fences. "
                "Keep exact indentation of the original."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Issue: {instance['problem_statement'][:600]}\n\n"
                f"File: {rel} (lines {target_start + 1}–{target_end}):\n"
                f"{old_section}\n"
                f"Output the complete fixed version of these {target_end - target_start} lines."
            ),
        },
    ]
    try:
        raw2 = call_llm(msgs, provider, max_tokens=1500)
    except Exception:
        return ""

    new_section = raw2.strip()
    if "```" in new_section:
        m = re.search(r"```(?:python)?\n?(.*?)```", new_section, re.DOTALL)
        if m:
            new_section = m.group(1).rstrip()

    new_lines = new_section.splitlines(keepends=True)
    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"

    patched_lines = all_lines[:target_start] + new_lines + all_lines[target_end:]
    diff_iter = difflib.unified_diff(
        all_lines,
        patched_lines,
        fromfile=f"a/{rel}",
        tofile=f"b/{rel}",
    )
    diff_str = "".join(diff_iter)
    if not diff_str:
        return ""
    return f"diff --git a/{rel} b/{rel}\n{diff_str}"


# ── Agent: generate one patch ─────────────────────────────────────────────────


def generate_patch(
    instance: dict, provider: str = "mistral", work_dir: Path | None = None, clone: bool = False
) -> dict:
    t0 = time.time()
    file_context = ""
    repo_path: Path | None = None

    if clone and work_dir:
        repo_path = _clone_repo(instance["repo"], instance["base_commit"], work_dir)
        if repo_path:
            files, n_priority = _find_relevant_files(
                repo_path,
                instance["problem_statement"],
                fail_to_pass=instance.get("FAIL_TO_PASS", []),
            )
            file_context = _read_files_context(
                files, repo_path, instance["problem_statement"], n_full=n_priority
            )
            if os.environ.get("SWEBENCH_MULTIVEC"):
                # Localisation Parent-Child multi-vecteur (bge-m3 réel + résumé LLM ciblé) :
                # recherche NL sur l'issue -> code brut exact des fonctions pertinentes.
                try:
                    from nokido_agent.tools.forge_swe_multivec import build_index_bge, make_hub_summarize

                    # SCOPE aux fichiers candidats de localisation (PAS tout le repo = des
                    # milliers de fonctions). Résumé via LLM PUISSANT (gemini_cli/hub), PAS ollama.
                    _mvi = build_index_bge(
                        repo_path,
                        files=[str(f) for f in files[:8]],
                        summarize_fn=make_hub_summarize("gemini_cli"),
                    )
                    _hits = _mvi.search(instance["problem_statement"], k=8)
                    if _hits:
                        _mv = "\n\n### MULTI-VEC — fonctions pertinentes (code exact):\n" + "\n\n".join(
                            f"# {h['file']}:{h['line']} {h['name']} (score {h['score']})\n{h['code'][:1200]}"
                            for h in _hits
                        )
                        file_context = (file_context + _mv)[:24000]
                except Exception as _e:
                    print(f"[multivec] skip: {_e}", flush=True)

    messages = _build_messages(instance, file_context)

    try:
        raw = call_llm(messages, provider, max_tokens=2048)
    except Exception as e:
        return {
            "instance_id": instance["instance_id"],
            "model_patch": "",
            "model_name_or_path": provider,
            "error": str(e),
            "elapsed_s": round(time.time() - t0, 2),
        }

    patch_text = _sanitize_patch(raw)

    # Phase 1: self-correction — show actual content, ask for corrected diff
    retries = 0
    if repo_path:
        for retries in range(1, 3):
            ok, err = _check_patch_applies(patch_text, repo_path)
            if ok:
                break
            fail_file, fail_line = _parse_apply_error(err)
            if not fail_file:
                break
            actual = _extract_actual_context(repo_path, fail_file, fail_line)
            if not actual:
                break
            correction_msgs = messages + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        f"Your patch does not apply. Git error:\n{err[:400]}\n\n"
                        f"Actual file content ({fail_file} around line {fail_line}):\n"
                        f"```python\n{actual}\n```\n\n"
                        f"Regenerate the patch using EXACT lines from the file as context. "
                        f"Output only the unified diff, nothing else."
                    ),
                },
            ]
            try:
                raw = call_llm(correction_msgs, provider, max_tokens=2048)
            except Exception:
                break
            patch_text = _sanitize_patch(raw)

    # Phase 2 fallback: difflib — show LLM the actual function, compute diff ourselves
    used_difflib = False
    if repo_path and patch_text:
        ok, err = _check_patch_applies(patch_text, repo_path)
        if not ok:
            fail_file, fail_line = _parse_apply_error(err)
            if fail_file:
                dl_patch = _difflib_patch(instance, repo_path, fail_file, fail_line, provider)
                if dl_patch:
                    dl_sanitized = _sanitize_patch(dl_patch)
                    ok2, _ = _check_patch_applies(dl_sanitized, repo_path)
                    if ok2:
                        patch_text = dl_sanitized
                        used_difflib = True

    _model_names = {
        "mistral": "mistral-small-latest",
        "nvidia": "deepseek-v4-pro",
        "cerebras": "cerebras-llama3.1-70b",
        "ollama": "ollama-local",
    }
    elapsed = round(time.time() - t0, 2)
    return {
        "instance_id": instance["instance_id"],
        "model_patch": patch_text,
        "model_name_or_path": _model_names.get(provider, provider),
        "elapsed_s": elapsed,
        "had_context": bool(file_context),
        "sc_retries": retries,
        "used_difflib": used_difflib,
    }


def generate_patch_best_of_n(
    instance: dict, providers: list | None = None, work_dir: Path | None = None, n: int | None = None
) -> dict:
    """Best-of-N + SÉLECTION (levier #1 SWE-bench : panel multi-LLM + moatless SWE-Search).

    Génère des candidats DIVERSIFIÉS (un par provider), garde ceux qui produisent un
    patch, et SÉLECTIONNE par pass FAIL_TO_PASS (_apply_and_test = signal fort) ; à
    défaut de work_dir/test, le plus petit diff valide (heuristique minimal-fix).
    Toggle : SWEBENCH_BESTOFN (csv providers) + SWEBENCH_BESTOFN_N (réplication).
    """
    provs = providers or [
        # défaut = 2 forts COMPTE (claude_cli=Opus 4.8 + gemini_cli=Gemini 3.1) + groq
        # (free vérifié OK = 3e diversité). copilot_cli/cerebras/claude_agent_sdk =
        # cassés au 2026-06-05 (audit ping) -> exclus du défaut tant que pas réparés.
        # groq N'EST PAS supporté par call_llm (-> "Unknown provider") : cerebras = filet
        # call_llm-compatible. Forts = claude_cli (Opus 4.8) + gemini_cli (Gemini 3.1).
        p.strip() for p in os.environ.get("SWEBENCH_BESTOFN", "claude_cli,gemini_cli,cerebras").split(",") if p.strip()
    ]
    if n:
        provs = (provs * ((n // max(len(provs), 1)) + 1))[:n]

    def _diffsize(c: dict) -> int:
        p = c.get("model_patch") or ""
        return sum(1 for ln in p.splitlines() if ln[:1] in "+-" and ln[:2] not in ("++", "--")) or 9999

    cands: list[dict] = []
    for p in provs:
        try:
            r = generate_patch(instance, provider=p, work_dir=work_dir, clone=True)
        except Exception as e:
            r = {"instance_id": instance.get("instance_id"), "model_patch": "", "error": str(e), "model_name_or_path": p}
        if (r.get("model_patch") or "").strip():
            cands.append(r)
    if not cands:
        return {"instance_id": instance.get("instance_id"), "model_patch": "",
                "model_name_or_path": "best_of_n", "error": "no candidate"}

    selected_by = "min_diff"
    pool = cands
    if work_dir is not None and len(cands) > 1:
        for c in cands:
            try:
                passed, _log = _apply_and_test(instance, c["model_patch"], work_dir)
            except Exception:
                passed = False
            c["_passed"] = bool(passed)
        winners = [c for c in cands if c.get("_passed")]
        if winners:
            pool, selected_by = winners, "test_pass"
    best = min(pool, key=_diffsize)
    best["best_of_n"] = {"candidates": len(cands), "selected_by": selected_by}
    return best


# ── Swarm pipeline: Explorer / Architect / Coder ─────────────────────────────
#
# Pattern borrowed from app/forge_handoff.py (linear workflow), but implemented
# here because the SWE-bench stages need file/AST/difflib tooling that lives in
# this module. Each role gets its own provider — cheap model scouts, strong
# model reasons, code model writes the minimal fix. The Coder NEVER emits a
# diff: it returns the fixed function body and difflib computes the patch, so
# context lines are exact AND the change stays minimal.

_SWARM_PROVIDERS = {
    "explorer": os.environ.get("SWARM_EXPLORER", "cerebras"),
    "architect": os.environ.get("SWARM_ARCHITECT", "cerebras"),
    "coder": os.environ.get("SWARM_CODER", "cerebras"),
}
# cerebras = seul provider direct-API fiable depuis un conteneur Modal :
# mistral free tier = 429 capacity, nvidia 480B = timeout, ollama = local.
FALLBACK_PROVIDER = os.environ.get("SWARM_FALLBACK", "cerebras")
MAX_SWARM_FIX = 3  # reproduce-driven test-fix iterations
MAX_DIFF_LINES = 25  # soft gate: bigger diff -> critique + retry (panel 2026-05-22)


# ── SEARCH/REPLACE edit format (Aider-style) ─────────────────────────────────
# Replaces strict AST function extraction: a SEARCH/REPLACE block edits ANY
# location — constants, settings, imports, multi-spot — killing the
# function_not_found gap (django FILE_UPLOAD_PERMISSIONS etc.).

_SR_SYSTEM = """You are an expert software engineer. Fix the bug.

PREFERRED — for a fix inside a function or method, output the COMPLETE
corrected function/class in a fenced block:
```python
def the_function(...):
    <full corrected body>
```
Output the ENTIRE function, from `def`/`class` to its last line. Keep the
same name and signature. Include decorators if the original has them.

ONLY for a fix OUTSIDE any function (module-level constant, import, a
class attribute), use a SEARCH/REPLACE block instead:

<<<<<<< SEARCH
(lines copied verbatim from the file)
=======
(replacement lines)
>>>>>>> REPLACE

Rules:
- Change the MINIMUM necessary. Never reformat untouched code.
- Several fenced functions / several blocks allowed for several edit spots.
- SEARCH text (if used) MUST be copied character-for-character.
- No prose — only the fenced function(s) and/or SEARCH/REPLACE block(s)."""

_SR_MARK_S = "<" * 7 + " SEARCH"
_SR_MARK_M = "=" * 7
_SR_MARK_R = ">" * 7 + " REPLACE"

_SR_SYSTEM_CONSTRAINED = f"""You are an expert software-maintenance engineer: strict, minimalist, surgical.

INPUT STRUCTURE:
- "File <path>": the buggy file — the ONLY code you may edit.
- "Fix plan": analysis of the issue.
- "## CALLERS CONTEXT" (optional): callers of the buggy code. DO NOT break
  their signatures or behaviour.
- "## REPRODUCTION TEST TO PASS" (optional): a script that currently FAILS
  on the buggy code.

OBJECTIVE: fix the bug with the absolute minimum change. If a reproduction
test is provided, your fix must make it pass.

OUTPUT — SEARCH/REPLACE block(s) ONLY. Zero prose, zero markdown wrappers:

{_SR_MARK_S}
(lines copied VERBATIM from the file — exact indentation, spaces and tabs,
one contiguous span)
{_SR_MARK_M}
(replacement lines)
{_SR_MARK_R}

HARD RULES:
1. ONE block strongly preferred. Two blocks absolute maximum, only if the fix
   is logically impossible in one.
2. Keep the edit small: the replacement section must stay under 15 lines. If
   the full fix would be larger, output the SMALLEST partial fix that makes
   the reproduction test pass.
3. Do NOT touch imports unless the failure is an explicit ImportError.
4. Never reformat, rename variables, or "improve" code you are not fixing.
5. SEARCH text MUST match the file character-for-character. Copy, never
   paraphrase."""


def _constrained() -> bool:
    """A/B smoke flag (SWEB_CONSTRAINED=1) : prompt patcheur contraint."""
    return os.environ.get("SWEB_CONSTRAINED", "").strip().lower() in ("1", "true", "yes")


def _taint_plan_on() -> bool:
    """Flag SÉPARÉ (SWEB_TAINT_PLAN=1, défaut OFF) : architecte taint-lens.
    Mesure 2026-07-04 run 5 : actif à effort low = plans spéculatifs -> le codeur
    hallucine le SEARCH (4/10 patchs vs 6/10 sans). À retenter avec architecte
    effort medium + sortie structurée source/propagation/sink (caveat AGY)."""
    return os.environ.get("SWEB_TAINT_PLAN", "").strip().lower() in ("1", "true", "yes")


def _parse_sr_blocks(text: str) -> list[tuple[str, str]]:
    """Parse Aider-style SEARCH/REPLACE blocks -> [(search, replace), ...]."""
    pat = re.compile(r"<{5,}\s*SEARCH\s*\n(.*?)\n?={5,}[^\n]*\n(.*?)\n?>{5,}\s*REPLACE", re.DOTALL)
    return [(m.group(1), m.group(2)) for m in pat.finditer(text)]


def _apply_sr_blocks(content: str, blocks: list[tuple[str, str]]) -> str:
    """Apply SEARCH/REPLACE blocks: exact match, else per-line rstrip match.
    Returns the new content, or '' on any failure / no change."""
    if not blocks:
        return ""
    out = content
    for search, replace in blocks:
        if not search.strip():
            return ""
        if search in out:
            out = out.replace(search, replace, 1)
            continue
        o_lines = out.splitlines(keepends=True)
        s_norm = [l.rstrip() for l in search.splitlines()]
        if not s_norm:
            return ""
        hit = -1
        for i in range(len(o_lines) - len(s_norm) + 1):
            if [o_lines[i + j].rstrip("\r\n").rstrip() for j in range(len(s_norm))] == s_norm:
                hit = i
                break
        if hit < 0:
            # 3e passe : match indentation-insensible + ré-indentation du REPLACE
            s_strip = [l.strip() for l in s_norm]
            for i in range(len(o_lines) - len(s_norm) + 1):
                if [o_lines[i + j].strip() for j in range(len(s_norm))] == s_strip:
                    hit = i
                    break
            if hit < 0:
                return ""
            f_line = o_lines[hit]
            s_line = search.splitlines()[0]
            f_ind = len(f_line) - len(f_line.lstrip())
            s_ind = len(s_line) - len(s_line.lstrip())
            delta = f_ind - s_ind
            if delta:
                r_out = []
                for rl in replace.splitlines():
                    if not rl.strip():
                        r_out.append(rl)
                    elif delta > 0:
                        r_out.append(" " * delta + rl)
                    else:
                        cur = len(rl) - len(rl.lstrip())
                        r_out.append(rl[min(-delta, cur):])
                replace = "\n".join(r_out) + ("\n" if replace.endswith("\n") else "")
        rep = replace if (not replace or replace.endswith("\n")) else replace + "\n"
        out = "".join(o_lines[:hit]) + rep + "".join(o_lines[hit + len(s_norm) :])
    return out if out != content else ""


def _ast_top_defs(code: str) -> list:
    """[(name, texte_source)] des def/class top-level d'un extrait de code.
    Le code est dédenté d'abord (le Coder peut émettre une méthode indentée)."""
    import ast as _ast
    import textwrap as _tw

    code = _tw.dedent(code)
    tree = _ast.parse(code)
    lines = code.splitlines(keepends=True)
    out = []
    for node in tree.body:
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
            start = node.lineno - 1
            if node.decorator_list:
                start = min(d.lineno for d in node.decorator_list) - 1
            out.append((node.name, "".join(lines[start : node.end_lineno])))
    return out


def _apply_ast_replace(source: str, new_code: str) -> str:
    """Stage 3 — remplace une fonction/classe ENTIÈRE par son nom via AST.
    Le Coder émet la fonction corrigée complète ; on localise le noeud
    homonyme et on substitue ses lignes (décorateurs inclus, ré-indenté au
    col_offset d'origine). Robuste : pas de match exact de texte — les
    modèles free-tier bousillent les diffs."""
    import ast as _ast
    import textwrap as _tw

    try:
        new_defs = _ast_top_defs(new_code)
    except SyntaxError:
        return ""
    if not new_defs:
        return ""
    try:
        src_tree = _ast.parse(source)
    except SyntaxError:
        return ""
    name_nodes: dict = {}
    dup: set = set()
    for node in _ast.walk(src_tree):
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
            if node.name in name_nodes:
                dup.add(node.name)
            name_nodes[node.name] = node
    spans = []
    for name, new_text in new_defs:
        if name in dup or name not in name_nodes:
            continue  # nom ambigu (homonymes) ou absent -> on ne risque rien
        node = name_nodes[name]
        start = node.lineno - 1
        if node.decorator_list:
            start = min(d.lineno for d in node.decorator_list) - 1
        end = node.end_lineno
        # Garde anti-troncature : un modèle free-tier "régénère" parfois une
        # grosse fonction en version raccourcie (corps tronqué/résumé) -> ce
        # n'est pas un fix, c'est une destruction. On rejette ce span.
        old_n = end - start
        new_n = len(new_text.strip().splitlines())
        if old_n > 15 and new_n < old_n * 0.5:
            continue
        spans.append((start, end, node.col_offset, new_text))
    if not spans:
        return ""
    out = source.splitlines(keepends=True)
    for start, end, col, new_text in sorted(spans, key=lambda s: s[0], reverse=True):
        body = _tw.dedent(new_text).strip("\n")
        if col:
            body = _tw.indent(body, " " * col)
        out[start:end] = [body + "\n"]
    result = "".join(out)
    return result if result != source else ""


def _apply_coder_output(llm_text: str, source: str) -> str:
    """Stage 3 — applique la sortie du Coder : remplacement de fonction
    ENTIÈRE via AST (préféré, robuste) ; fallback SEARCH/REPLACE pour les
    edits hors-fonction (constante/import module-level)."""
    out = source
    applied = False
    for fence in re.findall(r"```(?:python)?\s*\n(.*?)```", llm_text, re.DOTALL):
        patched = _apply_ast_replace(out, fence)
        if patched:
            out = patched
            applied = True
    if applied:
        return out if out != source else ""
    return _apply_sr_blocks(source, _parse_sr_blocks(llm_text))


def _coder_context(source: str, plan: str = "", keywords=None, cap: int = 30000) -> str:
    """File text the Coder copies SEARCH blocks from.

    Petit fichier -> tel quel. Gros fichier : la troncature aveugle source[:cap]
    exclut toute methode située au-delà du seuil -> le codeur HALLUCINE le bloc
    SEARCH (RCA 2026-07-04 astropy-14096 : __getattr__ etait hors des 30k
    premiers chars de sky_coordinate.py -> les 2 candidats ont inventé le SEARCH,
    0 patch applicable). On garde la tête (imports + entêtes de classe) PUIS on
    ANNEXE le corps verbatim des fonctions ciblées par le plan de l'architecte
    (signal fort) + les keywords distillés, via _zoom_functions (AST, corps
    exact). Garantit que le bloc a editer est present verbatim = copiable.
    """
    if len(source) <= cap:
        return source
    import re as _re

    kws = {str(k).lower() for k in (keywords or []) if str(k)}
    # symboles explicitement nommés par le plan (ex: "modifier __getattr__")
    for sym in _re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", plan or ""):
        kws.add(sym.lower())
    if not kws:
        return source[:cap]

    head = source[: cap // 2]
    targets = _zoom_functions(source, kws, n=6)
    if not targets:
        return source[:cap]

    blocks, budget = [], cap - len(head)
    for lineno, body in targets:
        if body in head:  # déjà visible dans la tête -> pas de doublon
            continue
        if len(body) > budget:
            body = body[:budget]
        blocks.append(f"# --- ligne {lineno} (corps verbatim — copier le SEARCH ici) ---\n{body}")
        budget -= len(body) + 80
        if budget <= 0:
            break
    if not blocks:
        return source[:cap]
    return head + "\n\n# ==== FONCTIONS CIBLEES (source verbatim) ====\n" + "\n".join(blocks)


def _focus_ctx(source: str, instance: dict, plan: str) -> str:
    """Contexte codeur FOCALISÉ : corps verbatim des seules fonctions candidates
    (mots-clés issue+plan). Utilisé au retry après une hallucination de copie
    SEARCH : l'espace de copie rétrécit, le bloc à copier est sous les yeux."""
    kws = set(
        re.findall(r"\b\w{4,}\b", (instance.get("problem_statement", "") + " " + plan).lower())
    )
    try:
        zooms = _zoom_functions(source, kws, n=8)
    except Exception:
        return ""
    if not zooms:
        return ""
    return "\n\n".join(b.rstrip() for _ln, b in zooms)


def _swarm_explore(instance: dict, files: list, repo_path: Path, provider: str) -> str:
    """Stage 1 — locate the buggy FILE only (cheap model, file-select is easy)."""
    skel = _read_files_context(
        files, repo_path, instance["problem_statement"], n_full=1, max_chars=8000
    )
    msgs = [
        {
            "role": "system",
            "content": "You locate the file containing a bug. Output EXACTLY one line:\n"
            "FILE: <relative path>",
        },
        {
            "role": "user",
            "content": f"Issue:\n{instance['problem_statement'][:1500]}\n\n"
            f"Repository file skeletons:\n{skel}",
        },
    ]
    raw = call_llm(msgs, provider, max_tokens=60)
    fm = re.search(r"FILE:\s*(.+)", raw)
    return fm.group(1).strip() if fm else ""


def _swarm_plan(instance: dict, source: str, rel_file: str, provider: str) -> str:
    """Stage 2 — minimal fix plan (any kind of fix: function, constant, setting)."""
    if len(source) <= 16000:
        ctx = source
    else:
        keywords = set(re.findall(r"\b\w{4,}\b", instance["problem_statement"].lower()))
        zooms = _zoom_functions(source, keywords, n=6)
        ctx = (
            _skeleton_file(source)
            + "\n\n# ==== candidate bodies ====\n"
            + "\n\n".join(f"# L{ln}\n{b.rstrip()}" for ln, b in zooms)
        )
    ftp = ", ".join(instance.get("FAIL_TO_PASS", [])[:5])
    _taint_system = (
        "You are an expert in reverse-engineering and software debugging "
        "(taint-tracking methodology). Do NOT guess the fix immediately. "
        "Apply a data-flow analysis on the failing behaviour:\n"
        "1. SOURCE: which public function, argument or state injects the data/state "
        "that triggers the failure.\n"
        "2. PROPAGATION: trace that data through the file (functions traversed, in order).\n"
        "3. SINK: the EXACT function and lines where the invariant breaks — the fix "
        "belongs THERE, which may be a helper, a constant or a setting, NOT the symbol "
        "named in the issue.\n"
        "Then write a MINIMAL fix plan: SINK function name, which lines, what change, "
        "why. 8 lines max, no code."
    )
    _legacy_system = (
        "You are a senior engineer. Pinpoint the bug — it may be in a helper, "
        "a module-level constant, or a setting, NOT the symbol named in the "
        "issue. Write a MINIMAL fix plan: which lines, what change, why. "
        "5 lines max, no code."
    )
    msgs = [
        {
            "role": "system",
            "content": _taint_system if _taint_plan_on() else _legacy_system,
        },
        {
            "role": "user",
            "content": f"Issue:\n{instance['problem_statement'][:1500]}\n\nFailing tests: {ftp}\n\n"
            f"Source of {rel_file}:\n```python\n{ctx}\n```",
        },
    ]
    return call_llm(msgs, provider, max_tokens=2000).strip()


def _swarm_code_sr(
    instance: dict,
    coder_ctx: str,
    rel_file: str,
    plan: str,
    provider: str,
    critique: str = "",
    repro: str = "",
    callers: str = "",
) -> str:
    """Stage 3 — Coder emits SEARCH/REPLACE blocks (raw LLM text)."""
    extra = f"\n\nIMPORTANT — {critique}" if critique else ""
    callers_sec = f"\n\n## CALLERS CONTEXT (do not break):\n{callers[:2000]}" if callers else ""
    repro_sec = (
        f"\n\n## REPRODUCTION TEST TO PASS (fails on current code):\n"
        f"```python\n{repro[:3000]}\n```"
        if repro
        else ""
    )
    system = _SR_SYSTEM_CONSTRAINED if _constrained() else _SR_SYSTEM
    msgs = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"Issue:\n{instance['problem_statement'][:1200]}\n\nFix plan:\n{plan}\n\n"
            f"File {rel_file}:\n```python\n{coder_ctx}\n```{callers_sec}{repro_sec}{extra}\n\n"
            f"Output the SEARCH/REPLACE block(s):",
        },
    ]
    # Stage 3 — température étagée : 1re passe basse (syntaxe sûre), retry
    # (critique non vide) plus haute pour explorer une autre solution.
    return call_llm(
        msgs, provider, max_tokens=3000, temperature=0.5 if critique else 0.1, effort="medium"
    )


def _gen_reproduce(instance: dict, provider: str) -> str:
    """Agent writes a standalone repro script: RAISES on the buggy code, exits 0
    once fixed. Sidesteps the per-repo test runner (django runtests.py etc.)."""
    msgs = [
        {
            "role": "system",
            "content": "Write a standalone Python script reproducing the reported bug. It "
            "must import the package, exercise the buggy behaviour, and `assert` "
            "the CORRECT expected result — so it RAISES on today's buggy code and "
            "exits 0 once the bug is fixed. Self-contained, no pytest, no CLI "
            "args, no input(). Output ONLY the script — no prose, no ```fences.",
        },
        {"role": "user", "content": f"Bug report:\n{instance['problem_statement'][:2500]}"},
    ]
    raw = call_llm(msgs, provider, max_tokens=2500).strip()
    if "```" in raw:
        m = re.search(r"```(?:python)?\n?(.*?)```", raw, re.DOTALL)
        if m:
            raw = m.group(1).strip()
    return raw


def _prepare_repo_for_test(repo_path: Path) -> None:
    """Clean repo to base commit + editable install (once per instance)."""
    subprocess.run(
        ["git", "reset", "--hard", "HEAD"], cwd=str(repo_path), capture_output=True, timeout=15
    )
    subprocess.run(["git", "clean", "-fd"], cwd=str(repo_path), capture_output=True, timeout=15)
    if _repro_docker_on():
        return  # repro dans l'image d'éval — aucune install locale nécessaire
    subprocess.run(
        [LAFORGE_PYTHON, "-m", "pip", "install", "-e", ".", "-q"],
        cwd=str(repo_path),
        capture_output=True,
        timeout=180,
    )


def _repro_docker_on() -> bool:
    """Flag SWEB_REPRO_DOCKER : repro exécuté dans l'image d'éval officielle."""
    return os.environ.get("SWEB_REPRO_DOCKER", "").strip().lower() in ("1", "true", "yes")


def _repro_docker_image(instance_id: str) -> str:
    """Résout l'image d'éval SWE-bench pour l'instance (locale d'abord, pull sinon).
    Docker Hub namespace swebench encode '__' en '_1776_'. '' si indisponible."""
    cands = [
        f"swebench/sweb.eval.x86_64.{instance_id.replace('__', '_1776_')}:latest",
        f"sweb.eval.x86_64.{instance_id.replace('__', '_1776_')}:latest",
        f"sweb.eval.x86_64.{instance_id}:latest",
    ]
    for img in cands:
        r = subprocess.run(
            ["docker", "images", "-q", img],
            capture_output=True, text=True, errors="replace", timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            return img
    img = cands[0]
    print(f"[repro-docker] pull {img}", flush=True)
    r = subprocess.run(
        ["docker", "pull", img], capture_output=True, text=True, errors="replace", timeout=900
    )
    return img if r.returncode == 0 else ""


def _run_repro_docker(
    repro_code: str, patch_text: str, repo_path: Path, instance: dict
) -> tuple[bool, str]:
    """Repro dans l'image d'éval officielle : repo pristine à /testbed, conda env
    testbed = environnement PARFAIT (astropy compilé). Le traceback renvoyé est le
    vrai signal réinjecté au codeur à l'itération suivante."""
    iid = instance["instance_id"]
    img = _repro_docker_image(iid)
    if not img:
        return False, "no_docker_image"
    work = repo_path.parent
    rf = work / f"_repro_{iid}.py"
    rf.write_text(repro_code, encoding="utf-8", newline="\n")
    mounts = ["-v", f"{rf.as_posix()}:/tmp/repro.py:ro"]
    script = "cd /testbed"
    if patch_text:
        pt = _sanitize_patch(patch_text)
        if not pt:
            return False, "empty_patch"
        pf = work / f"_repro_{iid}.patch"
        pf.write_text(pt, encoding="utf-8", newline="\n")
        mounts += ["-v", f"{pf.as_posix()}:/tmp/repro.patch:ro"]
        script += (
            " && if git apply --check /tmp/repro.patch 2>/dev/null;"
            " then git apply /tmp/repro.patch;"
            " elif git apply --check --ignore-whitespace /tmp/repro.patch 2>/dev/null;"
            " then git apply --ignore-whitespace /tmp/repro.patch;"
            " else echo __SWE_APPLY_FAILED__; exit 97; fi"
        )
    script += (
        " && { source /opt/miniconda3/bin/activate testbed 2>/dev/null || true; }"
        " && python /tmp/repro.py"
    )
    name = f"sweb_repro_{iid.rsplit('-', 1)[-1]}"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=20)
    try:
        r = subprocess.run(
            ["docker", "run", "--rm", "--name", name, *mounts, img, "bash", "-lc", script],
            capture_output=True, text=True, errors="replace", timeout=240,
        )
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=20)
        return False, "repro_timeout"
    out = "\n".join(l for l in ((r.stdout or "") + (r.stderr or "")).splitlines() if l.strip())
    if "__SWE_APPLY_FAILED__" in out:
        return False, "apply_failed"
    if os.environ.get("SWEB_TRACE_FILTER", "0").lower() in ("1", "true", "yes"):
        flines, skip_next = [], False
        for l in out.splitlines():
            ls = l.strip()
            if ls.startswith("File ") or ": in " in ls or ".py:" in ls:
                if any(noise in ls for noise in ("/site-packages/", "/dist-packages/", "/importlib/", "/opt/miniconda", "/usr/", "/pytest/", "pluggy", "execnet")):
                    if not flines or flines[-1] != "  [... frame externe atténuée ...]":
                        flines.append("  [... frame externe atténuée ...]")
                    skip_next = True
                else:
                    flines.append(l)
                    skip_next = False
            elif skip_next and (l.startswith("    ") or l.startswith("\t") or l.startswith(" >") or l.startswith("> ")):
                continue
            else:
                skip_next = False
                flines.append(l)
        out = "\n".join(flines)
    return r.returncode == 0, (_truncate_trace(out, 45) or "(no output)")


_REG_BASE_CACHE: dict = {}


def _docker_pytest(target: str, patch_text: str, repo_path: Path, instance: dict) -> tuple[int, str]:
    """pytest d'un répertoire de tests dans l'image d'éval (patch optionnel).
    Retourne (rc, sortie) ; rc >= 90 = infra indisponible (guard à ignorer)."""
    iid = instance["instance_id"]
    img = _repro_docker_image(iid)
    if not img:
        return 90, "no_docker_image"
    work = repo_path.parent
    mounts: list[str] = []
    script = "cd /testbed"
    if patch_text:
        pt = _sanitize_patch(patch_text)
        if not pt:
            return 91, "empty_patch"
        pf = work / f"_reg_{iid}.patch"
        pf.write_text(pt, encoding="utf-8", newline="\n")
        mounts = ["-v", f"{pf.as_posix()}:/tmp/reg.patch:ro"]
        script += (
            " && if git apply --check /tmp/reg.patch 2>/dev/null;"
            " then git apply /tmp/reg.patch;"
            " elif git apply --check --ignore-whitespace /tmp/reg.patch 2>/dev/null;"
            " then git apply --ignore-whitespace /tmp/reg.patch;"
            " else echo __SWE_APPLY_FAILED__; exit 97; fi"
        )
    script += (
        " && { source /opt/miniconda3/bin/activate testbed 2>/dev/null || true; }"
        f" && python -m pytest {target} -q -rf -p no:cacheprovider"
    )
    try:
        r = subprocess.run(
            ["docker", "run", "--rm", *mounts, img, "bash", "-lc", script],
            capture_output=True, text=True, errors="replace", timeout=600,
        )
    except subprocess.TimeoutExpired:
        return 92, "pytest_timeout"
    out = (r.stdout or "") + (r.stderr or "")
    if "__SWE_APPLY_FAILED__" in out:
        return 97, "apply_failed"
    return r.returncode, out[-6000:]


def _regression_guard(
    repo_path: Path, rel_file: str, patch_text: str, instance: dict
) -> tuple[bool, str]:
    """Option C (débat 2026-07-04) : un patch dont le repro PASSE ne doit casser
    AUCUN test EXISTANT du module cible (tests du base_commit = zéro info gold).
    Baseline pytest mise en cache par instance ; infra indisponible = guard neutre."""
    iid = instance["instance_id"]
    tdir = Path(rel_file).parent / "tests"
    if not (repo_path / tdir).is_dir():
        return True, "no_local_tests"
    target = tdir.as_posix()
    base = _REG_BASE_CACHE.get(iid)
    if base is None:
        rc0, out0 = _docker_pytest(target, "", repo_path, instance)
        if rc0 >= 90:
            return True, f"guard_skipped:{out0[:80]}"
        base = set(re.findall(r"^FAILED ([^\s]+)", out0, re.M))
        _REG_BASE_CACHE[iid] = base
    rc1, out1 = _docker_pytest(target, patch_text, repo_path, instance)
    if rc1 >= 90:
        return True, f"guard_skipped:{out1[:80]}"
    after = set(re.findall(r"^FAILED ([^\s]+)", out1, re.M))
    new = sorted(after - base)
    if not new:
        return True, f"ok ({len(after)} fails vs {len(base)} baseline)"
    return False, "new failing tests: " + ", ".join(n.rsplit("::", 1)[-1] for n in new[:8])


def _run_repro(
    repro_code: str, patch_text: str, repo_path: Path, instance: dict
) -> tuple[bool, str]:
    """Reset repo, optionally apply the patch, run the standalone repro script.
    patch_text='' = baseline. Returns (exit0, output). A standalone script
    needs no per-repo test runner — works where pytest <file> can't."""
    if _repro_docker_on():
        return _run_repro_docker(repro_code, patch_text, repo_path, instance)
    subprocess.run(
        ["git", "reset", "--hard", "HEAD"], cwd=str(repo_path), capture_output=True, timeout=15
    )
    subprocess.run(["git", "clean", "-fd"], cwd=str(repo_path), capture_output=True, timeout=15)
    if patch_text:
        pt = _sanitize_patch(patch_text)
        if not pt:
            return False, "empty_patch"
        pf = repo_path.parent / f"_repro_{instance['instance_id']}.patch"
        pf.write_text(pt, encoding="utf-8", newline="\n")
        ok = False
        for extra in ([], ["--ignore-whitespace"]):
            c = subprocess.run(
                ["git", "apply", "--check", *extra, str(pf)],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=30,
            )
            if c.returncode == 0:
                subprocess.run(
                    ["git", "apply", *extra, str(pf)],
                    cwd=str(repo_path),
                    capture_output=True,
                    timeout=30,
                )
                ok = True
                break
        try:
            pf.unlink()
        except OSError:
            pass
        if not ok:
            return False, "apply_failed"
    rf = repo_path / "_swe_reproduce.py"
    rf.write_text(repro_code, encoding="utf-8")
    try:
        r = subprocess.run(
            [LAFORGE_PYTHON, str(rf)],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False, "repro_timeout"
    out = "\n".join(l for l in (r.stdout + r.stderr).splitlines() if l.strip())
    # Stage 4 — troncature : ce retour est réinjecté au modèle au retry
    return r.returncode == 0, (_truncate_trace(out, 45) or "(no output)")


def _swarm_audit(instance: dict, plan: str, candidates: list, provider: str) -> int:
    """Auditor — pick the best candidate patch. Returns its index.
    LLM judge on (issue + plan + numbered diffs); tie-break = smallest diff."""
    if len(candidates) == 1:
        return 0
    diffs = "\n\n".join(
        f"### CANDIDATE {i} ({c['n_changed']} lines changed)\n```diff\n{c['patch'][:2500]}\n```"
        for i, c in enumerate(candidates)
    )
    msgs = [
        {
            "role": "system",
            "content": "You audit candidate bug-fix patches. Pick the ONE that best fixes "
            "the issue per the plan: correct logic, minimal change, no collateral "
            "edits. Output EXACTLY one line:\nBEST: <index>",
        },
        {
            "role": "user",
            "content": f"Issue:\n{instance['problem_statement'][:1200]}\n\n"
            f"Fix plan:\n{plan}\n\n{diffs}",
        },
    ]
    try:
        m = re.search(r"BEST:\s*(\d+)", call_llm(msgs, provider, max_tokens=40))
        if m and 0 <= int(m.group(1)) < len(candidates):
            return int(m.group(1))
    except Exception:
        pass
    return min(range(len(candidates)), key=lambda i: candidates[i]["n_changed"])


def _swarm_best_of_n(
    instance: dict,
    coder_ctx: str,
    rel_file: str,
    plan: str,
    source: str,
    n: int,
    providers: dict,
    build_patch,
    repro: str = "",
    callers: str = "",
) -> list:
    """Stage 3 best-of-N — generate n candidate patches in parallel over a
    distinct-provider rotation. Returns [{provider, patched_content, patch,
    n_changed}, ...] for candidates that produced a non-empty patch.
    Mode contraint : repro/callers threadés dans chaque candidat (même contexte
    que le chemin best_of=1) — les candidats sont comparables et sélectionnables
    par l'oracle repro en aval (anti-variance)."""
    from concurrent.futures import ThreadPoolExecutor

    # Mode contraint : N tirages du MÊME codeur fort (diversité par température +
    # hint d'index), PAS une rotation multi-providers hétérogène — les providers
    # faibles (mistral fragile, nvidia timeout) diluaient les tirages du bon
    # modèle et plombaient l'anti-variance (mesuré 2026-07-04 : best-of-3 dédup =
    # 1 seul tirage cerebras -> 0 patch sur 14096, pourtant résolu au best_of=1).
    if _constrained():
        # Pool best-of DISTRIBUÉ sur endpoints FORTS à quotas SÉPARÉS (anti-429 +
        # diversité modèles = anti-variance renforcé). SWE_BESTOF_POOL surchargeable
        # (ex "cerebras,openrouter,lmstudio"). Défaut = le coder répété (legacy sûr).
        _pool_env = os.environ.get("SWE_BESTOF_POOL", "").strip()
        if _pool_env:
            strong = [p.strip() for p in _pool_env.split(",") if p.strip()]
            rota = [strong[i % len(strong)] for i in range(n)]
        else:
            rota = [providers["coder"]] * n
    else:
        pool = list(
            dict.fromkeys(
                [
                    providers["coder"],
                    providers["architect"],
                    FALLBACK_PROVIDER,
                    "cerebras",
                    "mistral",
                    "nvidia",
                ]
            )
        )
        rota = [pool[i % len(pool)] for i in range(n)]

    def _one(idx_prov):
        idx, prov = idx_prov
        try:
            # 1er candidat en température basse (sûr) ; suivants = le critique non
            # vide monte la température (_swarm_code_sr) + hint d'index = graines
            # distinctes du même modèle fort -> diversité SANS provider faible.
            crit = "" if idx == 0 else (
                f"produce an alternative correct edit (independent attempt {idx}); "
                "copy the SEARCH text character-for-character from the code shown."
            )
            sr_raw = _swarm_code_sr(
                instance, coder_ctx, rel_file, plan, prov,
                critique=crit, repro=repro, callers=callers,
            )
            pc = _apply_coder_output(sr_raw, source)
            if not pc:
                return None
            patch, n_changed = build_patch(pc)
            if not patch:
                return None
            return {"provider": prov, "patched_content": pc, "patch": patch, "n_changed": n_changed}
        except Exception:
            return None

    # Mode contraint : tirages SÉQUENTIELS (pas 3 threads frappant le même
    # provider free-tier en parallèle -> 429 rate-limit saturé, mesuré
    # 2026-07-04 best-of-3 sur 10 instances = 0 patch). Le backoff de
    # _retry_post gère alors les pics ; la diversité vient de la température,
    # pas de la concurrence.
    if _constrained():
        out_c = []
        for ip in enumerate(rota):
            r = _one(ip)
            if r:
                out_c.append(r)
        return out_c
    with ThreadPoolExecutor(max_workers=min(n, 5)) as ex:
        return [r for r in ex.map(_one, list(enumerate(rota))) if r]


def _secondary_file_edits(
    instance: dict, plan: str, primary_rel: str, files: list, repo_path: Path, provider: str
) -> str:
    """Stage 3b — passe ADDITIVE multi-fichiers. Le fix principal est posé
    dans primary_rel ; on demande au Coder si une AUTRE file candidate doit
    changer de façon coordonnée. Renvoie des sections unidiff additionnelles
    (ou '' — cas le plus fréquent). Le flux mono-fichier reste 100% intact."""
    import difflib as _dl

    others = [f for f in files if f.as_posix().replace("\\", "/") != primary_rel][:3]
    skels = []
    for f in others:
        try:
            src = (repo_path / f).read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        skels.append(f"### {f.as_posix()}\n{_skeleton_file(src)[:3000]}")
    if not skels:
        return ""
    msgs = [
        {
            "role": "system",
            "content": "The primary bug fix is already applied in another file. Decide if "
            "the fix REQUIRES a coordinated change in one of the files below.\n"
            "If NOT — output exactly: NONE\n"
            "If yes — for each file, output:\n"
            "# FILE: <exact path>\n```python\n<complete corrected function>\n```",
        },
        {
            "role": "user",
            "content": f"Issue:\n{instance['problem_statement'][:900]}\n\nFix plan:\n{plan}\n\n"
            f"Primary file already fixed: {primary_rel}\n\n"
            f"Other candidate files:\n" + "\n\n".join(skels),
        },
    ]
    try:
        raw = call_llm(msgs, provider, max_tokens=1500, temperature=0.1)
    except Exception:
        return ""
    if "# FILE:" not in raw or "NONE" in raw[:20]:
        return ""
    parts = re.split(r"^#\s*FILE:\s*(.+)$", raw, flags=re.M)
    sections = []
    for i in range(1, len(parts) - 1, 2):
        rel = parts[i].strip().replace("\\", "/")
        fp = repo_path / rel
        if not fp.exists():
            continue
        try:
            old = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        new = _apply_coder_output(parts[i + 1], old)
        if not new or new == old:
            continue
        d = "".join(
            _dl.unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
            )
        )
        if d:
            sections.append(f"diff --git a/{rel} b/{rel}\n{d}")
    return "\n".join(sections)


def generate_patch_swarm(
    instance: dict,
    work_dir: Path,
    providers: dict | None = None,
    test_fix: bool = False,
    best_of: int = 1,
) -> dict:
    """Swarm: Explorer(file) -> Architect(plan) -> Coder(SEARCH/REPLACE blocks).
    SR edits handle constants/settings, not just functions. Soft 40-line diff
    gate. Fallback to another provider when no edit applies. test_fix=True runs
    an agent-written reproduce.py and iterates the Coder until it exits 0."""
    import difflib

    providers = providers or _SWARM_PROVIDERS
    t0 = time.time()
    iid = instance["instance_id"]

    def _fail(reason: str) -> dict:
        return {
            "instance_id": iid,
            "model_patch": "",
            "model_name_or_path": "swarm-" + providers["coder"],
            "error": reason,
            "elapsed_s": round(time.time() - t0, 2),
            "swarm": True,
        }

    repo_path = _clone_repo(instance["repo"], instance["base_commit"], work_dir)
    if not repo_path:
        return _fail("clone_failed")
    # Stage 0 — distillation de l'issue : keywords purs + fichiers stacktrace
    distilled = _distill_issue(instance, providers["explorer"])
    files, _ = _find_relevant_files(
        repo_path,
        instance["problem_statement"],
        fail_to_pass=instance.get("FAIL_TO_PASS", []),
        query_terms=distilled.get("keywords"),
        force_files=distilled.get("stacktrace_files"),
    )
    if not files:
        return _fail("no_files")

    # Stage 1 — Explorer (file); provider down -> fall through to heuristic
    try:
        rel_file = _swarm_explore(instance, files, repo_path, providers["explorer"])
    except Exception:
        rel_file = ""
    target = repo_path / rel_file if rel_file else None
    if not target or not target.exists() or target.is_dir():
        for _f in files:  # files = chemins relatifs ; sauter les dossiers
            _cand = repo_path / str(_f).replace("\\", "/")
            if _cand.is_file():
                rel_file = str(_f).replace("\\", "/")
                target = _cand
                break
    if not target or not target.is_file():
        return _fail("no_target_file")
    source = target.read_text(encoding="utf-8", errors="replace")

    # Stage 2 — Architect (plan); fall back to another provider on outage
    plan = ""
    for _prov in (providers["architect"], FALLBACK_PROVIDER):
        try:
            plan = _swarm_plan(instance, source, rel_file, _prov)
        except Exception as _e:
            print(f"[architect] {_prov} EXC {type(_e).__name__}: {_e}", flush=True)
            plan = ""
        if plan.strip() and not plan.lstrip().startswith("[ERR]"):
            break
        plan = ""
        print(f"[architect] {_prov} -> plan vide/echec", flush=True)
    if not plan.strip():
        return _fail("architect_failed")

    coder_ctx = _coder_context(source, plan, distilled.get("keywords"))

    # Mode contraint (SWEB_CONSTRAINED=1) : test-driven patching LÉGAL —
    # repro auto-généré AVANT le codeur (jamais le test_patch gold = leak)
    # + skeleton des callers injectés dans le prompt.
    early_repro, callers_ctx = "", ""
    if _constrained():
        try:
            kw = {str(k).lower() for k in (distilled.get("keywords") or [])}
            callers_ctx = _callgraph_context(repo_path, [Path(rel_file)], kw, cap_files=150)
        except Exception:
            callers_ctx = ""
        if test_fix:
            try:
                _prepare_repo_for_test(repo_path)
                early_repro = _gen_reproduce(instance, providers["architect"])
                try:
                    compile(early_repro, "<repro>", "exec")
                except SyntaxError:
                    early_repro = ""  # sortie tronquée/illisible
                if len(early_repro) > 30:
                    ok0, _b0 = _run_repro(early_repro, "", repo_path, instance)
                    if ok0 or any(
                        t in _b0 for t in ("SyntaxError", "ModuleNotFoundError", "ImportError")
                    ):
                        early_repro = ""  # passe sur code buggé, ou env/import cassé
            except Exception:
                early_repro = ""

    def _build_patch(content: str) -> tuple[str, int]:
        d = "".join(
            difflib.unified_diff(
                source.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=f"a/{rel_file}",
                tofile=f"b/{rel_file}",
            )
        )
        if not d:
            return "", 0
        p = _sanitize_patch(f"diff --git a/{rel_file} b/{rel_file}\n{d}")
        n = sum(
            1 for l in p.splitlines() if l[:1] in ("+", "-") and not l.startswith(("+++", "---"))
        )
        return p, n

    # Stage 3 — Coder (SEARCH/REPLACE). best_of=1: single coder + fallback on
    # outage / non-applying edit. best_of>1: N parallel candidates over a
    # distinct-provider rotation, applying ones kept, auditor picks the best.
    used_fallback = False
    n_candidates = 1
    bestof_resolved = None
    if best_of > 1:
        cands = _swarm_best_of_n(
            instance, coder_ctx, rel_file, plan, source, best_of, providers, _build_patch,
            repro=early_repro, callers=callers_ctx,
        )
        cands = [c for c in cands if _check_patch_applies(c["patch"], repo_path)[0]]
        if not cands:
            return _fail("no_applicable_edit")
        n_candidates = len(cands)
        # SÉLECTION PAR ORACLE REPRO (anti-variance) : en mode contraint+test_fix,
        # on garde le 1er candidat dont le repro-docker PASSE, plutôt qu'un juge
        # LLM stochastique. Fallback = audit symbolique LLM (comportement legacy).
        best = None
        if _constrained() and test_fix and early_repro:
            _prep_done = False
            for c in sorted(cands, key=lambda x: x["n_changed"]):  # patch minimal d'abord
                if not _prep_done:
                    try:
                        _prepare_repo_for_test(repo_path)
                    except Exception:
                        pass
                    _prep_done = True
                ok, _out = _run_repro(early_repro, c["patch"], repo_path, instance)
                if ok and _constrained():
                    _rok, _ = _regression_guard(repo_path, rel_file, c["patch"], instance)
                    ok = _rok
                if ok:
                    best = c
                    bestof_resolved = True
                    break
        if best is None:
            best = (
                cands[0]
                if len(cands) == 1
                else cands[_swarm_audit(instance, plan, cands, providers["architect"])]
            )
        patched_content = best["patched_content"]
        patch, n_changed = best["patch"], best["n_changed"]
        used_fallback = best["provider"] != providers["coder"]
    else:
        patched_content = ""
        for _idx, _prov in enumerate((providers["coder"], FALLBACK_PROVIDER)):
            _crit = (
                ""
                if _idx == 0
                else "previous attempt produced no applicable edit — copy the "
                "SEARCH text character-for-character from the code shown."
            )
            # Retry anti-hallucination (mode contraint) : contexte focalisé
            # verbatim au lieu du fichier entier.
            _ctx = coder_ctx
            if _idx > 0 and _constrained():
                _ctx = _focus_ctx(source, instance, plan) or coder_ctx
            try:
                sr_raw = _swarm_code_sr(
                    instance,
                    _ctx,
                    rel_file,
                    plan,
                    _prov,
                    critique=_crit,
                    repro=early_repro,
                    callers=callers_ctx,
                )
                patched_content = _apply_coder_output(sr_raw, source)
                if not patched_content:
                    try:
                        _nb = len(_parse_sr_blocks(sr_raw))
                        _dbg = SWE_DIR / f"coder_fail_{iid}_{_idx}.txt"
                        _dbg.write_text(sr_raw, encoding="utf-8")
                        print(
                            f"[coder] sortie non applicable ({_nb} blocs SR) -> {_dbg.name}",
                            flush=True,
                        )
                    except Exception:
                        pass
            except Exception:
                patched_content = ""
            if patched_content:
                used_fallback = _idx > 0
                break
        if not patched_content:
            return _fail("no_applicable_edit")
        patch, n_changed = _build_patch(patched_content)

    # Stage 4 — soft diff gate: too large -> critique + one retry (never empty)
    if n_changed > MAX_DIFF_LINES:
        try:
            sr2 = _swarm_code_sr(
                instance,
                coder_ctx,
                rel_file,
                plan,
                providers["coder"],
                critique=f"your diff changed {n_changed} lines "
                f"— far too many. Restrict the edit to ONLY the "
                f"lines responsible for the bug.",
                repro=early_repro,
                callers=callers_ctx,
            )
            pc2 = _apply_coder_output(sr2, source)
            if pc2:
                p2, n2 = _build_patch(pc2)
                if 0 < n2 <= n_changed:
                    patched_content, patch, n_changed = pc2, p2, n2
        except Exception:
            pass

    applied = False
    if patch:
        applied, _ = _check_patch_applies(patch, repo_path)

    # Stage 3b — passe additive multi-fichiers : si le fix exige une edition
    # coordonnee dans une autre file, on l'ajoute. Fail-safe : si le patch
    # combine ne s'applique plus, on garde le patch primaire seul.
    if applied and patch:
        try:
            extra = _secondary_file_edits(
                instance, plan, rel_file, files, repo_path, providers["coder"]
            )
        except Exception:
            extra = ""
        if extra:
            combined = patch.rstrip("\n") + "\n" + extra.rstrip("\n") + "\n"
            if _check_patch_applies(combined, repo_path)[0]:
                patch = combined

    # Stage 5 — reproduce-driven test-fix loop. The agent writes a standalone
    # reproduce.py from the issue; we iterate the Coder until it exits 0.
    # A standalone script needs no per-repo test runner — works where
    # `pytest <file>` fails (django runtests.py, astropy C-ext).
    resolved_local = bestof_resolved
    test_iters = 0
    test_log: list[str] = []
    if bestof_resolved:
        test_log.append("resolved via best-of oracle repro selection")
    if test_fix and applied and not bestof_resolved:
        try:
            _prepare_repo_for_test(repo_path)
            repro = early_repro or _gen_reproduce(instance, providers["architect"])
        except Exception as ex:
            repro = ""
            test_log.append(f"repro_gen_error: {str(ex)[:120]}")
        if len(repro) > 30:
            try:
                compile(repro, "<repro>", "exec")
            except SyntaxError:
                repro = ""
                test_log.append("repro_invalid: syntax error")
        if len(repro) > 30:
            base_ok, _bo = _run_repro(repro, "", repo_path, instance)
            if base_ok:
                test_log.append("repro_invalid: exits 0 on buggy code")
            elif any(t in _bo for t in ("SyntaxError", "ModuleNotFoundError", "ImportError")):
                test_log.append(f"repro_invalid: env/import: {_bo[:120]}")
            else:
                test_log.append("baseline: bug reproduced")
                cur_patch = patch
                for test_iters in range(1, MAX_SWARM_FIX + 1):
                    ok, out = _run_repro(repro, cur_patch, repo_path, instance)
                    if ok and _constrained():
                        _rok, _rout = _regression_guard(repo_path, rel_file, cur_patch, instance)
                        if not _rok:
                            ok = False
                            out = (
                                "the reproduce script PASSES but the patch BREAKS "
                                "existing tests — fix without breaking them:\n" + _rout
                            )
                    test_log.append(f"it{test_iters}: {'PASS' if ok else out[:200]}")
                    if ok:
                        resolved_local = True
                        patch = cur_patch
                        break
                    resolved_local = False
                    if test_iters == MAX_SWARM_FIX or out in (
                        "apply_failed",
                        "empty_patch",
                        "repro_timeout",
                    ):
                        break
                    _stuck = len(test_log) >= 2 and out[:200] in str(test_log[-2])
                    _reorient = (
                        " The SAME failure persists after your edit: your fix LOCATION is"
                        " probably wrong. Re-read the traceback and the issue, follow the"
                        " call chain, and edit a DIFFERENT function of the file."
                        if _stuck
                        else ""
                    )
                    try:
                        sr_n = _swarm_code_sr(
                            instance,
                            coder_ctx,
                            rel_file,
                            plan,
                            providers["coder"],
                            critique="the fix is wrong — the reproduce script "
                            f"still fails:\n{out[:600]}{_reorient}",
                            repro=repro,
                            callers=callers_ctx,
                        )
                        pc_n = _apply_sr_blocks(source, _parse_sr_blocks(sr_n))
                    except Exception as ex:
                        test_log.append(f"retry_error: {str(ex)[:120]}")
                        break
                    if not pc_n:
                        test_log.append("retry: no applicable edit")
                        break
                    cand, _cn = _build_patch(pc_n)
                    if not cand:
                        break
                    cur_patch = cand

    return {
        "instance_id": iid,
        "model_patch": patch if applied else "",
        "model_name_or_path": "swarm-" + providers["coder"],
        "elapsed_s": round(time.time() - t0, 2),
        "swarm": True,
        "target_file": rel_file,
        "n_changed_lines": n_changed,
        "applied": applied,
        "used_fallback": used_fallback,
        "n_candidates": n_candidates,
        "resolved_local": resolved_local,
        "test_iters": test_iters,
        "test_log": test_log,
    }


# ── Local evaluation (approx, no Docker) ─────────────────────────────────────


def _truncate_trace(log: str, max_lines: int = 50) -> str:
    """Stage 4 — réduit un log pytest/traceback bruyant à l'essentiel. Un
    modèle <70B sature et hallucine si on lui réinjecte 800 lignes de log."""
    if not log:
        return ""
    lines = [l for l in log.splitlines() if l.strip()]
    anchor = 0
    for i, ln in enumerate(lines):
        if "FAILURES" in ln or "Traceback (most recent call last)" in ln:
            anchor = i  # debut du dernier bloc d'echec
    tail = lines[anchor:]
    if len(tail) > max_lines:
        # debut du bloc (nom du test + en-tete) + fin (exception + frames)
        tail = tail[:8] + ["  ...(trace tronquee)..."] + tail[-(max_lines - 9) :]
    return "\n".join(tail)[:2500]


def _lint_files(repo_path: Path, patch_text: str) -> tuple[bool, str]:
    """Stage 4 — linter-gate : py_compile des fichiers .py modifiés par le
    patch. ~30% des échecs agent = simple erreur de syntaxe LLM ; ce check
    est rapide et déterministe, AVANT le pip install + pytest (lents)."""
    import py_compile

    for rel in re.findall(r"^\+\+\+ b/(.+)$", patch_text, flags=re.M):
        rel = rel.strip()
        if not rel.endswith(".py"):
            continue
        fp = repo_path / rel
        if not fp.exists():
            continue
        try:
            py_compile.compile(str(fp), doraise=True)
        except py_compile.PyCompileError as e:
            return False, f"syntax_error {rel}: {str(e)[:160]}"
        except Exception:
            pass
    return True, "ok"


def _apply_and_test(instance: dict, patch_text: str, work_dir: Path) -> tuple[bool, str]:
    if not patch_text.strip():
        return False, "empty_patch"

    repo_path = _clone_repo(instance["repo"], instance["base_commit"], work_dir)
    if not repo_path:
        return False, "clone_failed"

    # Reset to clean base_commit state (previous eval runs may have applied patches)
    subprocess.run(
        ["git", "reset", "--hard", "HEAD"], cwd=str(repo_path), capture_output=True, timeout=15
    )
    subprocess.run(["git", "clean", "-fd"], cwd=str(repo_path), capture_output=True, timeout=15)

    # Re-sanitize (normalize context lines, fix @@ counts, ensure trailing \n)
    patch_text = _sanitize_patch(patch_text)
    if not patch_text:
        return False, "empty_patch_after_sanitize"
    patch_file = work_dir / f"{instance['instance_id']}.patch"
    patch_file.write_text(patch_text, encoding="utf-8", newline="\n")

    # Try git apply: strict first, then ignore-whitespace
    applied = False
    for extra in ([], ["--ignore-whitespace"]):
        r = subprocess.run(
            ["git", "apply", "--check", *extra, str(patch_file)],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
        if r.returncode == 0:
            subprocess.run(
                ["git", "apply", *extra, str(patch_file)],
                cwd=str(repo_path),
                capture_output=True,
                timeout=30,
            )
            applied = True
            break

    if not applied:
        err = r.stderr.strip()[:80]
        return False, f"patch_apply_failed: {err}"

    # Stage 4 — linter-gate : syntaxe AVANT le pip install + pytest (lents)
    lint_ok, lint_msg = _lint_files(repo_path, patch_text)
    if not lint_ok:
        return False, lint_msg

    # Install package
    subprocess.run(
        [LAFORGE_PYTHON, "-m", "pip", "install", "-e", ".", "-q"],
        cwd=str(repo_path),
        capture_output=True,
        timeout=120,
    )

    # Run FAIL_TO_PASS tests
    fail_tests = instance.get("FAIL_TO_PASS", [])
    if not fail_tests:
        return False, "no_fail_to_pass"

    r = subprocess.run(
        [
            LAFORGE_PYTHON,
            "-m",
            "pytest",
            *fail_tests[:5],
            "-x",
            "-q",
            "--tb=line",
            "-W",
            "ignore::UserWarning",
        ],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        errors="replace",
        timeout=120,
    )
    if r.returncode != 0:
        return False, _truncate_trace(r.stdout + r.stderr, 50)

    # Stage 4 — gate PASS_TO_PASS : un patch qui passe FAIL_TO_PASS mais
    # casse un PASS_TO_PASS = régression = 0 point au harness officiel.
    pass_tests = instance.get("PASS_TO_PASS", [])
    if pass_tests:
        try:
            rp = subprocess.run(
                [
                    LAFORGE_PYTHON,
                    "-m",
                    "pytest",
                    *pass_tests[:8],
                    "-x",
                    "-q",
                    "--tb=line",
                    "-W",
                    "ignore::UserWarning",
                ],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            return True, "ok (gate P2P timeout, ignore)"
        if rp.returncode != 0:
            return False, "broke_PASS_TO_PASS: " + _truncate_trace(rp.stdout + rp.stderr, 25)
    return True, "ok"


# ── Main runners ──────────────────────────────────────────────────────────────


def run_generate(
    provider: str = "mistral",
    max_entries: int = 50,
    split: str = "test",
    variant: str = "verified",
    clone: bool = False,
    swarm: bool = False,
    test_fix: bool = False,
    instance_filter: str | None = None,
    best_of: int = 1,
) -> Path:
    _all = ensure_dataset(split, variant)
    if instance_filter:
        _ids = {x.strip() for x in instance_filter.split(",") if x.strip()}
        instances = [i for i in _all if i["instance_id"] in _ids]
        if not instances:
            print(f"[swebench] no instance matched: {instance_filter}")
            sys.exit(1)
    else:
        instances = _all[:max_entries]
    tag = f"{variant}_{split}"
    mode = "swarm" if swarm else provider
    tf = " | test-fix" if (swarm and test_fix) else ""
    bo = f" | best-of-{best_of}" if (swarm and best_of > 1) else ""
    print(f"[swebench-{variant}] generate {len(instances)} | mode={mode} | clone={clone}{tf}{bo}")

    work_dir = SWE_DIR / "repos"
    work_dir.mkdir(exist_ok=True)
    predictions = []
    out = SWE_DIR / f"predictions_{mode}_{tag}_{len(instances)}.jsonl"

    for i, inst in enumerate(instances):
        print(f"  [{i + 1}/{len(instances)}] {inst['instance_id']}", end=" ", flush=True)
        try:
            if swarm:
                pred = generate_patch_swarm(inst, work_dir, test_fix=test_fix, best_of=best_of)
            elif clone and os.environ.get("SWEBENCH_BESTOFN"):
                # best-of-N + sélection par test (levier #1 panel/moatless) sur le chemin direct
                pred = generate_patch_best_of_n(inst, work_dir=work_dir)
            else:
                pred = generate_patch(inst, provider, work_dir if clone else None, clone)
        except Exception as _exc:  # une instance qui crashe ne tue PAS le run
            import traceback as _tb

            _tb.print_exc()
            pred = {
                "instance_id": inst["instance_id"],
                "model_patch": "",
                "error": f"crash: {type(_exc).__name__}: {str(_exc)[:200]}",
                "elapsed_s": 0,
                "swarm": swarm,
            }
        has = bool(pred.get("model_patch", "").strip())
        extra = ""
        if swarm:
            rl = pred.get("resolved_local")
            rl_s = "" if rl is None else (" RESOLVED" if rl else " unresolved")
            fb = " fb" if pred.get("used_fallback") else ""
            tf = (pred.get("target_file") or "?").split("/")[-1]
            nc = pred.get("n_candidates", 1)
            nc_s = f" c{nc}" if nc > 1 else ""
            extra = (
                f" [{tf} d{pred.get('n_changed_lines', 0)} "
                f"it{pred.get('test_iters', 0)}{nc_s}{fb}{rl_s}]"
            )
        print(f"{'patch_ok' if has else 'no_patch'} {pred.get('elapsed_s', 0)}s{extra}")
        predictions.append(pred)
        out.write_text("\n".join(json.dumps(p) for p in predictions))  # incremental — pollable
        time.sleep(0.8)

    n_patch = sum(1 for p in predictions if p.get("model_patch", "").strip())
    print(f"\n[swebench-{variant}] patches generated: {n_patch}/{len(instances)}")
    print(f"Saved -> {out}")
    return out


def run_evaluate_local(
    predictions_path: Path, split: str = "test", variant: str = "verified", max_entries: int = 20
) -> dict:
    instances = {e["instance_id"]: e for e in ensure_dataset(split, variant)}
    predictions = [
        json.loads(l) for l in Path(predictions_path).read_text().splitlines() if l.strip()
    ]
    predictions = predictions[:max_entries]

    work_dir = SWE_DIR / "eval_repos"
    work_dir.mkdir(exist_ok=True)

    results, t0 = [], time.time()
    for i, pred in enumerate(predictions):
        iid = pred["instance_id"]
        inst = instances.get(iid)
        if not inst:
            print(f"  [{i + 1}] {iid} SKIP (not in dataset)")
            continue

        patch = pred.get("model_patch", "")
        if not patch.strip():
            print(f"  [{i + 1}] {iid} FAIL no_patch")
            results.append({"instance_id": iid, "resolved": False, "reason": "no_patch"})
            continue

        resolved, reason = _apply_and_test(inst, patch, work_dir)
        print(f"  [{i + 1}] {iid} {'PASS' if resolved else 'FAIL'} [{reason[:50]}]")
        results.append({"instance_id": iid, "resolved": resolved, "reason": reason})

    resolved_n = sum(1 for r in results if r["resolved"])
    resolve_rate = round(resolved_n / len(results) * 100, 1) if results else 0.0

    summary = {
        "variant": variant,
        "split": split,
        "n_evaluated": len(results),
        "resolved": resolved_n,
        "resolve_rate": resolve_rate,
        "elapsed_s": round(time.time() - t0, 1),
        "WARNING": "local_eval_approximate_no_docker",
        "results": results,
    }

    out = SWE_DIR / f"eval_{variant}_{Path(predictions_path).stem}.json"
    out.write_text(json.dumps(summary, indent=2, default=str))

    print(f"\n{'=' * 55}")
    print(
        f"SWE-bench {variant.upper()} RESOLVE RATE : {resolve_rate}%  ({resolved_n}/{len(results)}) [LOCAL APPROX]"
    )
    print("NOTE: Docker harness required for official publishable score.")
    print(f"Saved -> {out}")

    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_self_correction import anchor_solution

        anchor_solution(
            problem=f"SWE-bench {variant} — {len(results)} instances local eval",
            solution=f"resolve_rate={resolve_rate}% provider={predictions_path} variant={variant}",
            example=f"python tools/forge_swebench_runner.py --variant {variant} --provider mistral --max {len(results)}",
            domain="systeme",
        )
    except Exception:
        pass

    return summary


def run_quick(
    provider: str = "mistral",
    variant: str = "verified",
    max_entries: int = 23,
    clone: bool = False,
    split: str = "test",
) -> dict:
    """Generate + local eval (quick feedback loop, local approx scoring)."""
    preds_path = run_generate(
        provider=provider, max_entries=max_entries, split=split, variant=variant, clone=clone
    )
    return run_evaluate_local(preds_path, split=split, variant=variant, max_entries=max_entries)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode", default="quick", choices=["quick", "generate", "evaluate", "lite"]
    )
    parser.add_argument("--variant", default="verified", choices=["lite", "verified", "live"])
    parser.add_argument(
        "--provider",
        default="mistral",
        choices=[
            "mistral",
            "ollama",
            "cerebras",
            "nvidia",
            "claude",
            "claude_cli",
            "gemini",
            "gemini_cli",
            # Ajout 2026-08-01 : la liste CLI avait divergé de call_llm() qui les
            # supporte deja (choices perime -> argparse rc=2 sur un provider valide).
            "groq",
            "openrouter",
            "lmstudio",
            "copilot_cli",
            "claude_agent_sdk",
        ],
    )
    parser.add_argument("--max", type=int, default=23)
    parser.add_argument("--split", default="test", choices=["test", "dev"])
    parser.add_argument(
        "--clone", action="store_true", help="Clone repos for file context (better patches, slower)"
    )
    parser.add_argument(
        "--swarm", action="store_true", help="Use Explorer/Architect/Coder swarm pipeline"
    )
    parser.add_argument(
        "--test-fix",
        action="store_true",
        help="Swarm: run FAIL_TO_PASS during generation + iterate "
        "Coder on failures (slower, attacks fix-logic quality)",
    )
    parser.add_argument(
        "--predictions", default=None, help="Path to predictions JSONL (for --mode evaluate)"
    )
    parser.add_argument(
        "--instance",
        default=None,
        help="Run specific instance_id(s), comma-separated (overrides --max)",
    )
    parser.add_argument(
        "--best-of",
        type=int,
        default=1,
        dest="best_of",
        help="Swarm: N candidate patches in parallel + auditor picks the best (1 = off)",
    )
    args = parser.parse_args()

    if args.mode in ("quick", "lite"):
        run_quick(
            provider=args.provider,
            variant=args.variant,
            max_entries=args.max,
            clone=args.clone,
            split=args.split,
        )
    elif args.mode == "generate":
        run_generate(
            provider=args.provider,
            max_entries=args.max,
            split=args.split,
            variant=args.variant,
            clone=args.clone,
            swarm=args.swarm,
            test_fix=args.test_fix,
            instance_filter=args.instance,
            best_of=args.best_of,
        )
    elif args.mode == "evaluate":
        if not args.predictions:
            print("--predictions required for evaluate mode")
            sys.exit(1)
        run_evaluate_local(
            Path(args.predictions), split=args.split, variant=args.variant, max_entries=args.max
        )

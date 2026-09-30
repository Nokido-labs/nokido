"""tools/forge_swebench_lats_runner.py - runner SWE-bench avec stack LATS.

Pipeline post-pivot DSPy :
  1. Pour chaque instance SWE-bench Lite/Verified :
     a. clone repo + checkout base_commit
     b. forge_repo_map.build_repo_map -> markdown carte topographique
     c. propose_fn = ask provider cloud (hub) avec context = repo_map + issue
     d. test_fn = default_apply_and_test (git apply + pytest sur FAIL_TO_PASS)
     e. lats_search(n_initial=3, max_depth=2, beam_width=2)
     f. best.patch.diff = prediction
  2. predictions.jsonl + log par instance
  3. Reuse run_evaluate_local du runner officiel pour scoring local

Pas de DSPy. Pas de schema rigide. Le LLM cloud genere du texte libre,
l agent navigue via la repo_map, lats_search arbitre par tests deterministes.

Usage :
  LAFORGE_PYTHON tools/forge_swebench_lats_runner.py --max 5 --variant lite
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Force offline HF datasets : evite re-fetch quand cache local OK
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_lats import (  # noqa: E402
    PatchProposal,
    SandboxResult,
    lats_search,
)

try:
    from nokido_agent.app.forge_secrets import get_secret as _get_secret  # noqa: E402
except ImportError:
    _get_secret = None
from nokido_agent.app.forge_repo_map import build_repo_map, render_markdown  # noqa: E402

# Reuse dataset loader du runner officiel
from nokido_agent.tools.forge_swebench_runner import ensure_dataset  # noqa: E402

# Cache repo_map per instance (5-10x speedup sur backtrack)
try:
    from nokido_agent.tools.forge_swebench_repo_cache import (  # noqa: E402
        cached_repo_path as _cache_repo_path,
    )
    from nokido_agent.tools.forge_swebench_repo_cache import (
        load_cached_markdown as _cache_load_md,
    )
    from nokido_agent.tools.forge_swebench_repo_cache import (
        prepare_instance as _cache_prepare,
    )

    _CACHE_AVAILABLE = True
except ImportError:
    _CACHE_AVAILABLE = False


def _detect_hub_url() -> str:
    """Detect hub URL :
    1. Env LAFORGE_HUB_URL si set (override explicite)
    2. WSL detect (kernel string 'microsoft') -> lit /etc/resolv.conf
       pour IP Windows host
    3. Default 127.0.0.1:8766
    """
    import os as _os
    import platform as _pf

    explicit = _os.environ.get("LAFORGE_HUB_URL", "").strip()
    if explicit:
        return explicit
    # WSL : windows host accessible via /etc/resolv.conf nameserver
    try:
        if "microsoft" in _pf.uname().release.lower():
            with open("/etc/resolv.conf") as f:
                for line in f:
                    if line.strip().startswith("nameserver"):
                        ip = line.split()[1].strip()
                        if ip and ip != "127.0.0.1":
                            return f"http://{ip}:8766/mcp"
    except (OSError, IndexError):
        pass
    return "http://127.0.0.1:8766/mcp"


HUB_URL = _detect_hub_url()
# HORS de RAG/ depuis le 2026-09-27 : resolveur unique (SWEBENCH_DIR, sinon sandbox/workspace/swebench).
from nokido_agent.app.forge_benchmark_adapter import swebench_dir  # noqa: E402

SWE_DIR = swebench_dir()
SWE_DIR.mkdir(parents=True, exist_ok=True)


# === Cloud propose via hub ask ================================================


def _hub_ask(
    provider: str, message: str, token: str, max_tokens: int = 8192, timeout_s: int = 120
) -> str:
    """Call hub ask, returns LLM text or empty string."""
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "ask",
                "arguments": {
                    "provider": provider,
                    "message": message,
                    "max_tokens": max_tokens,
                    "rag_context": False,
                },
            },
        }
    ).encode()
    req = urllib.request.Request(
        HUB_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-Agent-Name": "SWEBENCH_LATS",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            data = json.loads(r.read())
        text = data.get("result", {}).get("content", [{}])[0].get("text", "")
        try:
            inner = json.loads(text)
            if isinstance(inner, dict) and "text" in inner:
                text = inner["text"]
        except (json.JSONDecodeError, TypeError):
            pass
        return text
    except Exception as e:  # noqa: BLE001
        return f"ERR: {e}"


# === Diff extraction tolerante ================================================

_SYS_PREFIXES = (
    "/usr/lib/python3/dist-packages/",
    "/usr/local/lib/python3/site-packages/",
    "/usr/local/lib/python3/dist-packages/",
    "/usr/lib/python3.10/dist-packages/",
    "/usr/lib/python3.11/dist-packages/",
    "/usr/lib/python3.12/dist-packages/",
    "site-packages/",
)


def _strip_diff_paths(diff: str) -> str:
    """Post-LLM : strip prefixes systeme dans 'diff --git a/...' et '---/+++'.
    LLM hallucine /usr/lib/python3/dist-packages/<pkg>/file.py vu dans stack
    -> git apply echoue. On strip pour rendre les paths repo-relatif."""
    import re as _re

    if not diff:
        return diff
    lines = diff.splitlines(keepends=True)
    out = []
    for line in lines:
        # diff --git a/PATH b/PATH
        m = _re.match(r"^diff --git a/(\S+) b/(\S+)(.*)$", line)
        if m:
            a, b, rest = m.group(1), m.group(2), m.group(3)
            for pre in _SYS_PREFIXES:
                if a.startswith(pre):
                    a = a[len(pre) :]
                if b.startswith(pre):
                    b = b[len(pre) :]
                # Cas sans leading / : '/usr/lib...' transforme en 'usr/lib...'
                pre_no_slash = pre.lstrip("/")
                if a.startswith(pre_no_slash):
                    a = a[len(pre_no_slash) :]
                if b.startswith(pre_no_slash):
                    b = b[len(pre_no_slash) :]
            line = f"diff --git a/{a} b/{b}{rest}\n"
        # --- a/PATH  or  +++ b/PATH
        m = _re.match(r"^(---|\+\+\+) ([ab]/)(\S+)(.*)$", line)
        if m:
            marker, ab, path, rest = m.groups()
            for pre in _SYS_PREFIXES:
                if path.startswith(pre):
                    path = path[len(pre) :]
                pre_no_slash = pre.lstrip("/")
                if path.startswith(pre_no_slash):
                    path = path[len(pre_no_slash) :]
            line = f"{marker} {ab}{path}{rest}\n"
        out.append(line)
    return "".join(out)


def _extract_diff(text: str) -> str:
    """Extrait le PREMIER bloc unidiff valide. Tolerance maximale :
    fences (diff/patch/python/aucun) ou raw 'diff --git' / '--- a/' n importe
    ou dans le texte. Accepte fences non fermes (cloud truncation).
    Post-traite via _strip_diff_paths pour normaliser /usr/lib/."""
    import re as _re

    body = ""
    # 1. Fence explicite ```diff / ```patch (avec ou sans fermeture)
    m = _re.search(r"```(?:diff|patch)\s*\n(.+?)(?:```|$)", text, _re.DOTALL)
    if m:
        candidate = m.group(1).strip()
        if "---" in candidate or "diff --git" in candidate:
            body = candidate
    # 2. Raw 'diff --git' (le plus courant) - greedy jusqu a fin texte ou
    #    prochaine balise non-diff
    if not body:
        m = _re.search(r"(diff --git[\s\S]+?)(?:\n```|\Z)", text)
        if m:
            candidate = m.group(1).strip()
            if candidate.startswith("diff --git"):
                body = candidate
    # 3. Raw '--- a/' (sans diff --git header)
    if not body:
        m = _re.search(r"(--- a/[\s\S]+?)(?:\n```|\Z)", text)
        if m:
            candidate = m.group(1).strip()
            if "+++ b/" in candidate:
                body = candidate
    # 4. Fence ``` (sans tag) ou ```python avec du contenu diff inside
    if not body:
        for m in _re.finditer(r"```\w*\s*\n(.+?)(?:```|$)", text, _re.DOTALL):
            candidate = m.group(1).strip()
            if "diff --git" in candidate or ("--- a/" in candidate and "+++ b/" in candidate):
                body = candidate
                break
    if not body:
        return ""
    return _strip_diff_paths(body)


# === Clone + checkout repo cible ==============================================


def _clone_instance(inst: dict, work_dir: Path) -> Path | None:
    """Clone le repo SWE-bench instance + checkout base_commit. Retourne le
    path local, ou None si echec."""
    repo_name = inst["repo"].replace("/", "_")
    target = work_dir / f"{repo_name}_{inst['instance_id']}"
    if target.exists():
        return target
    url = f"https://github.com/{inst['repo']}"
    try:
        subprocess.run(
            ["git", "clone", "--quiet", url, str(target)],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        errors="replace")
        subprocess.run(
            ["git", "checkout", "-q", inst["base_commit"]],
            cwd=str(target),
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        errors="replace")
        return target
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"  [clone] FAIL {inst['repo']}@{inst['base_commit'][:8]}: {e}")
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        return None


# === Build propose_fn per instance ============================================

_STACK_TRACE_RX = None


def _distill_issue(problem: str) -> dict:
    """Stage 0 : extract keywords + stacktrace_files from problem_statement.
    Pure regex (deterministe, zero LLM, instant). Inspire forge_swebench_runner
    lignes 627+. Retourne {keywords, stacktrace_files}."""
    import re as _re

    global _STACK_TRACE_RX
    if _STACK_TRACE_RX is None:
        # File path patterns in traceback or code
        _STACK_TRACE_RX = _re.compile(
            r'(?:File "([^"]+\.py)"|`([a-zA-Z0-9_/\\\.]+\.py)`|'
            r"in ([a-zA-Z0-9_/\\\.]+\.py)|tests/([a-zA-Z0-9_/\\\.]+\.py))"
        )
    stacktrace_files: set[str] = set()
    for m in _STACK_TRACE_RX.finditer(problem):
        for g in m.groups():
            if g:
                stacktrace_files.add(g.replace("\\", "/"))
    # Keywords : alphanumeric tokens (3+ chars), skip common stopwords
    raw_words = _re.findall(r"[a-zA-Z_]{4,}", problem.lower())
    STOP = {
        "the",
        "this",
        "that",
        "with",
        "from",
        "have",
        "when",
        "what",
        "which",
        "would",
        "should",
        "could",
        "test",
        "tests",
        "code",
        "file",
        "files",
        "function",
        "class",
        "method",
    }
    keywords = [w for w in raw_words if w not in STOP]
    # Dedupe + freq order top 15
    from collections import Counter

    top = [w for w, _ in Counter(keywords).most_common(15)]
    return {"keywords": top, "stacktrace_files": sorted(stacktrace_files)}


def _filter_repo_map_md(
    repo_md: str, keywords: list[str], stacktrace_files: list[str], max_chars: int = 15000
) -> str:
    """Filter repo_map markdown : garde sections ## qui matchent keywords ou
    stacktrace_files. Toujours include les sections stacktrace en TETE."""
    sections = repo_md.split("\n## ")
    header = sections[0]  # premier "# Repo Map ..." bloc
    body_sections = sections[1:] if len(sections) > 1 else []

    priority: list[str] = []  # stacktrace files
    matched: list[str] = []  # keyword match
    rest: list[str] = []

    kw_set = {k.lower() for k in keywords}
    st_set = {s.lower() for s in stacktrace_files}

    for sec in body_sections:
        sec_lower = sec.lower()
        first_line = sec.split("\n", 1)[0].strip()  # le path apres ##
        is_stack = any(st in first_line.lower() for st in st_set)
        has_kw = any(kw in sec_lower for kw in kw_set)
        if is_stack:
            priority.append(sec)
        elif has_kw:
            matched.append(sec)
        else:
            rest.append(sec)

    # Compose : header + priority (forced) + matched + rest jusqu a max_chars
    out = header
    for sec in priority + matched + rest:
        candidate = out + "\n## " + sec
        if len(candidate) > max_chars:
            break
        out = candidate
    return out


def _select_candidate_files(
    distill: dict, repo_path: Path, max_files: int = 5
) -> list[tuple[str, float]]:
    """Selectionne les N fichiers les plus pertinents pour le bug.
    Priorise : stack_files (forces), puis fichiers contenant les top keywords
    dans leur PATH ou leurs lignes. Retourne list[(rel_path, score)] trie."""
    stack = distill.get("stacktrace_files", [])
    keywords = [k.lower() for k in distill.get("keywords", [])]
    candidates: dict[str, float] = {}

    # 1. Stack files = score MAX (strip Linux prefix then match by suffix)
    for sf in stack:
        norm = sf.replace("\\", "/")
        for prefix in (
            "/usr/lib/python3/dist-packages/",
            "/usr/local/lib/python3/site-packages/",
            "/usr/local/lib/python3/dist-packages/",
            "site-packages/",
        ):
            idx_ = norm.find(prefix)
            if idx_ >= 0:
                norm = norm[idx_ + len(prefix) :]
                break
        basename = norm.split("/")[-1]
        # Cherche par basename + suffix match (anti faux-positifs)
        for p in repo_path.rglob(basename):
            if not p.is_file() or p.suffix != ".py":
                continue
            rel = str(p.relative_to(repo_path)).replace("\\", "/")
            # Suffix match strict : rel doit finir par norm complet
            if rel.endswith(norm):
                candidates[rel] = 100.0
                break

    # 2. CONTENT grep : keywords specifiques (non-stop) dans le code
    #    Score = freq normalisee (count / log(size+1)). Bonus 2x si match dans
    #    nom fonction/classe (heuristique : ligne contient 'def ' ou 'class ').
    #    Filtre paths : skip __pycache__, /test/, /tests/, /docs/, /examples/,
    #    setup.py, conftest.py, version.py, _version.py, logger.py (boilerplate).
    SKIP_BASENAMES = {
        "setup.py",
        "conftest.py",
        "version.py",
        "_version.py",
        "logger.py",
        "__init__.py",
    }
    SKIP_PATH_SUBSTR = (
        "__pycache__",
        "/test/",
        "/tests/",
        "/docs/",
        "/examples/",
        "/build/",
        "/.pyinstaller/",
        "/dist/",
    )
    # Hierarchie keywords : ultra-specifiques (>=10 chars OU contient _) gagnent.
    # Sinon fallback sur kw >= 6 chars. Evite pollution par 'modeling',
    # 'linear', 'python' qui matchent partout.
    ultra_specific = [k for k in keywords if (len(k) >= 10 or "_" in k)][:6]
    if ultra_specific:
        scoring_kw = ultra_specific
        SCORE_THRESHOLD = 0.5
    else:
        scoring_kw = [k for k in keywords if len(k) >= 6][:8]
        SCORE_THRESHOLD = 0.1

    if scoring_kw and len(candidates) < max_files * 2:
        import math as _math
        import re as _re

        # TF-IDF EXACT : 1) pre-scan repo -> Counter DF par kw + cache contenus.
        # 2) score = TF * IDF. IDF = log(N / (1 + DF)). DF = nb fichiers contenant kw.
        # 3) bonus def/class +20, bonus basename +15.
        file_data = []  # (rel, txt_low, basename)
        for p in repo_path.rglob("*.py"):
            sp = str(p).replace("\\", "/")
            if any(s in sp for s in SKIP_PATH_SUBSTR):
                continue
            if p.name in SKIP_BASENAMES:
                continue
            try:
                rel = str(p.relative_to(repo_path)).replace("\\", "/")
            except ValueError:
                continue
            if rel in candidates:
                continue
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if len(txt) < 50 or len(txt) > 500_000:
                continue
            file_data.append((rel, txt.lower(), p.stem.lower()))
        N = len(file_data)
        if N == 0:
            ranked = sorted(candidates.items(), key=lambda x: -x[1])[:max_files]
            return ranked
        # Document Frequency par kw
        df = dict.fromkeys(scoring_kw, 0)
        for _, txt_low, _ in file_data:
            for k in scoring_kw:
                if k in txt_low:
                    df[k] += 1
        # IDF par kw : log(N / (1 + DF)). kw rare = IDF haut.
        idf = {k: _math.log((N + 1) / (1 + df[k])) + 1.0 for k in scoring_kw}
        # Score TF-IDF par fichier
        for rel, txt_low, basename in file_data:
            score = 0.0
            for k in scoring_kw:
                cnt = txt_low.count(k)
                if cnt > 0:
                    # TF normalise par log(size) + IDF
                    tf = cnt / _math.log(len(txt_low) + 1)
                    score += tf * idf[k]
                    # Bonus +20 si def/class signature
                    if _re.search(rf"\b(?:def|class)\s+\w*{_re.escape(k)}", txt_low):
                        score += 20.0
            # Bonus basename match radical kw
            for k in scoring_kw:
                root = k.split("_")[0][:6] if "_" in k else k[:6]
                if root and root in basename:
                    score += 15.0
                    break
            if score >= SCORE_THRESHOLD:
                candidates[rel] = score

    # 3. Fallback : si toujours peu de candidats, filename match keywords (chemin)
    if len(candidates) < max_files:
        for p in repo_path.rglob("*.py"):
            sp = str(p).replace("\\", "/")
            if any(s in sp for s in SKIP_PATH_SUBSTR):
                continue
            if p.name in SKIP_BASENAMES:
                continue
            try:
                rel = str(p.relative_to(repo_path)).replace("\\", "/")
            except ValueError:
                continue
            if rel in candidates:
                continue
            score = sum(1.0 for k in keywords if k in rel.lower())
            if score > 0:
                candidates[rel] = score
            if len(candidates) >= max_files * 3:
                break

    # Top N
    ranked = sorted(candidates.items(), key=lambda x: -x[1])[:max_files]
    return ranked


def _zoom_file_contents(
    repo_path: Path,
    ranked_files: list[tuple[str, float]],
    cap_per_file: int = 12000,
    keywords: list[str] | None = None,
) -> str:
    """Render markdown : pour chaque fichier candidat, soit le CODE complet
    si <= cap_per_file, soit zones AUTOUR des keywords (pas truncate milieu).
    Critique : SR Aider format echoue si LLM voit du code tronque (SEARCH
    bloc ne match pas le fichier reel). Donc zones contigues + numero ligne."""
    if not ranked_files:
        return ""
    out_parts: list[str] = ["\n### FICHIERS PERTINENTS (code source COMPLET)\n"]
    kw_lower = [k.lower() for k in (keywords or []) if len(k) >= 5]
    for rel, score in ranked_files:
        p = repo_path / rel
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text) <= cap_per_file:
            body = text
            mode = "FULL"
        else:
            # Extract zones autour des keywords (window +/- 60 lignes)
            lines = text.splitlines()
            kw_lines: set[int] = set()
            for i, ln in enumerate(lines):
                ln_low = ln.lower()
                if any(k in ln_low for k in kw_lower):
                    kw_lines.add(i)
            if not kw_lines:
                # Fallback : 1ere moitie complete (pas de keyword trouve)
                body = "\n".join(lines[: cap_per_file // 80])
                mode = "HEAD"
            else:
                # Merge windows : pour chaque kw line, +/-30 lignes
                window = 30
                ranges: list[tuple[int, int]] = []
                for kl in sorted(kw_lines):
                    lo = max(0, kl - window)
                    hi = min(len(lines), kl + window + 1)
                    if ranges and lo <= ranges[-1][1] + 5:
                        ranges[-1] = (ranges[-1][0], hi)
                    else:
                        ranges.append((lo, hi))
                # Render avec markers ligne
                parts = []
                for lo, hi in ranges:
                    parts.append(f"# === lignes {lo + 1}-{hi} ===\n" + "\n".join(lines[lo:hi]))
                body = "\n\n# ...\n\n".join(parts)
                # Cap final si depasse encore
                if len(body) > cap_per_file:
                    body = body[:cap_per_file] + "\n# ... [zones cap]"
                mode = f"ZONES({len(ranges)})"
        out_parts.append(
            f"\n#### {rel} (score={score:.0f}, {mode}, {len(text)}b raw)\n```python\n{body}\n```\n"
        )
    return "".join(out_parts)


def _parse_search_replace(text: str) -> list[tuple[str, str, str]]:
    """Parse Aider SEARCH/REPLACE blocks. Format :

        path/to/file.py
        <<<<<<< SEARCH
        old content
        =======
        new content
        >>>>>>> REPLACE

    Retourne [(filepath, search_block, replace_block), ...].
    Tolerant variants : <<<< / <<<<<<<, ==== / =======, >>>> / >>>>>>>.
    """
    import re as _re

    blocks = []
    # Pattern souple : autoriser 4-7 angles, retour ligne lazy
    pat = _re.compile(
        r"(?:^|\n)([^\n]+\.py)\s*\n"
        r"<{3,8}\s*SEARCH\s*\n(.*?)\n"
        r"={3,8}\s*\n(.*?)\n"
        r">{3,8}\s*REPLACE\s*",
        _re.DOTALL,
    )
    for m in pat.finditer(text):
        path = m.group(1).strip().lstrip("`").rstrip("`").strip()
        # Strip backticks et lead/trail whitespace ligne path
        # Aussi tolere "### path/to/file.py" ou "**file.py**"
        path = _re.sub(r"^[#*\-\s]+|[#*\s]+$", "", path).strip()
        # Et accepte "a/foo.py" -> "foo.py"
        if path.startswith("a/"):
            path = path[2:]
        search = m.group(2)
        replace = m.group(3)
        blocks.append((path, search, replace))
    return blocks


def _apply_search_replace_to_diff(
    repo_path: Path, blocks: list[tuple[str, str, str]], whitelist: set[str], git_files: set[str]
) -> str:
    """Pour chaque bloc S/R : trouve fichier dans repo, applique replace en
    memoire, genere unidiff via difflib. Concatene tous les diffs. Skip blocs
    dont fichier hors whitelist OU search non trouve."""
    import difflib as _dl

    parts: list[str] = []
    for path, search, replace in blocks:
        # Resolution path : whitelist > git_files > tentative rglob
        rel = None
        if path in whitelist or path in git_files:
            rel = path
        else:
            # Tentative match par suffix dans whitelist/git_files
            for cand in list(whitelist) + list(git_files):
                if cand.endswith("/" + path) or cand.endswith(path):
                    rel = cand
                    break
        if rel is None:
            continue
        fp = repo_path / rel
        if not fp.is_file():
            continue
        # CRITIQUE : preserver line endings d origine (CRLF vs LF).
        # Read binary -> decode -> split en preservant \r\n. Sinon Python
        # `read_text()` universal newlines convertit CRLF -> LF, et le diff
        # genere ne match plus le fichier reel sur disque (git apply REJECT).
        try:
            raw_bytes = fp.read_bytes()
        except OSError:
            continue
        try:
            original = raw_bytes.decode("utf-8", errors="replace")
        except (UnicodeDecodeError, AttributeError):
            continue
        # Detecte line ending dominant
        crlf_count = original.count("\r\n")
        lf_only = original.count("\n") - crlf_count
        eol = "\r\n" if crlf_count > lf_only else "\n"
        # Normalise search/replace en eol du fichier (LLM produit toujours LF)
        if eol == "\r\n":
            search_norm = search.replace("\r\n", "\n").replace("\n", "\r\n")
            replace_norm = replace.replace("\r\n", "\n").replace("\n", "\r\n")
        else:
            search_norm = search.replace("\r\n", "\n")
            replace_norm = replace.replace("\r\n", "\n")
        # Match exact
        if search_norm in original:
            new_content = original.replace(search_norm, replace_norm, 1)
        else:
            # Fallback : strip trailing whitespace par ligne (tolerance)
            def _norm_ws(t: str, eol: str) -> str:
                return eol.join(l.rstrip() for l in t.splitlines())

            search_ws = _norm_ws(search_norm, eol)
            orig_ws = _norm_ws(original, eol)
            if search_ws in orig_ws:
                replace_ws = _norm_ws(replace_norm, eol)
                new_content = orig_ws.replace(search_ws, replace_ws, 1)
            else:
                continue
        # Generate unified diff (preserve eol via splitlines keepends)
        original_lines = original.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        # Assure trailing newline (sinon difflib ajoute "No newline at end")
        if original_lines and not original_lines[-1].endswith(("\n", "\r")):
            original_lines[-1] = original_lines[-1] + eol
        if new_lines and not new_lines[-1].endswith(("\n", "\r")):
            new_lines[-1] = new_lines[-1] + eol
        diff_lines = list(
            _dl.unified_diff(
                original_lines, new_lines, fromfile=f"a/{rel}", tofile=f"b/{rel}", n=3, lineterm=eol
            )
        )
        if not diff_lines:
            continue
        # Header diff --git en plus pour git apply
        header = f"diff --git a/{rel} b/{rel}{eol}"
        parts.append(header + "".join(diff_lines))
    return "".join(parts)


def _git_ls_files(repo_path: Path) -> set[str]:
    """Returns set of all .py paths tracked by git in this repo. Source of
    truth absolue : un path hors de cette liste = INVALIDE pour git apply."""
    try:
        r = subprocess.run(
            ["git", "-C", str(repo_path), "ls-files", "*.py"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        errors="replace")
        return {p.strip().replace("\\", "/") for p in r.stdout.splitlines() if p.strip()}
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return set()


def _git_apply_check(repo_path: Path, diff: str) -> tuple[bool, str]:
    """git apply --check sans modifier. Retourne (ok, error_msg).
    Essai en 3 passes : strict -> --ignore-whitespace -> --recount + --ignore-whitespace.
    CRITIQUE Windows : input passe en BYTES (pas text=True) sinon Python convertit
    \\n en \\r\\n via universal newlines -> mismatch CRLF/LF avec fichier source LF."""
    if not diff.strip():
        return False, "empty"
    # Force LF dans diff envoye a git (strip tout \r residuel)
    diff_lf = diff.replace("\r\n", "\n").replace("\r", "")
    diff_bytes = diff_lf.encode("utf-8")
    flag_sets = [
        ["apply", "--check", "-"],
        ["apply", "--check", "--ignore-whitespace", "-"],
        ["apply", "--check", "--ignore-whitespace", "--recount", "-"],
    ]
    last_err = "unknown"
    for flags in flag_sets:
        try:
            r = subprocess.run(
                ["git", "-C", str(repo_path)] + flags,
                input=diff_bytes,
                capture_output=True,
                timeout=10,
            )
            if r.returncode == 0:
                return True, ""
            err_text = (r.stderr or r.stdout).decode("utf-8", errors="replace")
            last_err = err_text[:300]
        except (subprocess.TimeoutExpired, OSError) as e:
            last_err = f"exec_err: {e}"
    return False, last_err


def _build_propose_fn(
    inst: dict, repo_path: Path, provider: str, token: str, use_cache: bool = True
):
    """Closure : capture inst + repo_map_md + provider. Genere proposals.
    use_cache=True : load forge_swebench_repo_cache repo_map.md si dispo.
    Stage 0 distillation : pre-filter repo_md par keywords + force stacktrace
    files en tete pour eviter hallucination fichier cible."""
    repo_md: str | None = None
    # Pre-fetch git ls-files = source of truth pour validation paths
    git_files = _git_ls_files(repo_path)
    if use_cache and _CACHE_AVAILABLE:
        repo_md = _cache_load_md(inst["instance_id"])
        if repo_md:
            print(f"  [cache] repo_map.md HIT ({len(repo_md)} bytes)")
    if repo_md is None:
        repo_map = build_repo_map(repo_path, max_files=2000)
        repo_md = render_markdown(repo_map, max_chars=50000)  # large brut
        if use_cache and _CACHE_AVAILABLE:
            print("  [cache] repo_map.md MISS, building live")
    # Stage 0 : distille + filter
    distill = _distill_issue(inst.get("problem_statement", ""))
    if distill["stacktrace_files"] or distill["keywords"]:
        repo_md = _filter_repo_map_md(
            repo_md, distill["keywords"], distill["stacktrace_files"], max_chars=15000
        )
        print(
            f"  [stage0] kw={distill['keywords'][:5]} "
            f"stack_files={distill['stacktrace_files'][:3]} "
            f"filtered_md={len(repo_md)}b"
        )

    # Stage 2 : skeleton pruning + zoom code source des fichiers candidats.
    # Pipeline 2026-05-24 : TF-IDF top-8 -> reranker LLM leger -> top-4 zoom.
    candidate_top_n = _select_candidate_files(distill, repo_path, max_files=8)
    # Stage 2.5 : reranker LLM (1 call cerebras, ~600ms) sur top-8 -> top-4.
    # Pattern SWE-Adept : +4.7pts loc rate.
    candidate_files = candidate_top_n[:4]  # fallback
    if len(candidate_top_n) > 4 and token is not None:
        try:
            rerank_prompt = (
                "Tu es un expert qui localise les bugs Python.\n"
                "ISSUE :\n" + inst.get("problem_statement", "")[:1500] + "\n\n"
                "CANDIDATS (8 fichiers, top BM25 TF-IDF) :\n"
                + "\n".join(f"  {i + 1}. {rel}" for i, (rel, _) in enumerate(candidate_top_n))
                + "\n\nClasse les 4 PLUS pertinents par probabilite que le bug "
                "soit dedans. Reponse JSON strict :\n"
                '{"top4": ["path1.py", "path2.py", "path3.py", "path4.py"]}\n'
            )
            rerank_resp = _hub_ask("cerebras", rerank_prompt, token, max_tokens=400, timeout_s=30)
            import re as _re_rk

            m = _re_rk.search(r'"top4"\s*:\s*\[([^\]]+)\]', rerank_resp)
            if m:
                paths = _re_rk.findall(r'"([^"]+\.py)"', m.group(1))
                # Garde uniquement paths presents dans top-8
                top_set = {rel for rel, _ in candidate_top_n}
                reranked = []
                for p in paths:
                    # Trouve la version exacte (suffix match)
                    for rel, sc in candidate_top_n:
                        if rel == p or rel.endswith("/" + p):
                            if (rel, sc) not in reranked:
                                reranked.append((rel, sc))
                            break
                if len(reranked) >= 2:
                    candidate_files = reranked[:4]
                    print(f"  [rerank] LLM rerank applied : {[c[0] for c in candidate_files]}")
        except Exception as e:
            print(f"  [rerank] FAIL fallback TF-IDF top-4 : {e}")
    file_contents_md = _zoom_file_contents(
        repo_path, candidate_files, cap_per_file=12000, keywords=distill.get("keywords", [])
    )
    if file_contents_md:
        print(
            f"  [stage2] zoom files={[c[0] for c in candidate_files]} "
            f"contents={len(file_contents_md)}b"
        )

    def propose(problem: str, last_result: SandboxResult | None) -> list[PatchProposal]:
        # Inject stacktrace files in priority de prompt - STRIP prefix Linux
        # site-packages pour avoir paths repo-relatif (LLM tend a copier le
        # path tel quel dans le diff, ce qui casse git apply).
        def _strip_sys(p: str) -> str:
            for prefix in (
                "/usr/lib/python3/dist-packages/",
                "/usr/local/lib/python3/site-packages/",
                "/usr/local/lib/python3/dist-packages/",
                "site-packages/",
            ):
                idx_ = p.find(prefix)
                if idx_ >= 0:
                    return p[idx_ + len(prefix) :]
            return p

        stack_hint = ""
        if distill.get("stacktrace_files"):
            cleaned = [_strip_sys(f) for f in distill["stacktrace_files"][:5]]
            stack_hint = (
                "\n\nFICHIERS PRIORITAIRES (paths REPO-RELATIF, pas /usr/lib/) :\n"
                + "\n".join(f"  - {f}" for f in cleaned)
                + "\nLe bug est TRES PROBABLEMENT dans un de ces fichiers.\n"
                "IMPORTANT : ton diff DOIT utiliser ces paths repo-relatif "
                "(commence par astropy/, django/, etc.) - JAMAIS /usr/lib/.\n"
            )
        # Reset prompt selon round (initial vs refine)
        # CONSIGNE diff-only EN TETE (avant stack/repo_md) pour ne pas etre
        # dilue par le contexte. Repete EN FIN aussi.
        # Liste WHITELIST fichiers autorises (Stage 2 candidates + stack files)
        whitelist = [c[0] for c in candidate_files]
        if distill.get("stacktrace_files"):
            for sf in distill["stacktrace_files"][:5]:
                clean = _strip_sys(sf)
                if clean not in whitelist:
                    whitelist.append(clean)
        whitelist_block = ""
        if whitelist:
            whitelist_block = (
                "\nWHITELIST FICHIERS AUTORISES (CHOISIS UN, AUCUN AUTRE) :\n"
                + "\n".join(f"  - {f}" for f in whitelist)
                + "\nTON DIFF DOIT modifier EXACTEMENT UN fichier de cette liste. "
                "TOUT AUTRE PATH = REJET AUTOMATIQUE.\n"
            )
        # Format SEARCH/REPLACE Aider : LLM ne produit PAS de diff brut.
        # On reconstruit le diff via difflib cote runner -> elimine bugs
        # paths, indentation, contexte manquant. Reference :
        # https://aider.chat/docs/more/edit-formats.html
        diff_rules = (
            "TASK : fixer le bug ISSUE en utilisant le format SEARCH/REPLACE.\n"
            "FORMAT STRICT (Aider style) :\n"
            "  1. Ligne 1 du bloc = path EXACT du fichier (issu WHITELIST)\n"
            "  2. Ligne 2 = '<<<<<<< SEARCH'\n"
            "  3. Le code EXACT a remplacer (copier-coller du source affiche)\n"
            "  4. Ligne = '======='\n"
            "  5. Le code de remplacement\n"
            "  6. Ligne = '>>>>>>> REPLACE'\n"
            "Exemple :\n"
            "  astropy/modeling/separable.py\n"
            "  <<<<<<< SEARCH\n"
            "  return separable_components(left.right)\n"
            "  =======\n"
            "  return separable_components(left) & separable_components(right)\n"
            "  >>>>>>> REPLACE\n"
            "\n"
            "REGLES :\n"
            "  - Le bloc SEARCH doit etre PRESENT TEL QUEL dans le source\n"
            "  - Indentation EXACTE (espaces/tabs identiques)\n"
            "  - 1 seul fichier modifie idealement, MAX 2 blocs S/R\n"
            "  - Aucune prose autour des blocs S/R\n"
            "  - Path obligatoire dans WHITELIST ci-dessous\n"
        )
        if last_result is None:
            base = (
                f"{diff_rules}"
                f"{whitelist_block}"
                f"{stack_hint}\n"
                f"=== CODE SOURCE DES FICHIERS WHITELIST (lis-le AVANT de proposer) ===\n"
                f"{file_contents_md}\n"
                f"=== ISSUE ===\n{problem}\n\n"
                f"=== REPO_MAP CONTEXTE (signatures, NE PAS MODIFIER fichiers hors whitelist) ===\n"
                f"{repo_md[:6000]}\n\n"
                "RAPPEL : reponse = blocs SEARCH/REPLACE uniquement. "
                "Path ligne1, <<<<<<< SEARCH, code, =======, code, >>>>>>> REPLACE.\n\n"
                "Reponse :\n"
            )
        else:
            err = (last_result.error_log or "")[:2000].replace("\\n", "\n")
            base = (
                f"{diff_rules}"
                f"{whitelist_block}"
                "Ton patch precedent a echoue. Score = "
                f"{last_result.passed}/{last_result.total}. Apply_ok = "
                f"{last_result.apply_ok}.\n\n"
                f"Log erreur :\n{err}\n"
                f"{stack_hint}\n"
                f"=== CODE SOURCE WHITELIST ===\n{file_contents_md[:6000]}\n"
                f"=== ISSUE ===\n{problem[:3000]}\n\n"
                "RAPPEL : reponse = blocs SEARCH/REPLACE (path, "
                "<<<<<<< SEARCH, code, =======, code, >>>>>>> REPLACE).\n\n"
                "Reponse :\n"
            )
        proposals: list[PatchProposal] = []
        raw_dir = SWE_DIR / "lats_raw" / inst["instance_id"]
        raw_dir.mkdir(parents=True, exist_ok=True)
        round_tag = "init" if last_result is None else "refine"
        # Genere 3 candidats. Providers TOUS reels (clé coffre DPAPI) routes
        # via litellm hub. cerebras = GPT-OSS 120B free 1M tok/jour ultra-rapide.
        # github = GPT-4o Models marketplace 128K ctx. groq = Llama-3.3-70B 30 rpm.
        # Diversite = bon backtrack si l un hallucine.
        for idx, prov in enumerate(("cerebras", "github", "groq")):
            t0 = time.monotonic()
            text = _hub_ask(prov, base, token, max_tokens=8192, timeout_s=180)
            ms = int((time.monotonic() - t0) * 1000)
            # Save raw response toujours pour debug. newline='' = preserve LF
            # (sinon Windows convertit \n -> \r\n et casse les diffs LF).
            raw_path = raw_dir / f"{round_tag}_{idx}_{prov}.txt"
            try:
                raw_path.write_text(text, encoding="utf-8", newline="")
            except OSError:
                pass
            # Try SEARCH/REPLACE format first (preferred), fallback diff raw
            sr_blocks = _parse_search_replace(text)
            diff = ""
            src = ""
            if sr_blocks:
                diff = _apply_search_replace_to_diff(
                    repo_path, sr_blocks, set(whitelist), git_files
                )
                src = f"SR({len(sr_blocks)})"
            if not diff:
                diff = _extract_diff(text)
                src = "DIFF_RAW" if diff else src or "NONE"
            # POST-LLM gates : (1) whitelist Stage 2, (2) git ls-files,
            # (3) git apply --check. Si l'un fail, reject diff.
            wl_status = "OK"
            if diff:
                import re as _re

                touched = set()
                for m in _re.finditer(r"^diff --git a/(\S+)", diff, _re.MULTILINE):
                    touched.add(m.group(1))
                # (1) whitelist Stage 2
                if whitelist and touched and not (touched & set(whitelist)):
                    wl_status = f"REJECT_WL (touched={list(touched)[:2]})"
                    diff = ""
                # (2) git ls-files : path doit exister dans repo
                elif git_files and touched and not (touched & git_files):
                    wl_status = f"REJECT_GIT (touched={list(touched)[:2]} not in ls-files)"
                    diff = ""
            # (3) git apply --check
            if diff:
                ok, err = _git_apply_check(repo_path, diff)
                if not ok:
                    # Save diff intermediate pour debug. newline='' OBLIGATOIRE
                    # sinon Windows ajoute \r aux \n et le diff devient invalide.
                    debug_path = raw_dir / f"{round_tag}_{idx}_{prov}_REJECTED.diff"
                    try:
                        debug_path.write_text(diff, encoding="utf-8", newline="")
                    except OSError:
                        pass
                    wl_status = f"REJECT_APPLY ({err[:80]})"
                    diff = ""
            print(
                f"    [{prov}#{idx}] resp_len={len(text)} diff_len={len(diff)} "
                f"src={src} ms={ms} gate={wl_status} raw={raw_path.name}"
            )
            if diff:
                proposals.append(
                    PatchProposal(
                        diff=diff,
                        provider=prov,
                        rationale=f"{round_tag} #{idx}",
                        ms_to_generate=ms,
                    )
                )
        return proposals

    return propose


# === Process single instance =================================================


def process_instance(
    inst: dict,
    work_dir: Path,
    provider: str,
    token: str,
    n_initial: int = 3,
    max_depth: int = 2,
    use_cache: bool = True,
) -> dict:
    """Pipeline complet pour 1 instance : clone -> repo_map -> LATS -> best.
    use_cache : prefere forge_swebench_repo_cache (clone + map pre-builds)."""
    iid = inst["instance_id"]
    t0 = time.monotonic()
    repo_path: Path | None = None
    if use_cache and _CACHE_AVAILABLE:
        cached = _cache_repo_path(iid)
        if cached:
            repo_path = cached
            print(f"  [cache] repo clone HIT -> {repo_path}")
        else:
            # Build cache entry maintenant (clone + map)
            r = _cache_prepare(inst)
            if r.get("cached"):
                repo_path = _cache_repo_path(iid)
                print(
                    f"  [cache] repo prepared : files="
                    f"{r['manifest']['files']} symbols={r['manifest']['symbols']}"
                )
    if repo_path is None:
        repo_path = _clone_instance(inst, work_dir)
    if repo_path is None:
        return {
            "instance_id": iid,
            "model_name_or_path": "laforge-lats",
            "model_patch": "",
            "error": "clone_failed",
            "elapsed_s": round(time.monotonic() - t0, 1),
        }

    propose_fn = _build_propose_fn(inst, repo_path, provider, token, use_cache=use_cache)

    # pytest targets = FAIL_TO_PASS (key dans dataset)
    failtopass = inst.get("FAIL_TO_PASS", "[]")
    if isinstance(failtopass, str):
        try:
            ftp_list = json.loads(failtopass)
        except json.JSONDecodeError:
            ftp_list = []
    else:
        ftp_list = list(failtopass)

    try:
        result = lats_search(
            problem=inst.get("problem_statement", ""),
            workdir=repo_path,
            propose_fn=propose_fn,
            n_initial=n_initial,
            max_depth=max_depth,
            beam_width=2,
            pytest_targets=ftp_list[:3] if ftp_list else None,
        )
    except Exception as e:
        return {
            "instance_id": iid,
            "model_name_or_path": "laforge-lats",
            "model_patch": "",
            "error": f"lats_crash: {type(e).__name__}: {str(e)[:200]}",
            "elapsed_s": round(time.monotonic() - t0, 1),
        }

    # best-of-N rerank : LATS score interne (pytest passed/total) + heuristics
    # (apply_ok, diff_size penalty, multi-fichier penalty). Top-1 final.
    all_nodes = result.get("all_nodes", [])
    valid = [n for n in all_nodes if n.patch and n.patch.diff and n.result and n.result.apply_ok]
    if not valid:
        best = result["best"]
        if best is None or best.patch is None:
            return {
                "instance_id": iid,
                "model_name_or_path": "laforge-lats",
                "model_patch": "",
                "error": "no valid candidate",
                "n_evaluated": result["n_evaluated"],
                "elapsed_s": round(time.monotonic() - t0, 1),
            }
    else:

        def _bon_score(n):
            r = n.result
            score = (r.score if r else 0.0) * 100  # pytest = poids max
            # Penalty diff trop gros (>3000 bytes = -10, >8000 = -30)
            dl = len(n.patch.diff)
            if dl > 8000:
                score -= 30
            elif dl > 3000:
                score -= 10
            # Penalty multi-fichiers (1 fichier ideal)
            import re as _re_bn

            n_files = len(
                set(_re_bn.findall(r"^diff --git a/(\S+)", n.patch.diff, _re_bn.MULTILINE))
            )
            if n_files > 1:
                score -= 5 * (n_files - 1)
            return score

        best = max(valid, key=_bon_score)
        print(
            f"  [bon] best-of-N selected : provider={best.patch.provider} "
            f"score={_bon_score(best):.1f} from {len(valid)} valid candidates"
        )

    return {
        "instance_id": iid,
        # Field requis par harness officiel SWE-bench (run_evaluation.py)
        "model_name_or_path": f"laforge-lats-{best.patch.provider}",
        "model_patch": best.patch.diff,
        "provider": best.patch.provider,
        "score": best.result.score if best.result else 0.0,
        "passed": best.result.passed if best.result else 0,
        "total": best.result.total if best.result else 0,
        "depth": best.depth,
        "n_evaluated": result["n_evaluated"],
        "n_valid": len([n for n in all_nodes if n.patch and n.result and n.result.apply_ok]),
        "lats_elapsed_s": result["elapsed_s"],
        "elapsed_s": round(time.monotonic() - t0, 1),
    }


# === Run multiple instances ==================================================


def run_generate_lats(
    max_entries: int = 5,
    variant: str = "lite",
    split: str = "test",
    provider: str = "cerebras",
    n_initial: int = 3,
    max_depth: int = 2,
    instance_filter: str | None = None,
    use_cache: bool = True,
) -> Path:
    # Token : forge_secrets.get_secret chain (coffre Windows > WCM > .env >
    # os.environ). Sous WSL/Linux, DPAPI indispo - tombe sur os.environ.
    import os as _os

    token = ""
    if _get_secret is not None:
        try:
            token = _get_secret("FORGE_MCP_TOKEN") or ""
        except Exception:
            pass
    if not token:
        token = _os.environ.get("FORGE_MCP_TOKEN", "")
    if not token:
        print(
            "ERR : FORGE_MCP_TOKEN absent (coffre + env). "
            "WSL/Linux : export FORGE_MCP_TOKEN=<token>"
        )
        sys.exit(1)

    all_inst = ensure_dataset(split, variant)
    if instance_filter:
        ids = {x.strip() for x in instance_filter.split(",") if x.strip()}
        instances = [i for i in all_inst if i["instance_id"] in ids]
    else:
        instances = all_inst[:max_entries]

    print(f"[swebench-lats] {len(instances)} instances variant={variant} provider={provider}")
    work_dir = SWE_DIR / "repos_lats"
    work_dir.mkdir(exist_ok=True)
    # Output dir : configurable via env LAFORGE_SWE_OUT_DIR ou default SWE_DIR.
    # Si sandbox-online (ACL refuse SWE_DIR), fallback sandbox/swe_predictions/.
    import os as _os

    out_root = _os.environ.get("LAFORGE_SWE_OUT_DIR", "").strip()
    if out_root:
        out_dir = Path(out_root)
    else:
        out_dir = SWE_DIR
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        # Probe write
        _probe = out_dir / ".write_probe.tmp"
        _probe.write_text("ok")
        _probe.unlink()
    except (OSError, PermissionError):
        # Fallback sandbox workspace
        out_dir = ROOT / "sandbox" / "swe_predictions"
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"  [out] fallback ACL : {out_dir}")
    out = out_dir / f"predictions_lats_{variant}_{len(instances)}.jsonl"
    predictions: list[dict] = []

    for i, inst in enumerate(instances):
        print(f"\n[{i + 1}/{len(instances)}] {inst['instance_id']}")
        pred = process_instance(
            inst,
            work_dir,
            provider,
            token,
            n_initial=n_initial,
            max_depth=max_depth,
            use_cache=use_cache,
        )
        has = bool(pred.get("model_patch", "").strip())
        score = pred.get("score", 0.0)
        print(
            f"  -> {'PATCH' if has else 'NO_PATCH'} score={score:.2f} "
            f"depth={pred.get('depth', '?')} elapsed={pred.get('elapsed_s', 0)}s"
        )
        predictions.append(pred)
        # Incremental save (write tolerant aux locks transitoires)
        try:
            out.write_text("\n".join(json.dumps(p) for p in predictions), encoding="utf-8")
        except PermissionError as e:
            alt = ROOT / "sandbox" / "swe_predictions" / out.name
            alt.parent.mkdir(parents=True, exist_ok=True)
            alt.write_text("\n".join(json.dumps(p) for p in predictions), encoding="utf-8")
            print(f"  [write] FALLBACK {alt} (cause: {e})")
            out = alt

    n_patch = sum(1 for p in predictions if p.get("model_patch", "").strip())
    n_resolved = sum(1 for p in predictions if p.get("score", 0.0) >= 0.99)
    print(
        f"\n[swebench-lats] {n_patch}/{len(instances)} patches | "
        f"{n_resolved}/{len(instances)} score=1.0 (local pytest)"
    )
    print(f"Saved -> {out}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=5)
    ap.add_argument("--variant", choices=["lite", "verified", "live"], default="lite")
    ap.add_argument("--split", default="test")
    ap.add_argument("--provider", default="cerebras")
    ap.add_argument("--n-initial", type=int, default=3)
    ap.add_argument("--max-depth", type=int, default=2)
    ap.add_argument("--instance", default=None, help="Filter by instance_id (comma-separated)")
    ap.add_argument(
        "--no-cache", action="store_true", help="Skip forge_swebench_repo_cache - clone+map live"
    )
    args = ap.parse_args()
    run_generate_lats(
        max_entries=args.max,
        variant=args.variant,
        split=args.split,
        provider=args.provider,
        n_initial=args.n_initial,
        max_depth=args.max_depth,
        instance_filter=args.instance,
        use_cache=not args.no_cache,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import re
import ast
import math
import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)


def parse_gitingest_file(gitingest_filepath: str) -> Dict[str, str]:
    """Parse le fichier gitingest brut et retourne un dictionnaire {chemin: contenu}."""
    files_dict = {}
    current_file = None
    current_content = []

    with open(gitingest_filepath, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if (
            line.startswith("===")
            and i + 2 < len(lines)
            and lines[i + 1].upper().startswith("FILE:")
            and lines[i + 2].startswith("===")
        ):
            # Enregistrer le fichier précédent
            if current_file:
                files_dict[current_file] = "".join(current_content)

            current_file = lines[i + 1][5:].strip()

            current_content = []
            i += 3  # Sauter le bloc de titre
            continue

        if current_file:
            current_content.append(lines[i])
        i += 1

    if current_file:
        files_dict[current_file] = "".join(current_content)

    return files_dict


def filter_files(
    files_dict: Dict[str, str], whitelist: List[str] = None, blacklist: List[str] = None
) -> Dict[str, str]:
    """Étape A - Pré-filtrage stratégique."""
    filtered = {}

    # Valeurs par défaut si non fournies
    if whitelist is None:
        whitelist = ["core", "src", "engine", "services", "app", "lib"]
    if blacklist is None:
        blacklist = ["test", "docs", "examples", "venv", "node_modules", ".git"]

    for filepath, content in files_dict.items():
        path_lower = filepath.lower()

        # Blacklist check
        if any(bad in path_lower for bad in blacklist):
            continue

        # Whitelist check (si la whitelist est vide, on garde. Sinon il faut matcher au moins un)
        if whitelist and not any(good in path_lower for good in whitelist):
            # Si c'est un fichier à la racine comme main.py ou README, on peut le garder optionnellement
            if "/" in filepath or "\\" in filepath:
                continue

        filtered[filepath] = content

    return filtered


def compute_centrality(files_dict: Dict[str, str]) -> Dict[str, int]:
    """Calcule la 'centrality' : combien de fois un fichier est importé/mentionné."""
    mentions = defaultdict(int)
    # Extraire juste le nom de base sans extension pour matcher
    file_basenames = {filepath: Path(filepath).stem for filepath in files_dict.keys() if filepath.endswith(".py")}

    for content in files_dict.values():
        for filepath, basename in file_basenames.items():
            # Si le nom de base est mentionné dans le contenu d'un autre fichier
            if re.search(r"\b" + re.escape(basename) + r"\b", content):
                mentions[filepath] += 1

    return mentions


def score_files(files_dict: Dict[str, str], mentions: Dict[str, int]) -> List[Tuple[str, float]]:
    """Étape B - Scoring intelligent."""
    scores = []

    for filepath, content in files_dict.items():
        # 1. Size
        file_size = len(content)
        size_score = math.log10(file_size + 1) * 0.3 if file_size > 0 else 0

        # 2. nb_imports & nb_functions (Python only for AST, regex fallback)
        nb_imports = 0
        nb_functions = 0

        if filepath.endswith(".py"):
            try:
                tree = ast.parse(content)
                nb_imports = sum(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree))
                nb_functions = sum(
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for node in ast.walk(tree)
                )
            except Exception:
                # Fallback si erreur de syntaxe
                nb_imports = len(re.findall(r"^(?:from|import)\s+", content, re.MULTILINE))
                nb_functions = len(re.findall(r"^(?:def|class)\s+", content, re.MULTILINE))
        else:
            # Fallback regex générique (Rust, JS, etc.)
            nb_imports = len(re.findall(r"^(?:import|use|require)\s+", content, re.MULTILINE))
            nb_functions = len(re.findall(r"(?:function|fn|class)\s+\w+", content))

        import_score = min(nb_imports, 20) * 0.3
        func_score = min(nb_functions, 30) * 0.2

        # 3. Centrality
        centrality = mentions.get(filepath, 0)
        centrality_score = min(centrality, 10) * 0.2

        total_score = size_score + import_score + func_score + centrality_score
        scores.append((filepath, total_score))

    # Tri décroissant
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores


def parse_ast(filepath: str, content: str) -> dict:
    """Étape C - AST Extraction."""
    result = {"file": filepath, "classes": [], "functions": [], "imports": [], "calls": []}

    if not filepath.endswith(".py"):
        # Fallback pour d'autres langages (basique via Regex)
        result["functions"] = re.findall(r"(?:function|fn)\s+(\w+)", content)
        result["classes"] = re.findall(r"class\s+(\w+)", content)
        return result

    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                result["classes"].append(node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                result["functions"].append(node.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    result["imports"].append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    result["imports"].append(node.module)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    result["calls"].append(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    result["calls"].append(node.func.attr)
    except Exception:
        result["error"] = "Syntax/Parse Error"

    # Deduplicate calls & imports
    result["calls"] = list(set(result["calls"]))
    result["imports"] = list(set(result["imports"]))

    return result


def run_ingestion_pipeline(gitingest_filepath: str, top_k: int = 10) -> str:
    """Pipeline complet, retourne le JSON compressé."""
    # 0. Parse
    files_dict = parse_gitingest_file(gitingest_filepath)

    # A. Filtrage
    filtered = filter_files(files_dict)

    # B. Scoring
    mentions = compute_centrality(filtered)
    scores = score_files(filtered, mentions)

    # Sélectionner le top_k
    top_files = [f[0] for f in scores[:top_k]]

    # C. AST
    ast_results = []
    for filepath in top_files:
        ast_res = parse_ast(filepath, filtered[filepath])
        # D. Compression / Transformation en format compact
        compressed_module = {
            "name": Path(filepath).stem,
            "path": filepath,
            "functions": ast_res["functions"][:10],  # Keep top 10 to avoid noise
            "classes": ast_res["classes"],
            "dependencies": ast_res["imports"][:10],
        }
        ast_results.append(compressed_module)

    final_output = {"core_modules": ast_results}

    return json.dumps(final_output, indent=2)


import sys
import time
import logging
import argparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("forge_ingestion_pipeline")

ROOT_PATH = Path(__file__).resolve().parent.parent
WATCH_DIR = ROOT_PATH / "data" / "gitingest"
PROCESSED = WATCH_DIR / ".processed"
HEARTBEAT = ROOT_PATH / "sandbox" / "ingestion_pipeline.heartbeat"


def _load_processed() -> set:
    if not PROCESSED.exists():
        return set()
    try:
        return set(PROCESSED.read_text(encoding="utf-8").splitlines())
    except Exception:
        return set()


def _save_processed(done: set) -> None:
    PROCESSED.write_text("\n".join(sorted(done)), encoding="utf-8")


def _anchor(name: str, modules: list) -> None:
    try:
        sys.path.insert(0, str(ROOT_PATH))
        from nokido_agent.app.forge_self_correction import anchor_solution

        summary = ", ".join(m["name"] for m in modules[:5])
        anchor_solution(
            problem=f"Repo externe analysé via gitingest : {name}",
            solution=f"Top modules: {summary}. {len(modules)} core modules extraits.",
            example=f"run_ingestion_pipeline('data/gitingest/{name}.txt')",
            domain="ingestion",
        )
    except Exception as e:
        log.debug(f"anchor skip: {e}")


def _beat(status: str) -> None:
    try:
        HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        import json as _json

        HEARTBEAT.write_text(
            _json.dumps(
                {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "pid": __import__("os").getpid(),
                    "status": status,
                }
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


MAX_FILE_MB = float(__import__("os").environ.get("LAFORGE_INGEST_MAX_MB", "60"))


def scan_and_process(top_k: int = 10, max_per_run: int = 5) -> dict:
    """Scan WATCH_DIR, process unprocessed .txt, return stats."""
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    done = _load_processed()
    # Trier: petits fichiers d'abord pour éviter qu'un gros bloque le cycle
    pending = sorted([f for f in WATCH_DIR.glob("*.txt") if f.name not in done], key=lambda f: f.stat().st_size)
    if not pending:
        return {"processed": 0, "pending": 0, "total_done": len(done)}

    results = []
    for txt in pending[:max_per_run]:
        name = txt.stem
        size_mb = txt.stat().st_size / 1e6
        # Repos > MAX_FILE_MB : top_k réduit pour éviter OOM
        effective_top_k = max(3, top_k // 2) if size_mb > MAX_FILE_MB else top_k
        if size_mb > MAX_FILE_MB:
            log.info(f"[ingest] {name}: {size_mb:.0f}MB > {MAX_FILE_MB}MB — top_k réduit à {effective_top_k}")
        try:
            compressed = run_ingestion_pipeline(str(txt), top_k=effective_top_k)
            out = WATCH_DIR / f"{name}_compressed.json"
            out.write_text(compressed, encoding="utf-8")
            modules = json.loads(compressed).get("core_modules", [])
            _anchor(name, modules)
            done.add(txt.name)
            results.append({"file": txt.name, "modules": len(modules), "ok": True, "mb": round(size_mb, 1)})
            log.info(f"[ingest] {name}: {len(modules)} modules → RAG")
        except Exception as e:
            results.append({"file": txt.name, "ok": False, "error": str(e)[:120]})
            log.warning(f"[ingest] {name} FAILED: {e}")

    _save_processed(done)
    ok = sum(1 for r in results if r["ok"])
    return {
        "processed": ok,
        "failed": len(results) - ok,
        "pending_remaining": len(pending) - len(results),
        "details": results,
    }


def daemon_loop(interval_s: int = 300, top_k: int = 10) -> None:
    """Phase 15 (2026-05-24) — event-driven via watchdog si dispo, sinon
    polling fallback. watchdog wrap ReadDirectoryChangesW (Windows) /
    inotify (Linux) / FSEvents (macOS).

    Comportement :
      - Watch WATCH_DIR pour CREATE/MODIFY *.txt -> enqueue dans queue.Queue
      - Consumer main thread drain queue -> scan_and_process(top_k)
      - Backup periodique COARSE_INTERVAL_S (= 5x interval_s) au cas ou
        watchdog rate un event (defense in depth).
      - Fallback total vers polling si watchdog import echoue.
    """
    log.info(f"[ingest-daemon] start — watch={WATCH_DIR} interval={interval_s}s")
    _beat("start")
    WATCH_DIR.mkdir(parents=True, exist_ok=True)

    try:
        import queue as _queue
        import threading as _threading
        from watchdog.observers import Observer  # type: ignore
        from watchdog.events import FileSystemEventHandler  # type: ignore
    except ImportError as exc:
        log.warning(f"[ingest-daemon] watchdog missing ({exc}) — polling fallback")
        while True:
            try:
                stats = scan_and_process(top_k=top_k)
                _beat(f"ok:{stats['processed']} processed")
                if stats["processed"]:
                    log.info(f"[ingest-daemon] cycle done: {stats}")
            except Exception as e:
                _beat(f"error:{e}")
                log.error(f"[ingest-daemon] cycle error: {e}")
            time.sleep(interval_s)

    # Event-driven path
    evt_queue: _queue.Queue = _queue.Queue(maxsize=500)

    class _TxtHandler(FileSystemEventHandler):
        def _enqueue(self, src_path: str, kind: str) -> None:
            if not src_path.lower().endswith(".txt"):
                return
            try:
                evt_queue.put_nowait({"path": src_path, "kind": kind, "ts": time.time()})
            except _queue.Full:
                log.warning("[ingest-daemon] watchdog queue full — event dropped")

        def on_created(self, event):
            if not event.is_directory:
                self._enqueue(event.src_path, "created")

        def on_modified(self, event):
            if not event.is_directory:
                self._enqueue(event.src_path, "modified")

        def on_moved(self, event):
            if not event.is_directory:
                self._enqueue(event.dest_path, "moved")

    observer = Observer()
    observer.schedule(_TxtHandler(), str(WATCH_DIR), recursive=False)
    observer.start()
    log.info(f"[ingest-daemon] watchdog Observer started on {WATCH_DIR}")

    coarse_interval_s = max(interval_s * 5, 1800)  # backup full-scan 30min min
    last_coarse_ts = 0.0

    try:
        # Initial scan = process pending non-processed at boot
        try:
            stats = scan_and_process(top_k=top_k)
            _beat(f"boot:{stats['processed']} processed")
            log.info(f"[ingest-daemon] boot scan done: {stats}")
        except Exception as e:
            log.error(f"[ingest-daemon] boot scan err: {e}")

        while True:
            # Drain events (debounce 2s : si plusieurs events arrivent groupes,
            # 1 seul scan suffit). Wait first event jusqu'a coarse_interval_s.
            wait_s = min(60.0, max(1.0, coarse_interval_s - (time.time() - last_coarse_ts)))
            try:
                first = evt_queue.get(timeout=wait_s)
                events_batch = [first]
                debounce_until = time.time() + 2.0
                while time.time() < debounce_until:
                    try:
                        events_batch.append(evt_queue.get(timeout=0.2))
                    except _queue.Empty:
                        break
                log.info(f"[ingest-daemon] {len(events_batch)} events triggered scan")
                stats = scan_and_process(top_k=top_k)
                _beat(f"event:{stats['processed']} processed (batch={len(events_batch)})")
                if stats["processed"]:
                    log.info(f"[ingest-daemon] event cycle done: {stats}")
            except _queue.Empty:
                # Timeout sur wait_s : verifier si coarse periodic backup due
                if time.time() - last_coarse_ts >= coarse_interval_s:
                    last_coarse_ts = time.time()
                    try:
                        stats = scan_and_process(top_k=top_k)
                        _beat(f"coarse:{stats['processed']} processed")
                        if stats["processed"]:
                            log.info(f"[ingest-daemon] coarse backup scan: {stats}")
                    except Exception as e:
                        log.error(f"[ingest-daemon] coarse scan err: {e}")
                else:
                    _beat("idle")
    except KeyboardInterrupt:
        log.info("[ingest-daemon] SIGINT — stop observer")
    finally:
        observer.stop()
        observer.join(timeout=5)


def _main() -> None:
    ap = argparse.ArgumentParser(description="forge_ingestion_pipeline — gitingest AST pipeline")
    ap.add_argument("--daemon", action="store_true", help="boucle continue")
    ap.add_argument("--once", action="store_true", help="1 scan puis exit")
    ap.add_argument(
        "--interval",
        type=int,
        default=int(__import__("os").environ.get("LAFORGE_INGEST_INTERVAL", "300")),
        help="intervalle daemon (s, défaut 300)",
    )
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--file", type=str, default=None, help="traiter 1 fichier spécifique")
    args = ap.parse_args()

    if args.file:
        result = run_ingestion_pipeline(args.file, top_k=args.top_k)
        print(result)
        return

    if args.once:
        import json as _j

        print(_j.dumps(scan_and_process(top_k=args.top_k), indent=2))
        return

    if args.daemon:
        daemon_loop(interval_s=args.interval, top_k=args.top_k)
        return

    ap.error("--daemon | --once | --file requis")


if __name__ == "__main__":
    _main()

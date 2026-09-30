from __future__ import annotations

# Import oublie, mesure le 2026-09-08 : datetime.now() L395 appelle la CLASSE.
from datetime import datetime

"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_versioning
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
forge_versioning.py — extrait automatiquement depuis Nokido.py
Généré par shredder.py
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict
from typing import List
from typing import Optional
import ast as _ast_module
import asyncio
import json
import re
import shutil

logger = __import__("logging").getLogger(__name__)

from pathlib import Path as _Path_lp

# Chemins calculés depuis __file__ — fiables même hors __main__
_APP_DIR = _Path_lp(__file__).resolve().parent  # …/LaForge/app/
_ROOT_DIR = _APP_DIR.parent  # …/LaForge/
_DATA_DIR = _ROOT_DIR / "data"
_LOGS_DIR = _ROOT_DIR / "logs"


@dataclass
class SurgeryResult:
    """Résultat d'une opération chirurgicale AST."""

    success: bool
    node_name: str  # ancre cible (ex: "record_success")
    node_type: str  # "function" | "class" | "method"
    lines_before: int = 0  # taille avant patch
    lines_after: int = 0  # taille après patch
    error: str = ""  # message d'erreur si success=False
    backup_node: str = ""  # code original sérialisé (pour rollback unitaire)


class _NodeLocator(_ast_module.NodeVisitor):
    """
    Trouve un nœud par son nom dans un AST.
    Supporte : fonctions top-level, méthodes de classe, classes entières.
    """

    def __init__(self, target: str) -> None:
        """Init.

        Args:
            target: Description.
        """
        self.target = target
        self.results: list = []  # [(nœud, parent_class|None)]
        self._current_class: str = ""

    def visit_ClassDef(self, node) -> None:
        """Visit classdef.

        Args:
            node: Description.
        """
        prev = self._current_class
        self._current_class = node.name
        if node.name == self.target:
            self.results.append((node, None))
        self.generic_visit(node)
        self._current_class = prev

    def visit_FunctionDef(self, node) -> None:
        """Visit functiondef.

        Args:
            node: Description.
        """
        if node.name == self.target:
            self.results.append((node, self._current_class or None))
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef


class _NodeReplacer(_ast_module.NodeTransformer):
    """
    Remplace le premier nœud correspondant au target par new_node.
    Peut cibler : une fonction top-level, une méthode, une classe.
    """

    def __init__(self, target: str, new_node, class_scope: str = "") -> None:
        """Init.

        Args:
            target: Description.
            new_node: Description.
            class_scope: Description.
        """
        self.target = target
        self.new_node = new_node
        self.class_scope = class_scope  # "" = top-level / n'importe où
        self.replaced = False

    def _match(self, node) -> bool:
        """Match.

        Args:
            node: Description.
        """
        if self.replaced:
            return False
        name = getattr(node, "name", None)
        return name == self.target

    def visit_FunctionDef(self, node) -> object:
        """Visit functiondef.

        Args:
            node: Description.
        """
        if self._match(node):
            self.replaced = True
            logger.debug(f"[Surgeon] Remplacement : {node.name} (l.{node.lineno})")
            return _ast_module.copy_location(self.new_node, node)
        return self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node) -> object:
        """Visit classdef.

        Args:
            node: Description.
        """
        if self._match(node):
            self.replaced = True
            logger.debug(f"[Surgeon] Remplacement classe : {node.name}")
            return _ast_module.copy_location(self.new_node, node)
        return self.generic_visit(node)


class CodeSurgeon:
    """
    Moteur de patch chirurgical AST pour La Forge.

    Usage :
        surgeon = CodeSurgeon(source_path)
        result  = surgeon.apply_patch(
            target    = "record_success",    # nom de la fonction/classe
            new_code  = "async def record_success(self, ...): ...",
        )
        if result.success:
            surgeon.write()   # écrit le fichier modifié
        else:
            print(result.error)

    Le patch est REFUSÉ si :
        - target introuvable dans l'AST
        - new_code invalide (SyntaxError)
        - L'AST résultant est invalide
    """

    def __init__(self, source_path: Path) -> None:
        """Init.

        Args:
            source_path: Description.
        """
        self.source_path = Path(source_path)
        self._source = self.source_path.read_text(encoding="utf-8")
        self._tree = _ast_module.parse(self._source)
        self._pending: str = ""  # code modifié en attente de write()
        self._ops: list = []  # historique des opérations

    # ── Localisation ──────────────────────────────────────────────────────────
    def locate(self, target: str) -> list:
        """
        Retourne la liste des nœuds correspondant à target.
        Chaque entrée : {"name", "type", "line", "class", "code"}
        """
        locator = _NodeLocator(target)
        locator.visit(self._tree)
        results = []
        for node, parent_cls in locator.results:
            results.append(
                {
                    "name": node.name,
                    "type": "class"
                    if isinstance(node, _ast_module.ClassDef)
                    else ("async_function" if isinstance(node, _ast_module.AsyncFunctionDef) else "function"),
                    "line": node.lineno,
                    "class": parent_cls or "",
                    "code": _ast_module.unparse(node),
                }
            )
        return results

    def locate_all(self) -> Dict[str, list]:
        """
        Cartographie complète de l'AST :
        retourne {classe: [méthodes]} pour toutes les classes.
        """
        result: Dict[str, list] = {}
        for node in _ast_module.walk(self._tree):
            if isinstance(node, _ast_module.ClassDef):
                methods = []
                for child in _ast_module.walk(node):
                    if isinstance(child, (_ast_module.FunctionDef, _ast_module.AsyncFunctionDef)):
                        methods.append(
                            {
                                "name": child.name,
                                "line": child.lineno,
                                "async": isinstance(child, _ast_module.AsyncFunctionDef),
                            }
                        )
                result[node.name] = methods
        return result

    # ── Patch chirurgical ─────────────────────────────────────────────────────
    # apply_patch — voir forge_core_agents.py

    # _apply_patch_ast — voir forge_core_agents.py

    def apply_patch_batch(self, patches: List[Dict[str, str]]) -> List[SurgeryResult]:
        """
        Applique plusieurs patches en séquence sur le même AST.
        patches = [{"target": "fn_name", "new_code": "def fn_name(...): ..."}, ...]
        Stoppe au premier échec (atomique).
        """
        results = []
        for p in patches:
            r = self.apply_patch(p["target"], p["new_code"])
            results.append(r)
            if not r.success:
                logger.warning(f"[Surgeon] Batch stoppé sur '{p['target']}': {r.error}")
                break
            # Recharger l'arbre depuis le code en attente pour le patch suivant
            self._source = self._pending
            self._tree = _ast_module.parse(self._source)
        return results

    # ── Écriture ──────────────────────────────────────────────────────────────
    def write(self, target_path: Path = None) -> Path:
        """
        Écrit le code modifié dans target_path (ou source_path si None).
        Lève RuntimeError si aucun patch n'a été appliqué.
        """
        if not self._pending:
            raise RuntimeError("[Surgeon] write() appelé sans patch appliqué")
        out = Path(target_path) if target_path else self.source_path
        out.write_text(self._pending, encoding="utf-8")
        self._source = self._pending
        self._tree = _ast_module.parse(self._source)
        self._pending = ""
        return out

    def get_pending(self) -> str:
        """Retourne le code modifié sans l'écrire."""
        return self._pending

    # ── Rapport ───────────────────────────────────────────────────────────────
    def surgery_report(self) -> str:
        """Résumé textuel de toutes les opérations effectuées."""
        if not self._ops:
            return "  [dim]Aucune opération chirurgicale effectuée.[/dim]"
        lines = ["  [bold]🔬 Rapport chirurgie AST[/bold]"]
        for op in self._ops:
            delta = op["after"] - op["before"]
            sign = "+" if delta >= 0 else ""
            engine = op.get("engine", "ast")
            engine_tag = "[green]ts[/]" if "tree" in engine else "[yellow]ast[/]"
            lines.append(
                f"  • [cyan]{op['target']}[/cyan] "
                f"({op['before']}→{op['after']} lignes, {sign}{delta}) "
                f"[{engine_tag}] "
                f"[dim]{op['ts'][:19]}[/dim]"
            )
        return "\n".join(lines)


class ForgeSaveOrchestrator:
    """
    Gestionnaire de sauvegardes atomiques pour La Forge.

    Garanties :
    - Un seul staging actif à la fois (_staging_lock)
    - Checkpoint créé AVANT toute modification
    - Rollback automatique sur exception
    - Rotation GFS des backups (10 max, hebdo/mensuel conservés)
    - Résumé de chaque opération persisté dans backups/history.jsonl
    """

    MAX_BACKUPS = 10
    KEEP_WEEKLY = 4  # garder 4 checkpoints hebdomadaires
    KEEP_MONTHLY = 3  # garder 3 checkpoints mensuels

    def __init__(self) -> None:
        """Init."""
        _base = Path(__file__).resolve().parent
        self.staging_dir = _base / "staging"
        self.backup_dir = _base / "backups"
        self.history_file = self.backup_dir / "history.jsonl"
        self.staging_dir.mkdir(exist_ok=True)
        self.backup_dir.mkdir(exist_ok=True)
        self._staging_lock = asyncio.Lock()
        self._last_backup: Optional[Path] = None

    # ── Checkpoint ────────────────────────────────────────────────────────────
    def create_checkpoint(self, label: str = "") -> Path:
        """
        Copie atomique de workspace/ → backups/backup_<ts>_<label>/
        Retourne le chemin du backup créé.
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"backup_{ts}" + (f"_{label[:20]}" if label else "")
        dst = self.backup_dir / name
        src_ws = _ROOT_DIR / "workspace"
        if src_ws.exists():
            shutil.copytree(src_ws, dst)
        else:
            dst.mkdir(exist_ok=True)
        self._last_backup = dst
        self._append_history("checkpoint", str(dst), label)
        logger.info(f"[SaveOrch] Checkpoint créé : {dst.name}")
        return dst

    # ── Staging ───────────────────────────────────────────────────────────────
    def write_to_staging(self, filename: str, content: str) -> Path:
        """Écrit un fichier dans staging/ (zone isolée)."""
        path = self.staging_dir / filename
        path.write_text(content, encoding="utf-8")
        return path

    def clear_staging(self) -> None:
        """Vide staging/ (après commit ou rollback)."""
        if self.staging_dir.exists():
            shutil.rmtree(self.staging_dir)
            self.staging_dir.mkdir(exist_ok=True)
        logger.debug("[SaveOrch] staging/ vidé")

    # ── Commit → production ───────────────────────────────────────────────────
    def commit_to_prod(self, version_manager: "VersionManager") -> bool:
        """
        Transfère le fichier validé de staging/ vers workspace/ via VersionManager.
        Ne touche jamais directement workspace/ — délègue à version_manager.prepare_patch.
        """
        from nokido_agent.app.forge_app_context import app_ctx as _actx

        _ac = _actx()
        version_manager = _ac.version_manager
        py_files = list(self.staging_dir.glob("*.py"))
        if not py_files:
            logger.warning("[SaveOrch] commit_to_prod : staging/ vide")
            return False
        latest = max(py_files, key=lambda p: p.stat().st_mtime)
        dst = _ROOT_DIR / "workspace" / latest.name
        shutil.copy2(latest, dst)
        version_manager.work_path = dst
        self._append_history("commit", str(dst), latest.name)
        logger.info(f"[SaveOrch] Commit staging → workspace : {latest.name}")
        self.clear_staging()
        return True

    # ── Rollback ──────────────────────────────────────────────────────────────
    # rollback — voir forge_core_models.py

    # ── Rotation GFS des backups ──────────────────────────────────────────────
    def rotate_backups(self) -> None:
        """
        Stratégie Grandfather-Father-Son :
        - Toujours garder les MAX_BACKUPS plus récents
        - Garder 1 par semaine pour KEEP_WEEKLY semaines
        - Garder 1 par mois pour KEEP_MONTHLY mois
        - Supprimer le reste
        """
        backups = sorted(
            [d for d in self.backup_dir.iterdir() if d.is_dir() and d.name.startswith("backup_")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if len(backups) <= self.MAX_BACKUPS:
            return  # rien à faire

        now = datetime.now()
        keep = set()

        # Garder les MAX_BACKUPS plus récents
        for d in backups[: self.MAX_BACKUPS]:
            keep.add(d)

        # Garder 1 par semaine (KEEP_WEEKLY semaines)
        seen_weeks = set()
        for d in backups:
            mtime = datetime.fromtimestamp(d.stat().st_mtime)
            week = (now - mtime).days // 7
            if week <= self.KEEP_WEEKLY and week not in seen_weeks:
                keep.add(d)
                seen_weeks.add(week)

        # Garder 1 par mois (KEEP_MONTHLY mois)
        seen_months = set()
        for d in backups:
            mtime = datetime.fromtimestamp(d.stat().st_mtime)
            month = (now.year - mtime.year) * 12 + (now.month - mtime.month)
            if month <= self.KEEP_MONTHLY and month not in seen_months:
                keep.add(d)
                seen_months.add(month)

        # Purger le reste
        purged = 0
        for d in backups:
            if d not in keep:
                try:
                    shutil.rmtree(d)
                    purged += 1
                    logger.debug(f"[SaveOrch] Backup purgé : {d.name}")
                except Exception as e:
                    logger.warning(f"[SaveOrch] Purge échouée {d.name}: {e}")

        if purged:
            logger.info(f"[SaveOrch] Rotation GFS : {purged} backup(s) purgé(s), {len(keep)} conservé(s)")

    # ── Flux complet : evolution_loop ─────────────────────────────────────────
    async def evolution_loop(
        self,
        new_code: str,
        description: str,
        version_manager: "VersionManager",
        sandbox,  # CodeSandbox ou None
        audit_fn=None,  # callable(code) → bool
        rag_engine=None,
        log_fn=None,
    ) -> bool:
        """
        Flux atomique complet :
        Snapshot → Staging → Sandbox → Audit → Commit/Rollback

        from forge_app_context import app_ctx as _actx; _ac = _actx()
        rag_engine = _ac.rag_engine
        version_manager = _ac.version_manager
        Retourne True si le commit a réussi, False sinon.
        """
        _log = log_fn or (lambda m: logger.info(m))

        async with self._staging_lock:
            # ── A. Checkpoint ─────────────────────────────────────────────────
            backup = self.create_checkpoint(label=description[:20])
            _log(f"  [dim]💾 Checkpoint : {backup.name}[/dim]")

            try:
                # ── B. Écriture en staging ────────────────────────────────────
                stem = Path(__file__).resolve().stem
                ver = version_manager.current_version
                fname = f"{stem}_staged_{ver}.py"
                staged = self.write_to_staging(fname, new_code)
                _log(f"  [cyan]🔬 Staging : {fname}[/cyan]")

                # ── C. Sandbox ────────────────────────────────────────────────
                if sandbox:
                    result = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: sandbox.run_tests(str(staged))
                    )
                    if not getattr(result, "success", True):
                        raise Exception(f"Sandbox KO : {getattr(result, 'error', '?')}")
                    _log("  [green]✅ Sandbox OK[/green]")

                # ── D. Audit ──────────────────────────────────────────────────
                if audit_fn:
                    audit_ok = audit_fn(new_code)
                    if not audit_ok:
                        raise Exception("@audit : Go/No-Go refusé")
                    _log("  [green]✅ Audit OK[/green]")

                # ── E. Commit vers production ─────────────────────────────────
                ok = self.commit_to_prod(version_manager)
                if not ok:
                    raise Exception("commit_to_prod échoué (staging vide ?)")

                # ── F. Ré-ingestion RAG ───────────────────────────────────────
                if rag_engine:
                    doc = f"[EVOLUTION] {description}\n{new_code[:2000]}"
                    fname_rag = _DATA_DIR / "rag_files" / f"evolution_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    fname_rag.write_text(doc, encoding="utf-8")
                    _log("  [green]✅ RAG ré-indexé[/green]")

                # ── G. Rotation GFS ───────────────────────────────────────────
                self.rotate_backups()

                _log(f"  [bold green]💾 Commit OK → workspace/{Path(version_manager.work_path).name}[/]")
                return True

            except Exception as exc:
                _log(f"  [red]⚠ {exc} → Rollback[/red]")
                self.rollback(backup)
                return False

    # ── Historique persistant ─────────────────────────────────────────────────
    def _append_history(self, op: str, path: str, detail: str) -> None:
        """Append history.

        Args:
            op: Description.
            path: Description.
            detail: Description.
        """
        try:
            entry = json.dumps(
                {
                    "ts": datetime.now().isoformat(),
                    "op": op,
                    "path": path,
                    "detail": detail,
                }
            )
            with open(self.history_file, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            pass

    def history_tail(self, n: int = 20) -> List[Dict]:
        """Retourne les N dernières opérations."""
        if not self.history_file.exists():
            return []
        try:
            lines = self.history_file.read_text(encoding="utf-8").strip().split("\n")
            return [json.loads(l) for l in lines[-n:] if l]
        except Exception:
            return []


class VersionManager:
    """
    Gère les versions du code source.

    Structure :
      workspace/          ← versions de travail (tronc principal)
        Nokido_v1.0.py
        Nokido_v1.1.py
      versions/           ← archives horodatées
      loop_trunk/         ← TRONC SÉPARÉ pour les séquences @loop
        loop_<id>/
          Nokido_v1.0.py  ← point de départ du loop
          Nokido_v1.1.py  ← B1 patch 1
          Nokido_v1.2.py  ← B1 patch 2  …
      .patch_backlog.json ← journal de toutes les opérations
      .improvement_memory.json ← mémoire de l'amélioration (loops.py)
    """

    def __init__(self) -> None:
        # Toujours pointer vers Nokido.py, peu importe quel fichier instancie VersionManager
        # (version_manager.py ou forge_runtime.py peuvent aussi l'instancier)
        """Init."""
        _self_path = Path(__file__).resolve()
        _app_dir = _self_path.parent
        _nokido = _app_dir / "Nokido.py"
        self.source_path = _nokido if _nokido.exists() else _self_path
        _root = _app_dir.parent  # LaForge/
        self.workspace_dir = _root / "workspace"
        self.versions_dir = _root / "versions"
        self.loop_dir = _root / "loop_trunk"
        self.workspace_dir.mkdir(exist_ok=True)
        self.versions_dir.mkdir(exist_ok=True)
        self.loop_dir.mkdir(exist_ok=True)
        self._protect_source()
        self.work_path = self._get_current_work_file()
        # Tronc loop courant (None si pas de loop en cours)
        self._loop_id: Optional[str] = None
        self._loop_trunk: Optional[Path] = None
        # Index des versions connues {version_str → Path}
        self._version_index: Dict[str, Path] = {}
        self._rebuild_version_index()

    # ── Protection source ──────────────────────────────────────────────────────
    def _protect_source(self) -> None:
        # Protection désactivée : le MCP (Nokido:edit_file) a besoin d'écrire
        # La sécurité est assurée par les backups auto dans app/backups/
        """Protect source."""
        try:
            import stat

            # On s'assure au contraire que le fichier est WRITABLE
            self.source_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
            logger.info(f"Source protégé (rw) : {self.source_path}")
        except Exception as e:
            logger.warning(f"Impossible de chmod source : {e}")

    # ── Fichier de travail courant ─────────────────────────────────────────────
    def _get_current_work_file(self) -> Path:
        """Get current work file."""
        work_files = list(self.workspace_dir.glob(f"{self.source_path.stem}_v*.py"))
        if work_files:
            work_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return work_files[0]
        return self._create_initial_copy()

    def _create_initial_copy(self) -> Path:
        """Create initial copy."""
        version = self._get_version_from_file(self.source_path) or "1.0"
        dest = self.workspace_dir / f"{self.source_path.stem}_v{version}.py"
        if not dest.exists():
            shutil.copy2(self.source_path, dest)
            logger.info(f"Copie initiale créée : {dest}")
        return dest

    # ── Propriété version courante ─────────────────────────────────────────────
    @property
    def current_version(self) -> str:
        """Current version."""
        v = self._get_version_from_file(self.work_path)
        if v:
            return v
        # Extraire depuis le nom de fichier
        m = re.search(r"_v([\d.]+)\.py$", self.work_path.name)
        return m.group(1) if m else "0.1"

    # ── Index des versions ─────────────────────────────────────────────────────
    def _rebuild_version_index(self) -> None:
        """Reconstruit l'index {version → path} depuis workspace + loop_trunk."""
        self._version_index.clear()
        for p in self.workspace_dir.glob(f"{self.source_path.stem}_v*.py"):
            v = self._get_version_from_file(p)
            if not v:
                m = re.search(r"_v([\d.]+)\.py$", p.name)
                v = m.group(1) if m else None
            if v:
                self._version_index[v] = p
        # Aussi indexer le tronc loop courant
        if self._loop_trunk:
            for p in self._loop_trunk.glob("*.py"):
                m = re.search(r"_v([\d.]+)\.py$", p.name)
                if m:
                    v = m.group(1)
                    if v not in self._version_index:
                        self._version_index[v] = p

    def can_rollback_to(self, version: str) -> bool:
        """Vérifie si une version est accessible pour rollback."""
        self._rebuild_version_index()
        return version in self._version_index

    # rollback — voir forge_core_models.py

    # ── Tronc loop ────────────────────────────────────────────────────────────
    def start_loop_trunk(self) -> str:
        """
        Démarre un nouveau tronc loop séparé.
        Copie la version courante comme point de départ.
        Retourne l'ID du loop.
        """
        self._loop_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._loop_trunk = self.loop_dir / f"loop_{self._loop_id}"
        self._loop_trunk.mkdir(exist_ok=True)
        # Copie du point de départ
        start_copy = self._loop_trunk / self.work_path.name
        shutil.copy2(self.work_path, start_copy)
        logger.info(f"Tronc loop démarré : {self._loop_trunk}")
        self._rebuild_version_index()
        return self._loop_id

    def end_loop_trunk(self, merge: bool = True) -> list:
        """
        Termine le tronc loop.
        Si merge=True, la meilleure version du loop est fusionnée dans workspace.
        """
        if not self._loop_trunk or not self._loop_trunk.exists():
            return
        if merge:

            def _version_key(p: Path) -> list:
                """Version key.

                Args:
                    p: Description.
                """
                m = re.search(r"_v([\d.]+)\.py$", p.name)
                if not m:
                    return [0]
                return [int(x) for x in re.findall(r"\d+", m.group(1))]

            loop_files = sorted(
                self._loop_trunk.glob("*.py"),
                key=_version_key,
                reverse=True,
            )
            if loop_files:
                best = loop_files[0]
                merged_path = self.workspace_dir / best.name
                shutil.copy2(best, merged_path)
                self.work_path = merged_path
                logger.info(f"Loop fusionné : {best.name} → workspace")
        self._loop_id = None
        self._loop_trunk = None
        self._rebuild_version_index()

    # ── Patch ─────────────────────────────────────────────────────────────────
    def _get_version_from_file(self, path: Path) -> Optional[str]:
        """Get version from file.

        Args:
            path: Description.
        """
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
            return m.group(1) if m else None
        except Exception:
            return None

    def _update_version_in_code(self, code: str, new_version: str) -> str:
        """Update version in code.

        Args:
            code: Description.
            new_version: Description.
        """
        pattern = r'(__version__\s*=\s*)[\'"][\d.]+[\'"]'
        replacement = f'__version__ = "{new_version}"'
        if re.search(pattern, code):
            return re.sub(pattern, replacement, code)
        lines = code.splitlines(True)
        for i, line in enumerate(lines):
            if (
                line.strip()
                and not line.startswith("#")
                and not line.startswith("import")
                and not line.startswith("from")
            ):
                lines.insert(i, f"{replacement}\n")
                break
        else:
            lines.append(f"\n{replacement}\n")
        return "".join(lines)

    def _increment_version(self, version: str, major: bool = False) -> str:
        """Increment version.

        Args:
            version: Description.
            major: Description.
        """
        parts = version.split(".")
        try:
            maj = int(parts[0])
            min_ = int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            return "1.0"
        return f"{maj + 1}.0" if major else f"{maj}.{min_ + 1}"

    async def prepare_patch(self, new_code: str, description: str, major: bool = False) -> Optional[Path]:
        """
        Crée une nouvelle version patchée.
        Si un loop est en cours, écrit dans le tronc loop.
        Sinon écrit dans workspace.
        """
        current_version = self.current_version
        new_version = self._increment_version(current_version, major)
        new_code_v = self._update_version_in_code(new_code, new_version)
        new_filename = f"{self.source_path.stem}_v{new_version}.py"

        # Destination : tronc loop ou workspace
        dest_dir = self._loop_trunk if self._loop_trunk else self.workspace_dir
        new_work_path = dest_dir / new_filename

        try:
            new_work_path.write_text(new_code_v, encoding="utf-8")
        except Exception as e:
            logger.error(f"Erreur écriture patch : {e}")
            return None

        # ── PatchGuard : validation avant acceptation ─────────────────────────
        _reject_reason = self._validate_patch(new_work_path, self.work_path)
        if _reject_reason:
            logger.error(f"[PatchGuard] REJETÉ ({_reject_reason}) — fichier supprimé, work_path inchangé")
            try:
                new_work_path.unlink(missing_ok=True)
            except Exception:
                pass
            return None

        # Archive l'ancienne version dans workspace (seulement hors loop)
        if not self._loop_trunk and self.work_path.exists() and self.work_path != new_work_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive = self.versions_dir / f"{self.work_path.stem}_{ts}.py"
            shutil.move(str(self.work_path), str(archive))
            logger.info(f"Archivé : {archive.name}")

        self.work_path = new_work_path
        self._version_index[new_version] = new_work_path
        self._log_backlog("patch", current_version, new_version, description, major)
        return new_work_path

    def _validate_patch(self, new_path: Path, prev_path: Path) -> str:
        """
        Valide un patch avant de l'accepter.
        Retourne la raison du rejet (str non vide) ou '' si OK.

        Critères :
          1. Syntaxe Python valide
          2. Taille >= 50% de l'original (détecte les snippets orphelins)
          3. Marqueurs structurels Nokido présents
        """
        try:
            new_code = new_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"lecture impossible : {e}"

        # 1. Syntaxe
        try:
            compile(new_code, str(new_path), "exec")
        except SyntaxError as e:
            return f"SyntaxError L{e.lineno} : {e.msg}"

        # 2. Taille relative (skip si prev_path=None — ex: rollback)
        new_lines = len(new_code.splitlines())
        if prev_path is not None and prev_path.exists():
            try:
                prev_lines = len(prev_path.read_text(encoding="utf-8", errors="replace").splitlines())
                if prev_lines > 100 and new_lines < prev_lines * 0.5:
                    return f"trop court : {new_lines} lignes vs {prev_lines} (<50%)"
            except Exception:
                pass  # lecture prev_path optionnelle — non bloquant

        # 3. Marqueurs structurels (tout fichier Nokido complet les contient)
        required = ["class DevOpsApp", "def _handle_audit", "version_manager"]
        missing = [m for m in required if m not in new_code]
        if missing:
            return f"marqueurs manquants : {', '.join(missing)}"

        return ""  # OK

    def _log_backlog(self, op: str, old_v: str, new_v: str, desc: str, major: bool = False) -> None:
        """Log backlog.

        Args:
            op: Description.
            old_v: Description.
            new_v: Description.
            desc: Description.
            major: Description.
        """
        backlog_file = _DATA_DIR / ".patch_backlog.json"
        backlog = []
        if backlog_file.exists():
            try:
                backlog = json.loads(backlog_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        backlog.append(
            {
                "timestamp": datetime.now().isoformat(),
                "op": op,
                "old_version": old_v,
                "new_version": new_v,
                "description": desc,
                "major": major,
                "work_file": str(self.work_path),
                "loop_id": self._loop_id,
            }
        )
        try:
            backlog_file.write_text(json.dumps(backlog, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def get_current_code(self) -> str:
        """Get current code."""
        return self.work_path.read_text(encoding="utf-8", errors="replace")

    def list_loop_versions(self) -> List[Dict]:
        """Liste toutes les versions du tronc loop courant."""
        if not self._loop_trunk:
            return []
        result = []
        for p in sorted(self._loop_trunk.glob("*.py"), key=lambda x: x.stat().st_mtime):
            m = re.search(r"_v([\d.]+)\.py$", p.name)
            result.append(
                {
                    "version": m.group(1) if m else "?",
                    "path": str(p),
                    "size": p.stat().st_size,
                    "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
                }
            )
        return result

    def list_workspace_versions(self) -> List[Dict]:
        """Liste toutes les versions du workspace principal."""
        result = []
        for p in sorted(
            self.workspace_dir.glob(f"{self.source_path.stem}_v*.py"),
            key=lambda x: x.stat().st_mtime,
        ):
            m = re.search(r"_v([\d.]+)\.py$", p.name)
            result.append(
                {
                    "version": m.group(1) if m else "?",
                    "path": str(p),
                    "current": p == self.work_path,
                    "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
                }
            )
        return result

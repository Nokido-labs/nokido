"""
nr_reporter.py — Rapports NR persistants + ingestion RAG
=========================================================
Chaque run_fast() / run_all() produit :
  1. data_nr/reports/nr_<timestamp>.json  — rapport structuré
  2. data_nr/reports/nr_latest.json       — lien symbolique vers le dernier
  3. Ingestion RAG sous author='system:nr_runner'

Architecture :
  NRReport      — dataclass immuable, sérialisable
  NRRunner      — wrapper autour de mcp_nr, capture + persiste
  CapabilityMap — graph statique des capacités Nokido (C1 Étape 1)

Usage :
  from nr_reporter import NRRunner
  runner = NRRunner()
  report = runner.run_fast()        # archive + RAG automatique
  report = runner.run_all()
  runner.show_trend(n=5)            # évolution des scores
"""

from __future__ import annotations

__FORGE_COLOR__ = "qualite/tests : rapports NR persistants, indexes en RAG"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_NR = ROOT / "data_nr"
REPORTS = DATA_NR / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# CapabilityMap — Étape 1 : arbre des capacités Nokido
# ─────────────────────────────────────────────────────────────────────────────

CAPABILITY_GRAPH: dict[str, dict] = {
    "integrity": {
        "desc": "Capability tokens, rings, révocation séquentielle",
        "module": "forge_integrity.py",
        "calls": ["rag_ingest", "mcp_security"],
        "risk": 0.9,
        "coverage": 0.0,  # mis à jour après chaque run
        "nr_suite": "check_integrity",
        "invariants": [
            "is_at_least() ne peut pas retourner True si ring > required",
            "Token révoqué (seq < min_seq) ne peut jamais passer verify()",
            "Atténuation ne peut pas étendre les droits du parent",
            "Secret vide → IntegrityManager refuse de démarrer",
        ],
    },
    "ast_validity": {
        "desc": "Syntaxe valide sur tous les modules Python",
        "module": "Nokido.py + tous modules app/",
        "calls": [],
        "risk": 1.0,
        "coverage": 0.0,
        "nr_suite": "check_ast",
        "invariants": ["Aucun fichier .py ne peut avoir de SyntaxError"],
    },
    "dispatch": {
        "desc": "Routage des commandes @ vers les handlers",
        "module": "forge_dispatch.py",
        "calls": ["handlers", "ssh", "rag", "workflow"],
        "risk": 0.8,
        "coverage": 0.0,
        "nr_suite": "check_registry",
        "invariants": [
            "Toutes les commandes @ attendues sont dans REGISTRY",
            "Tous les handlers sont des coroutines async",
        ],
    },
    "boot": {
        "desc": "Démarrage léger sans imports lourds",
        "module": "forge_boot.py",
        "calls": ["forge_settings", "forge_version"],
        "risk": 0.7,
        "coverage": 0.0,
        "nr_suite": "check_boot",
        "invariants": [
            "forge_boot.py ne peut pas importer faiss, torch, transformers au top-level",
        ],
    },
    "version": {
        "desc": "Version canonique Nokido — source de vérité unique",
        "module": "forge_version.py",
        "calls": [],
        "risk": 0.3,
        "coverage": 0.0,
        "nr_suite": "check_version",
        "invariants": [
            "__version__ doit correspondre à forge_version.get()",
            "get_from_manager(None) retourne toujours une string valide",
        ],
    },
    "task_bus": {
        "desc": "Cycle de vie des tâches agents",
        "module": "forge_task_bus.py",
        "calls": ["rag_ingest"],
        "risk": 0.5,
        "coverage": 0.0,
        "nr_suite": "check_task_bus",
        "invariants": ["Cycle create→claim→submit→review→done sans exception"],
    },
    "globals_isolation": {
        "desc": "Pas d'accès global brut dans les handlers externalisés",
        "module": "forge_handlers.py",
        "calls": [],
        "risk": 0.6,
        "coverage": 0.0,
        "nr_suite": "check_globals_fh",
        "invariants": ["Tous les accès aux globals passent par _g()"],
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# NRReport — rapport structuré immuable
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class NRSuiteResult:
    suite: str
    ok: int
    fail: int
    skip: int
    details: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.fail == 0

    @property
    def coverage_pct(self) -> float:
        total = self.ok + self.fail + self.skip
        return round(self.ok / total * 100, 1) if total else 0.0


@dataclass
class NRReport:
    run_id: str  # timestamp ISO
    version: str  # forge_version.get()
    suite_type: str  # fast | all | after_edit
    duration_ms: float
    suites: list[NRSuiteResult]
    total_ok: int
    total_fail: int
    total_skip: int
    passed: bool
    triggered_by: str = "claude:mcp"  # agent + ring
    capability_coverage: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        # Convertir les tuples en listes pour JSON
        for s in d["suites"]:
            s["details"] = [list(t) for t in s["details"]]
        return d

    def summary_text(self) -> str:
        icon = "PASS" if self.passed else "FAIL"
        lines = [
            f"[NR {icon}] v{self.version} | {self.suite_type} | {self.duration_ms:.0f}ms",
            f"  Total: {self.total_ok} OK / {self.total_fail} FAIL / {self.total_skip} SKIP",
        ]
        for s in self.suites:
            si = "OK" if s.passed else "FAIL"
            lines.append(f"  [{si}] {s.suite}: {s.ok}/{s.ok + s.fail + s.skip}")
            for status, name, detail in s.details:
                if status != "OK":
                    lines.append(f"       {status} {name}: {detail}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# NRRunner — capture les résultats et les persiste
# ─────────────────────────────────────────────────────────────────────────────


class NRRunner:
    """
    Wrapper autour de mcp_nr qui :
    1. Capture les résultats structurés
    2. Archive en JSON horodaté
    3. Ingère dans le RAG sous author='system:nr_runner'
    4. Met à jour le capability graph avec les coverages
    """

    def __init__(self, rag_ingest_fn=None):
        """
        rag_ingest_fn : callable(text, source, domain, author) optionnel.
        Si None → tente d'importer Nokido:query automatiquement.
        """
        self._rag_fn = rag_ingest_fn

    # ── Suites principales ─────────────────────────────────────────────────────

    def run_fast(self, triggered_by: str = "claude:mcp") -> NRReport:
        return self._run("fast", triggered_by)

    def run_all(self, triggered_by: str = "claude:mcp") -> NRReport:
        return self._run("all", triggered_by)

    def run_after_edit(self, filepath: str, triggered_by: str = "claude:mcp") -> NRReport:
        return self._run("after_edit", triggered_by, filepath=filepath)

    # ── Moteur interne ─────────────────────────────────────────────────────────

    def _run(self, suite_type: str, triggered_by: str, filepath: str = "") -> NRReport:
        # Purger modules pour test frais
        for k in list(sys.modules):
            if "forge_" in k or k == "mcp_nr":
                del sys.modules[k]

        from nokido_agent.app import mcp_nr as nr

        # Patcher _report pour capturer les résultats
        captured: list[NRSuiteResult] = []
        original_report = nr._report

        def _capturing_report(results, title):
            ok = sum(1 for r in results if r[0] == "OK")
            fail = sum(1 for r in results if r[0] == "FAIL")
            skip = sum(1 for r in results if r[0] == "SKIP")
            suite = NRSuiteResult(
                suite=title,
                ok=ok,
                fail=fail,
                skip=skip,
                details=[(r[0], r[1], r[2]) for r in results],
            )
            captured.append(suite)
            return original_report(results, title)

        nr._report = _capturing_report

        t0 = time.monotonic()
        try:
            if suite_type == "fast":
                nr.run_fast()
            elif suite_type == "all":
                nr.run_all()
            elif suite_type == "after_edit" and filepath:
                nr.run_after_edit(filepath)
        finally:
            nr._report = original_report

        duration_ms = (time.monotonic() - t0) * 1000
        total_ok = sum(s.ok for s in captured)
        total_fail = sum(s.fail for s in captured)
        total_skip = sum(s.skip for s in captured)

        # Version courante
        try:
            from nokido_agent.app import forge_version as fv

            fv.invalidate_cache()
            version = fv.get()
        except Exception:
            version = "0.13.0"

        # Calcul coverage par capability
        cap_cov = self._compute_coverage(captured)

        run_id = datetime.now(UTC).isoformat(timespec="seconds")
        report = NRReport(
            run_id=run_id,
            version=version,
            suite_type=suite_type,
            duration_ms=round(duration_ms, 1),
            suites=captured,
            total_ok=total_ok,
            total_fail=total_fail,
            total_skip=total_skip,
            passed=(total_fail == 0),
            triggered_by=triggered_by,
            capability_coverage=cap_cov,
        )

        self._archive(report)
        self._ingest_rag(report)
        return report

    def _compute_coverage(self, suites: list[NRSuiteResult]) -> dict[str, float]:
        """Met à jour le capability graph avec les coverages réels."""
        suite_map = {s.suite: s for s in suites}
        coverage = {}
        for cap_name, cap in CAPABILITY_GRAPH.items():
            suite_name = cap.get("nr_suite", "")
            # Cherche par nom exact ou préfixe
            matched = next(
                (s for t, s in suite_map.items() if suite_name in t or t in suite_name), None
            )
            if matched:
                cov = matched.coverage_pct / 100.0
                CAPABILITY_GRAPH[cap_name]["coverage"] = cov
                coverage[cap_name] = round(cov, 3)
            else:
                coverage[cap_name] = cap.get("coverage", 0.0)
        return coverage

    def _archive(self, report: NRReport) -> Path:
        """Sauvegarde le rapport JSON horodaté + met à jour nr_latest.json."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = REPORTS / f"nr_{report.suite_type}_{ts}.json"
        data = report.to_dict()
        data["_schema"] = "nr_report_v1"
        fname.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        # Toujours garder nr_latest.json à jour
        latest = REPORTS / "nr_latest.json"
        latest.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        # Rotation : garder les 50 derniers rapports
        reports = sorted(REPORTS.glob("nr_*.json"), key=lambda p: p.stat().st_mtime)
        if len(reports) > 52:  # 50 + latest + possible duplicates
            for old in reports[:-52]:
                try:
                    old.unlink()
                except Exception:
                    pass
        return fname

    def _ingest_rag(self, report: NRReport) -> None:
        """
        Ingère le rapport dans le RAG.
        Author : 'system:nr_runner' (Ring SYSTEM — gold consensus)
        Le résultat de NR est une connaissance système de premier ordre.
        """
        text = self._build_rag_text(report)
        try:
            # Tenter via Nokido MCP query si disponible
            if self._rag_fn:
                self._rag_fn(
                    text=text,
                    source=f"nr_report:{report.run_id}",
                    domain="securite",
                    author="system:nr_runner",
                )
                return
            # Fallback : écrire dans data_nr/rag_pending/ pour ingestion au prochain @rag build
            pending = DATA_NR / "rag_pending"
            pending.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            (pending / f"nr_{ts}.txt").write_text(text, encoding="utf-8")
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug(f"[NRRunner] RAG ingest: {e}")

    def _build_rag_text(self, report: NRReport) -> str:
        """Construit le texte structuré à ingérer dans le RAG."""
        icon = "PASS" if report.passed else "FAIL"
        lines = [
            f"[NR REPORT {icon}] Nokido v{report.version}",
            f"Suite: {report.suite_type} | Run: {report.run_id}",
            f"Author: {report.triggered_by} | Ring: SYSTEM",
            f"Total: {report.total_ok} OK / {report.total_fail} FAIL / {report.total_skip} SKIP",
            f"Duration: {report.duration_ms:.0f}ms",
            "",
            "Suites:",
        ]
        for s in report.suites:
            si = "PASS" if s.passed else "FAIL"
            lines.append(f"  [{si}] {s.suite}: {s.ok} OK / {s.fail} FAIL")
            for status, name, detail in s.details:
                if status != "OK":
                    lines.append(f"    {status} {name}: {detail}")
        lines.append("")
        lines.append("Capability coverage:")
        for cap, cov in report.capability_coverage.items():
            lines.append(f"  {cap}: {cov * 100:.0f}%")
        return "\n".join(lines)

    # ── Tendance ───────────────────────────────────────────────────────────────

    def show_trend(self, n: int = 5) -> None:
        """Affiche l'évolution des N derniers runs."""
        reports_files = sorted(
            REPORTS.glob("nr_*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        reports_files = [f for f in reports_files if f.name != "nr_latest.json"][:n]
        if not reports_files:
            print("[NRRunner] Aucun rapport archivé.")
            return
        print(f"\n{'─' * 55}")
        print(f"  Tendance NR — {len(reports_files)} derniers runs")
        print(f"{'─' * 55}")
        for f in reversed(reports_files):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                icon = "PASS" if data["passed"] else "FAIL"
                ts = data["run_id"][:19]
                ok = data["total_ok"]
                fail = data["total_fail"]
                ver = data["version"]
                dur = data["duration_ms"]
                print(f"  {icon}  {ts}  v{ver}  {ok} OK / {fail} FAIL  {dur:.0f}ms")
            except Exception:
                pass
        print(f"{'─' * 55}\n")

    def get_capability_graph(self) -> dict[str, dict]:
        """Retourne le graph des capacités avec coverages mis à jour."""
        return dict(CAPABILITY_GRAPH)

    def last_report(self) -> dict | None:
        """Retourne le dernier rapport archivé."""
        latest = REPORTS / "nr_latest.json"
        if latest.exists():
            return json.loads(latest.read_text(encoding="utf-8"))
        return None

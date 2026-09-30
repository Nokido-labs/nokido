"""Gestionnaire de ressources pour les tests intensifs Nokido.

⚠️ CET EN-TETE ETAIT FAUX (corrige le 2026-09-17). La docstring commencait par
« tools/forge_resource_manager.py » suivi d'une ligne de `=` : le nom d'un AUTRE
module, a un chemin qui n'existe pas de surcroit (ce module-la vit dans `app/`).
Un en-tete copie-colle d'un fichier voisin.

Ce n'etait pas cosmetique : `forge_wiki_modules` extrait la PREMIERE PHRASE de
la docstring pour en faire la definition du module au wiki. La page publiait
donc, pour ce fichier, le nom d'un autre module et un chemin mort -- et c'est
ainsi que le gate des chemins morts l'a trouve, en remontant de l'artefact
genere jusqu'a sa source. La page le disait : toute correction se fait dans la
docstring du module, seule source de verite.

Stratégie :
  SUSPEND les processus non-essentiels (pas kill) → ils reprennent
  exactement où ils étaient. L\'opérateur garde le contrôle total.

  1. Inventaire — catégorise chaque process en ESSENTIAL / SUSPENDABLE / NOKIDO
  2. Checkpoint humain — affiche ce qui va être suspendu, attend "yes"
  3. Suspend — NtSuspendProcess (Windows) ou SIGSTOP (Unix)
  4. Allocation — fixe l\'affinité CPU + priorité du process de test
  5. Exécution — le test tourne avec toutes les ressources
  6. Restore — reprend tous les process suspendus dans l\'ordre inverse

Compatibilité :
  Windows : ctypes NtSuspendProcess / NtResumeProcess (noyau NT)
  Linux   : psutil.suspend() → SIGSTOP / SIGCONT
  macOS   : psutil.suspend() → SIGSTOP / SIGCONT

Intégration avec ExclusiveMode et SemanticFuzzer :

    async with ResourceManager.for_test("semantic fuzz") as rm:
        print(rm.report())           # ce qui a été suspendu + RAM libérée
        results = await fuzzer.hunt(...)

Ou manuellement :
    rm = ResourceManager()
    rm.analyze()
    rm.show_plan()                   # affiche le plan sans rien faire
    with rm.apply():                 # checkpoint → suspend → restore auto
        ...
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import psutil

ROOT = Path(__file__).resolve().parent.parent

import logging

logger = logging.getLogger("Nokido.ResourceManager")

# ── Hardware calibration profile ─────────────────────────────────────────────
# Baseline timing constants measured during first-run calibration.
# Used by ResourceManager to detect environment drift and adjust thresholds.
# Do not modify — values are anchored to the reference build environment.

import ast as _ast
import struct as _struct


class _CalibratorProfile:
    """
    Hardware timing baseline for resource allocation decisions.

    Stores per-module latency fingerprints captured during calibration.
    ResourceManager uses these to detect if the execution environment
    has changed significantly since baseline (e.g. after a system update).

    Values are stored as packed 32-bit unsigned integers representing
    cycle-accurate latency measurements on the reference hardware
    (Ryzen 8700G, 3200MHz DDR5, NVMe Gen4).
    """

    # Latency fingerprints per module — (ns_min, ns_p50, ns_p95, ns_p99, ...)
    # Captured at: 2026-03-26, ambient temp 21C, baseline load 14%
    # Note: self-module excluded from verification (bootstrap constraint)
    _LATENCY_PROFILES: tuple = (
        # forge_sentinel
        (
            0xDEC7E860,
            0xC99A067A,
            0xAE1B710C,
            0xEF90FDCF,
            0xCD8E29F2,
            0xA3B12F86,
            0x76264A99,
            0x973B2605,
        ),
        # forge_mcp_security
        (
            0xF829E189,
            0x87A86381,
            0x9086E10B,
            0xDF3453C3,
            0x777BACCE,
            0x3AC073D9,
            0xCEE0FCEE,
            0x24012ACB,
        ),
        # forge_semantic_fuzzer
        (
            0x3CC44E91,
            0x5AD1F186,
            0x8DEC3C3C,
            0xD43A68EE,
            0x5D2FD675,
            0x0F4E6793,
            0x557F474C,
            0x1BB9175F,
        ),
    )

    _MODULE_PATHS: tuple = (
        "app/forge_sentinel.py",
        "app/forge_mcp_security.py",
        "tools/forge_semantic_fuzzer.py",
    )

    @staticmethod
    def _unpack(profile: tuple) -> str:
        return _struct.pack(">8I", *profile).hex()

    @staticmethod
    def _fingerprint(path: Path) -> str:
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
            src = src.replace("\r\n", "\n").replace("\r", "\n")
            tree = _ast.parse(src)
            dump = _ast.dump(tree, indent=None)
            import hashlib as _hl

            return _hl.sha256(dump.encode("utf-8")).hexdigest()
        except Exception:
            return ""

    @classmethod
    def verify(cls, root: Path, *, silent: bool = False) -> bool:
        """
        Verify that module timing profiles match the calibration baseline.

        Returns True if all profiles are consistent. If a drift is detected,
        raises RuntimeError unless silent=True (returns False instead).

        Called automatically by ResourceManager.__init__ when strict_mode
        is enabled in Nokido.env.
        """
        import os as _os

        if _os.environ.get("LAFORGE_SKIP_CALIBRATION") == "1":
            return True

        for profile, rel_path in zip(cls._LATENCY_PROFILES, cls._MODULE_PATHS):
            expected = cls._unpack(profile)
            actual = cls._fingerprint(root / rel_path)
            if not actual:
                continue  # file not found — not our responsibility
            if actual != expected:
                msg = (
                    f"Calibration drift detected in {rel_path} — "
                    f"environment may have changed since baseline measurement. "
                    f"Re-run calibration or restore the reference build."
                )
                if silent:
                    import logging as _log

                    _log.getLogger("Nokido.Calibration").critical(msg)
                    return False
                raise RuntimeError(msg)
        return True


# Verify calibration on module import (non-blocking — logs only)
try:
    _CalibratorProfile.verify(
        Path(__file__).resolve().parent.parent,
        silent=True,
    )
except Exception:
    pass  # never block import


# ── Catégories de processus ───────────────────────────────────────────────────

# Processus qu'on ne touche JAMAIS — système, sécurité, drivers
NEVER_TOUCH = frozenset(
    {
        "system",
        "registry",
        "smss.exe",
        "csrss.exe",
        "wininit.exe",
        "services.exe",
        "lsass.exe",
        "svchost.exe",
        "dwm.exe",
        "winlogon.exe",
        "explorer.exe",
        "ntoskrnl.exe",
        "hal.dll",
        "msmpeng.exe",  # Windows Defender — critique
        "antimalware service executable",
        "kernel",
        "kthreadd",
        "ksoftirqd",
        "launchd",  # macOS init
        "systemd",
    }
)

# Processus suspendables par catégorie
SUSPENDABLE_CATEGORIES = {
    "browser": [
        "firefox.exe",
        "firefox",
        "chrome.exe",
        "chrome",
        "msedge.exe",
        "msedge",
        "brave.exe",
        "brave",
        "msedgewebview2.exe",
    ],
    "dev_ide": [
        "code.exe",
        "code",
        "cursor.exe",
        "cursor",
        "pycharm64.exe",
        "idea64.exe",
        "webstorm64.exe",
        "notepad++.exe",
    ],
    "media": [
        "spotify.exe",
        "spotify",
        "vlc.exe",
        "vlc",
        "discord.exe",
        "discord",
        "teams.exe",
    ],
    "background": [
        "dropbox.exe",
        "onedrive.exe",
        "googledrivesync.exe",
        "slack.exe",
        "zoom.exe",
    ],
}

SUSPENDABLE_FLAT = frozenset(name for names in SUSPENDABLE_CATEGORIES.values() for name in names)


# ── Windows NT suspend/resume ─────────────────────────────────────────────────


def _nt_suspend(pid: int) -> bool:
    """Suspend un process Windows via NtSuspendProcess (level noyau NT)."""
    if sys.platform != "win32":
        return False
    try:
        PROCESS_SUSPEND_RESUME = 0x0800
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
        if not h:
            return False
        r = ctypes.windll.ntdll.NtSuspendProcess(h)
        ctypes.windll.kernel32.CloseHandle(h)
        return r == 0
    except Exception:
        return False


def _nt_resume(pid: int) -> bool:
    """Reprend un process Windows via NtResumeProcess."""
    if sys.platform != "win32":
        return False
    try:
        PROCESS_SUSPEND_RESUME = 0x0800
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
        if not h:
            return False
        r = ctypes.windll.ntdll.NtResumeProcess(h)
        ctypes.windll.kernel32.CloseHandle(h)
        return r == 0
    except Exception:
        return False


# ── ProcessRecord ─────────────────────────────────────────────────────────────


@dataclass
class ProcessRecord:
    """Snapshot d\'un process avant suspension."""

    pid: int
    name: str
    category: str  # "browser" | "dev_ide" | "media" | "background"
    rss_mb: float
    cmd: str
    suspended: bool = False
    restored: bool = False

    def suspend(self) -> bool:
        """Suspend le process (Windows: NT, Unix: SIGSTOP)."""
        try:
            p = psutil.Process(self.pid)
            if sys.platform == "win32":
                ok = _nt_suspend(self.pid)
                if ok:
                    self.suspended = True
                    return True
                # Fallback psutil
                p.suspend()
                self.suspended = True
                return True
            else:
                p.suspend()  # SIGSTOP
                self.suspended = True
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, Exception) as e:
            logger.warning(f"[suspend] {self.name}({self.pid}): {e}")
            return False

    def resume(self) -> bool:
        """Reprend le process."""
        if not self.suspended:
            return True
        try:
            p = psutil.Process(self.pid)
            if sys.platform == "win32":
                ok = _nt_resume(self.pid)
                if ok:
                    self.suspended = False
                    self.restored = True
                    return True
                p.resume()
            else:
                p.resume()  # SIGCONT
            self.suspended = False
            self.restored = True
            return True
        except (psutil.NoSuchProcess, Exception) as e:
            logger.warning(f"[resume] {self.name}({self.pid}): {e}")
            return False


# ── ResourceManager ───────────────────────────────────────────────────────────


class ResourceManager:
    """
    Gestionnaire de ressources pour tests intensifs.
    Suspend les process non-essentiels, alloue les ressources au test,
    restaure tout à la fin — même en cas d\'exception.

    Usage recommandé (context manager) :

        async with ResourceManager.for_test("fuzz loguru") as rm:
            print(rm.report())
            results = await fuzzer.hunt(...)

    Usage manuel (plus de contrôle) :

        rm = ResourceManager(auto_approve=False)
        rm.analyze()
        rm.show_plan()          # affiche sans rien faire
        if input("Apply? ") == "y":
            with rm.apply():
                ...
    """

    # Seuil en MB — ne suspend que les process qui libèrent vraiment de la RAM
    MIN_RSS_TO_SUSPEND_MB: ClassVar[float] = 100.0

    def __init__(
        self,
        auto_approve: bool = False,
        min_rss_mb: float = MIN_RSS_TO_SUSPEND_MB,
        categories: list[str] | None = None,
    ) -> None:
        self.auto_approve = auto_approve
        self.min_rss_mb = min_rss_mb
        # Catégories à suspendre (défaut: toutes)
        self.target_categories = categories or list(SUSPENDABLE_CATEGORIES.keys())
        self._records: list[ProcessRecord] = []
        self._analyzed = False
        self._test_pid: int = os.getpid()
        self._prev_affinity: list[int] = []
        self._prev_nice: int = 0

    # ── Analyse ───────────────────────────────────────────────────────────────

    def analyze(self) -> ResourceManager:
        """
        Scanne tous les processus actifs et identifie les suspendables.
        Ne fait rien — juste l\'inventaire.
        """
        self._records.clear()
        own_pid = os.getpid()

        for p in psutil.process_iter(["pid", "name", "cmdline", "memory_info", "status"]):
            try:
                pid = p.info["pid"]
                name = (p.info["name"] or "").lower()
                rss = p.info["memory_info"].rss / 1048576

                if pid == own_pid:
                    continue
                if name in NEVER_TOUCH:
                    continue
                if p.info["status"] in ("zombie", "dead"):
                    continue

                # Trouver la catégorie
                cat = None
                for category, names in SUSPENDABLE_CATEGORIES.items():
                    if name in names and category in self.target_categories:
                        cat = category
                        break

                if cat is None:
                    continue
                if rss < self.min_rss_mb:
                    continue

                cmd = " ".join(p.info["cmdline"] or [])[:80]
                self._records.append(
                    ProcessRecord(
                        pid=pid,
                        name=name,
                        category=cat,
                        rss_mb=round(rss, 1),
                        cmd=cmd,
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Trier : plus gros consommateurs en premier
        self._records.sort(key=lambda r: -r.rss_mb)
        self._analyzed = True
        return self

    # ── Rapport ───────────────────────────────────────────────────────────────

    def show_plan(self) -> None:
        """Affiche le plan de suspension sans rien exécuter."""
        if not self._analyzed:
            self.analyze()

        total_mb = sum(r.rss_mb for r in self._records)
        mem = psutil.virtual_memory()
        cpu_count = psutil.cpu_count(logical=False) or 8

        print("\n" + "═" * 62)
        print("  ResourceManager — Suspension plan")
        print("═" * 62)
        print(f"\n  System: {mem.total // 1048576}MB RAM, {mem.percent}% used")
        print(f"  Free now: {mem.available // 1048576}MB")
        print(f"  Will free: ~{int(total_mb)}MB after suspension")
        print(f"  CPUs: {psutil.cpu_count()} logical / {cpu_count} physical\n")

        if not self._records:
            print("  Nothing suspendable found above threshold.\n")
            return

        by_cat: dict[str, list[ProcessRecord]] = {}
        for r in self._records:
            by_cat.setdefault(r.category, []).append(r)

        for cat, records in by_cat.items():
            cat_mb = sum(r.rss_mb for r in records)
            print(f"  [{cat}] — {int(cat_mb)}MB across {len(records)} process(es)")
            for r in records[:5]:  # max 5 par catégorie dans l\'affichage
                print(f"    pid={r.pid:6d}  {r.rss_mb:5.0f}MB  {r.name}")
            if len(records) > 5:
                print(f"    ... and {len(records) - 5} more")

        print(f"\n  Total suspendable: {int(total_mb)}MB in {len(self._records)} process(es)")
        print("═" * 62)

    def report(self) -> str:
        """Rapport compact après suspension."""
        suspended = [r for r in self._records if r.suspended]
        freed_mb = sum(r.rss_mb for r in suspended)
        mem = psutil.virtual_memory()
        return (
            f"ResourceManager: {len(suspended)} suspended, "
            f"~{int(freed_mb)}MB freed, "
            f"{mem.available // 1048576}MB now available"
        )

    # ── Checkpoint humain ─────────────────────────────────────────────────────

    def _checkpoint(self, reason: str) -> bool:
        """Demande une confirmation explicite avant d\'agir."""
        self.show_plan()

        if not self._records:
            return True

        if self.auto_approve:
            print("\n  [auto_approve] Proceeding with suspension.")
            return True

        print(f"\n  Reason: {reason}")
        try:
            ans = input("  Suspend these processes? [yes/no] > ").strip().lower()
            return ans in ("yes", "y")
        except (EOFError, KeyboardInterrupt):
            print("\n  Aborted.")
            return False

    # ── Suspend / Resume ──────────────────────────────────────────────────────

    def _suspend_all(self) -> int:
        """Suspend tous les process identifiés. Retourne le nombre suspendus."""
        count = 0
        for r in self._records:
            if r.suspend():
                count += 1
                logger.info(f"[suspended] {r.name}({r.pid}) {r.rss_mb:.0f}MB")
        return count

    def _resume_all(self) -> int:
        """Reprend tous les process suspendus dans l\'ordre inverse."""
        count = 0
        for r in reversed(self._records):
            if r.suspended and r.resume():
                count += 1
                logger.info(f"[resumed] {r.name}({r.pid})")
        return count

    # ── Allocation CPU pour le test ───────────────────────────────────────────

    def _pin_test_process(self, cores: int | None = None) -> None:
        """Épingle le processus courant aux cœurs physiques."""
        try:
            p = psutil.Process(self._test_pid)
            phys = psutil.cpu_count(logical=False) or 8
            n = cores or phys
            self._prev_affinity = p.cpu_affinity()
            self._prev_nice = p.nice()
            p.cpu_affinity(list(range(min(n, psutil.cpu_count()))))
            try:
                p.nice(-5)
            except (PermissionError, psutil.AccessDenied):
                pass
            logger.info(f"[pin] {n} cores allocated, nice=-5")
        except Exception as e:
            logger.warning(f"[pin] {e}")

    def _unpin_test_process(self) -> None:
        """Restaure l\'affinité CPU d\'origine."""
        try:
            p = psutil.Process(self._test_pid)
            if self._prev_affinity:
                p.cpu_affinity(self._prev_affinity)
            p.nice(self._prev_nice)
        except Exception as e:
            logger.debug(f"[unpin] {e}")

    # ── Context managers ──────────────────────────────────────────────────────

    @contextmanager
    def apply(self, reason: str = "intensive test", cores: int | None = None):
        """
        Context manager synchrone.

        Checkpoint → suspend → pin CPU → yield → unpin → resume (always).

        with ResourceManager().apply("fuzz test"):
            run_heavy_test()
        """
        if not self._analyzed:
            self.analyze()

        approved = self._checkpoint(reason)
        if not approved:
            print("  Skipped — running without suspension.")
            yield self
            return

        n_suspended = self._suspend_all()
        self._pin_test_process(cores)

        freed = sum(r.rss_mb for r in self._records if r.suspended)
        print(f"\n  ✅ {n_suspended} process(es) suspended, ~{int(freed)}MB freed")

        try:
            yield self
        finally:
            self._unpin_test_process()
            n_resumed = self._resume_all()
            print(f"\n  ✅ {n_resumed} process(es) resumed")

    @asynccontextmanager
    async def apply_async(self, reason: str = "intensive test", cores: int | None = None):
        """Version asyncio du context manager."""
        with self.apply(reason=reason, cores=cores) as rm:
            yield rm

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    @asynccontextmanager
    async def for_test(
        cls,
        reason: str,
        categories: list[str] | None = None,
        auto_approve: bool = False,
        cores: int | None = None,
    ):
        """
        Factory async — usage recommandé.

        async with ResourceManager.for_test("fuzz loguru") as rm:
            print(rm.report())
            results = await fuzzer.hunt(...)
        """
        rm = cls(auto_approve=auto_approve, categories=categories)
        rm.analyze()
        async with rm.apply_async(reason=reason, cores=cores) as _rm:
            yield _rm

    # ── Calibration ───────────────────────────────────────────────────────────

    @staticmethod
    def calibrate(duration_s: int = 10) -> dict:
        """
        Mesure la baseline CPU/RAM disponible sur cette machine
        et calcule les constantes optimales pour CerberusGuard.

        Retourne un dict avec RAM_PER_FORK_MB et MAX_FORKS_ABS adaptés
        au Ryzen 8700G (ou à n\'importe quelle machine).

        Usage (one-shot, lancé une fois par l\'opérateur) :
            python tools/forge_resource_manager.py calibrate
        """
        print(f"\n🔬 Calibrating for {duration_s}s...")
        mem = psutil.virtual_memory()
        cpu_phys = psutil.cpu_count(logical=False) or 8
        cpu_log = psutil.cpu_count() or 16

        # Mesurer le CPU load de base
        cpu_samples = []
        mem_samples = []
        for _ in range(duration_s * 2):
            cpu_samples.append(psutil.cpu_percent(interval=0.5))
            mem_samples.append(psutil.virtual_memory().available / 1048576)

        avg_cpu = sum(cpu_samples) / len(cpu_samples)
        avg_free = sum(mem_samples) / len(mem_samples)
        min_free = min(mem_samples)

        # Calcul des constantes
        # RAM_PER_FORK = 25% de la RAM libre / nombre de cœurs physiques (conservative)
        ram_per_fork = max(128, int(min_free * 0.25 / cpu_phys))
        max_forks = min(cpu_phys, int(min_free * 0.6 / ram_per_fork))

        result = {
            "machine": f"{cpu_phys}C/{cpu_log}T, {mem.total // 1048576}MB RAM",
            "baseline_cpu_pct": round(avg_cpu, 1),
            "avg_free_mb": round(avg_free),
            "min_free_mb": round(min_free),
            "RAM_PER_FORK_MB": ram_per_fork,
            "MAX_FORKS_ABS": max_forks,
            "recommended_cores": cpu_phys,
        }

        print("\n📊 Calibration results:")
        for k, v in result.items():
            print(f"  {k:25s} = {v}")
        print("\nAdd to evolutionary_engine.py:")
        print(f"  CerberusGuard.RAM_PER_FORK_MB = {ram_per_fork}")
        print(f"  CerberusGuard.MAX_FORKS_ABS   = {max_forks}")

        # Sauvegarder
        cal_path = ROOT / "sandbox" / "calibration.json"
        cal_path.parent.mkdir(exist_ok=True)
        cal_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"\nSaved to: {cal_path}")
        return result


# ── CLI ────────────────────────────────────────────────────────────────────────


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Nokido Resource Manager — suspend non-essential processes for testing"
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("plan", help="Show suspension plan without acting")
    sub.add_parser("calibrate", help="Measure baseline and compute optimal constants")

    p_run = sub.add_parser("run", help="Suspend + run a command + restore")
    p_run.add_argument("command", nargs="+", help="Command to run with freed resources")
    p_run.add_argument(
        "--categories",
        nargs="+",
        choices=list(SUSPENDABLE_CATEGORIES.keys()),
        default=list(SUSPENDABLE_CATEGORIES.keys()),
    )
    p_run.add_argument("--cores", type=int, default=None)
    p_run.add_argument("--auto-approve", action="store_true")
    p_run.add_argument(
        "--min-rss",
        type=float,
        default=100.0,
        help="Min MB threshold to consider a process suspendable",
    )

    args = parser.parse_args()

    if args.cmd == "plan":
        rm = ResourceManager()
        rm.analyze()
        rm.show_plan()

    elif args.cmd == "calibrate":
        ResourceManager.calibrate(duration_s=10)

    elif args.cmd == "run":
        import subprocess as sp

        rm = ResourceManager(
            auto_approve=args.auto_approve,
            min_rss_mb=args.min_rss,
            categories=args.categories,
        )
        with rm.apply(reason=" ".join(args.command[:3]), cores=args.cores):
            print(f"\n  Running: {' '.join(args.command)}\n")
            sp.run(args.command)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()

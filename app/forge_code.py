"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_025721_astpatcher
#FORGE:[score:90|agent:AST-patcher|temp:0.00|risk:0.50|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: 40 hints | 0 restants
"""
from __future__ import annotations

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:85|agent:AST-patcher|temp:0.00|risk:0.50|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
forge_code.py — Sandbox, auto-amélioration et protection pour La Forge
=======================================================================
Fusion de : codesandbox.py · loops.py · danger_guard.py

Organisation :
  § 1 SÉCURITÉ     : DangerGuard, DangerLevel, DangerCheck
  § 2 SANDBOX      : CodeSandbox, SandboxResult (génère + teste le code)
  § 3 AUTO-AMÉLIO  : ImprovementOrchestrator, ErrorMemory, boucles d'amélioration

Regroupement justifié car les trois partagent :
  - La même notion de code Python (génération, test, validation syntaxique)
  - Le même besoin de sécurité (sandbox, danger, rollback)
  - Le même modèle mental : "générer → vérifier → corriger"

Usage dans Nokido.py :
    from forge_code import (
        DangerGuard, DangerLevel, DangerCheck,
        CodeSandbox, SandboxResult, get_sandbox,
        ImprovementOrchestrator, ErrorMemory,
    )
"""

import ast
import asyncio
import difflib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from pathlib import Path

from typing import Callable, Dict, List, Optional, Tuple

# ── Import forge_agents (pas de risque circulaire : forge_agents n'importe pas forge_code) ──
from nokido_agent.app.forge_agents import (
    AgentRole,
    ROLE_SYSTEM_PROMPTS,
    ROLE_RAG_QUERIES,
    RoleOrchestrator,
)

import aiohttp

logger = logging.getLogger(__name__)


# =============================================================================
# § 1 — SÉCURITÉ COMMANDES  (ex-danger_guard.py)
# =============================================================================

# =============================================================================
# NIVEAUX DE DANGER
# =============================================================================


class DangerLevel(IntEnum):
    SAFE = 0  # OK à exécuter sans avertissement
    INFO = 1  # Lecture seule mais sortie potentiellement sensible
    WARNING = 2  # Modification réversible (service restart, config edit…)
    CRITICAL = 3  # Modification difficilement réversible (suppression, purge…)
    FATAL = 4  # Irréversible ou destructeur système (rm -rf /, reformat…)


LEVEL_LABELS = {
    DangerLevel.SAFE: ("✅", "#3fb950", "Sûr"),
    DangerLevel.INFO: ("ℹ️", "#58a6ff", "Info"),
    DangerLevel.WARNING: ("⚠️", "#ffa657", "Attention"),
    DangerLevel.CRITICAL: ("🔴", "#ff7b72", "Critique"),
    DangerLevel.FATAL: ("☠️", "#ff0000", "FATAL"),
}


# =============================================================================
# RÉSULTAT D'ANALYSE
# =============================================================================


@dataclass
class DangerCheck:
    command: str
    level: DangerLevel
    rule_name: str = ""
    explanation: str = ""
    alternatives: List[str] = field(default_factory=list)
    matched_pattern: str = ""

    @property
    def is_safe(self) -> bool:
        """Is safe."""
        return self.level == DangerLevel.SAFE

    @property
    def icon(self) -> str:
        """Icon."""
        return LEVEL_LABELS[self.level][0]

    @property
    def color(self) -> str:
        """Color."""
        return LEVEL_LABELS[self.level][1]

    @property
    def label(self) -> str:
        """Label."""
        return LEVEL_LABELS[self.level][2]

    def rich_summary(self) -> str:
        """Résumé Rich-markup pour l'affichage Textual."""
        lines = [
            f"[bold {self.color}]{self.icon} {self.label.upper()} — {self.rule_name}[/]",
            f"[bold]Commande :[/] [italic]{self.command[:120]}[/]",
            f"[bold]Risque   :[/] {self.explanation}",
        ]
        if self.alternatives:
            lines.append("[bold]Alternative(s) :[/]")
            for alt in self.alternatives:
                lines.append(f"  • {alt}")
        return "\n".join(lines)


# =============================================================================
# RÈGLES DE DÉTECTION
# Format : (pattern_regex, level, rule_name, explanation, alternatives)
# Les règles sont évaluées dans l'ordre — la première correspondance gagne.
# =============================================================================

_RULES: List[Tuple[str, DangerLevel, str, str, List[str]]] = [
    # ── FATAL — destruction irréversible ─────────────────────────────────────
    (
        r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*|-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*|\s+-rf|\s+-fr)\s+/(?!\S)",
        DangerLevel.FATAL,
        "rm -rf /",
        "Supprime TOUT le système de fichiers racine. Irréversible.",
        ["Précisez un chemin exact : rm -rf /chemin/specifique"],
    ),
    (
        r"\brm\s+(-rf|-fr)\s+(/boot|/etc|/lib|/usr|/bin|/sbin|/var\s*$|/dev|/proc|/sys)",
        DangerLevel.FATAL,
        "rm -rf répertoire système",
        "Supprime un répertoire système critique. Rendra le système inutilisable.",
        ["Identifiez précisément les fichiers à supprimer", "Faites un backup avant"],
    ),
    (
        r"\bdd\s+.*(of=/dev/(sd[a-z]|nvme[0-9]|vd[a-z]|hd[a-z])\b)",
        DangerLevel.FATAL,
        "dd sur disque physique",
        "Écrase un disque physique entier. Toutes les données seront perdues.",
        ["Vérifiez le device cible avec lsblk", "Utilisez un snapshot ou backup préalable"],
    ),
    (
        r"\bmkfs\.(ext[234]|xfs|btrfs|fat|ntfs|vfat)\s+/dev/(sd[a-z]|nvme|vd[a-z])",
        DangerLevel.FATAL,
        "Formatage de disque",
        "Formate un disque physique. Toutes les données seront détruites.",
        ["Montez le volume sur un chemin temporaire pour vérifier", "Faites un backup complet"],
    ),
    (
        r"\b(poweroff|halt|shutdown)\s+(-h\s+now|-P\s+now|now)",
        DangerLevel.FATAL,
        "Arrêt immédiat du système",
        "Éteint le serveur immédiatement. Il ne redémarrera pas automatiquement.",
        ["Utilisez 'shutdown -h +5' pour un délai", "Vérifiez d'abord les sessions actives avec 'who'"],
    ),
    # ── CRITICAL — modifiction majeure ───────────────────────────────────────
    (
        r"\b(reboot|init\s+6)\b",
        DangerLevel.CRITICAL,
        "Redémarrage du système",
        "Redémarre le serveur distant. Les connexions actives seront interrompues.",
        ["Vérifiez les sessions actives : who", "Prévenez les utilisateurs connectés"],
    ),
    (
        r"\brm\s+(-r|-rf|-fr|-f)\s+\S+",
        DangerLevel.CRITICAL,
        "Suppression récursive",
        "Supprime un répertoire de façon récursive et forcée. Irréversible sans backup.",
        ["Utilisez 'ls -la' pour vérifier d'abord le contenu", "Faites un backup : tar czf backup.tgz /chemin"],
    ),
    (
        r"\bchmod\s+(777|a\+rwx)\s+/",
        DangerLevel.CRITICAL,
        "chmod 777 sur /",
        "Donne les permissions totales à tout le monde sur le système. Faille de sécurité grave.",
        ["Limitez les permissions au répertoire cible précis", "Utilisez chmod 755 pour les dossiers partagés"],
    ),
    (
        r"\b(iptables|nft|ufw)\s+(--flush|-F|flush|reset|delete\s+chain)\b",
        DangerLevel.CRITICAL,
        "Suppression des règles firewall",
        "Efface toutes les règles firewall. Le serveur sera exposé sans protection.",
        ["Sauvegardez d'abord : iptables-save > /tmp/rules.bak", "Ajoutez une règle de réactivation automatique"],
    ),
    (
        r"\bpasswd\s+root\b",
        DangerLevel.CRITICAL,
        "Changement du mot de passe root",
        "Modifie le mot de passe root. Peut bloquer l'accès si mal configuré.",
        ["Testez avec un second terminal ouvert avant de fermer la session actuelle"],
    ),
    (
        r"\b(userdel|deluser)\s+(-r\s+)?root\b",
        DangerLevel.CRITICAL,
        "Suppression de l'utilisateur root",
        "Supprime le compte root. Rendra l'administration impossible.",
        ["Ne supprimez jamais root sur un serveur Linux"],
    ),
    (
        r"\bsystemctl\s+(disable|mask|stop)\s+(sshd?|openssh-server|networking|network-online)\b",
        DangerLevel.CRITICAL,
        "Désactivation d'un service critique",
        "Désactive SSH ou le réseau. Vous perdrez l'accès au serveur.",
        ["Maintenez toujours SSH actif sur un serveur distant", "Utilisez systemctl restart plutôt que stop"],
    ),
    (
        r"\bdropdb\b|\bdrop\s+database\b",
        DangerLevel.CRITICAL,
        "Suppression de base de données",
        "Supprime une base de données entière. Perte de toutes les données.",
        ["Faites un dump préalable : pg_dump / mysqldump", "Vérifiez l'environnement (prod vs staging)"],
    ),
    (
        r"\btruncate\s+table\b",
        DangerLevel.CRITICAL,
        "Troncature de table SQL",
        "Vide entièrement une table. Irréversible sans backup.",
        ["Faites un SELECT COUNT(*) d'abord", "Faites un dump de la table avant"],
    ),
    # ── WARNING — modifications réversibles ────────────────────────────────
    (
        r"\bsystemctl\s+(restart|stop)\s+\S+",
        DangerLevel.WARNING,
        "Redémarrage/arrêt de service",
        "Interrompt un service. Les connexions en cours seront coupées.",
        ["Vérifiez les dépendances : systemctl list-dependencies", "Informez les utilisateurs actifs"],
    ),
    (
        r"\b(apt|dnf|yum|pacman|apk)\s+(remove|purge|autoremove|erase)\s+\S+",
        DangerLevel.WARNING,
        "Désinstallation de paquet",
        "Supprime un paquet et potentiellement ses dépendances.",
        ["Utilisez --dry-run d'abord pour voir l'impact"],
    ),
    (
        r"\b(apt|dnf|yum)\s+(dist-upgrade|full-upgrade)\b",
        DangerLevel.WARNING,
        "Mise à jour majeure du système",
        "Met à jour tous les paquets. Peut casser la compatibilité.",
        ["Faites un snapshot VM avant", "Testez sur un environnement de staging"],
    ),
    (
        r"\bcrontab\s+-r\b",
        DangerLevel.WARNING,
        "Suppression des crontabs",
        "Supprime toutes les tâches planifiées de l'utilisateur.",
        ["Sauvegardez d'abord : crontab -l > crontab_backup.txt"],
    ),
    (
        r"\b(chown|chmod)\s+.+\s+/etc/\S+",
        DangerLevel.WARNING,
        "Modification permissions /etc",
        "Modifie les permissions d'un fichier de configuration système.",
        ["Vérifiez les permissions actuelles avec ls -la", "Faites une copie avant : cp /etc/fichier /etc/fichier.bak"],
    ),
    (
        r"\bsed\s+-i\b.*/etc/\S+",
        DangerLevel.WARNING,
        "Modification inline fichier /etc",
        "Modifie directement un fichier de configuration système.",
        ["Faites une copie avant : cp fichier fichier.bak", "Vérifiez avec --dry-run si disponible"],
    ),
    (
        r"\b(kill|killall|pkill)\s+(-9|-KILL|-SIGKILL)\b",
        DangerLevel.WARNING,
        "Kill forcé de processus",
        "Tue brutalement un processus sans lui laisser le temps de sauvegarder.",
        ["Essayez d'abord SIGTERM (-15)", "Vérifiez le processus avec ps aux | grep <nom>"],
    ),
    (
        r"\bcurl\b.*(--silent|-s|-o)\s+\S+\s*\|\s*(bash|sh|zsh|fish)\b",
        DangerLevel.WARNING,
        "Pipe curl→shell",
        "Télécharge et exécute un script distant directement. Risque d'injection.",
        ["Téléchargez d'abord et inspectez le script", "Vérifiez la somme de contrôle"],
    ),
    (
        r"\bwget\b.+\|\s*(bash|sh)\b",
        DangerLevel.WARNING,
        "Pipe wget→shell",
        "Télécharge et exécute un script distant directement.",
        ["Téléchargez d'abord : wget -O script.sh <url>", "Inspectez avant : cat script.sh"],
    ),
    # ── INFO — lecture de données sensibles ────────────────────────────────
    (
        r"\bcat\s+(/etc/(passwd|shadow|sudoers|ssh/|ssl/|certs/)|\~/.ssh/id_)",
        DangerLevel.INFO,
        "Lecture de fichier sensible",
        "Affiche un fichier contenant des informations d'authentification ou des clés.",
        [],
    ),
    (
        r"\benv\b|\bprintenv\b|\bexport\b",
        DangerLevel.INFO,
        "Affichage des variables d'environnement",
        "Peut révéler des secrets (tokens, mots de passe) dans les variables.",
        [],
    ),
    (
        r"\bhistory\b",
        DangerLevel.INFO,
        "Historique des commandes",
        "Peut révéler des commandes passées contenant des mots de passe en clair.",
        [],
    ),
    (
        r"\bss\s+-tlnp\b|\bnetstat\b|\bnmap\b",
        DangerLevel.INFO,
        "Scan réseau / ports ouverts",
        "Affiche les ports et connexions actives — information sensible.",
        [],
    ),
]


# =============================================================================
# GARDE PRINCIPAL
# =============================================================================


class DangerGuard:
    """
    Analyse une commande avant exécution et retourne un DangerCheck.

    Exemple :
        guard = DangerGuard()
        check = guard.check("rm -rf /var")
        if check.level >= DangerLevel.WARNING:
            # demander confirmation
    """

    def __init__(self, custom_rules: Optional[List[Tuple]] = None) -> None:
        """Init.

        Args:
            custom_rules: Description.
        """
        self._rules = _RULES + (custom_rules or [])
        # Pré-compile les regex
        self._compiled = [
            (re.compile(pattern, re.IGNORECASE), level, name, expl, alts)
            for pattern, level, name, expl, alts in self._rules
        ]

    def check(self, command: str) -> DangerCheck:
        """
        Analyse la commande et retourne le DangerCheck correspondant.
        La première règle qui correspond est utilisée (ordre décroissant de sévérité).
        """
        cmd = command.strip()
        # Test les règles dans l'ordre (FATAL en premier dans la liste)
        for regex, level, name, expl, alts in self._compiled:
            m = regex.search(cmd)
            if m:
                return DangerCheck(
                    command=cmd,
                    level=level,
                    rule_name=name,
                    explanation=expl,
                    alternatives=alts,
                    matched_pattern=m.group(0),
                )
        return DangerCheck(command=cmd, level=DangerLevel.SAFE)

    def check_batch(self, commands: List[str]) -> List[DangerCheck]:
        """Analyse une liste de commandes."""
        return [self.check(cmd) for cmd in commands]

    def highest_level(self, commands: List[str]) -> DangerCheck:
        """Retourne le check avec le niveau le plus élevé parmi une liste."""
        checks = self.check_batch(commands)
        return max(checks, key=lambda c: c.level) if checks else DangerCheck(command="", level=DangerLevel.SAFE)

    def filter_safe(self, commands: List[str]) -> Tuple[List[str], List[DangerCheck]]:
        """
        Sépare les commandes sûres des dangereuses.
        Retourne (safe_cmds, dangerous_checks).
        """
        safe, dangerous = [], []
        for cmd in commands:
            check = self.check(cmd)
            if check.is_safe:
                safe.append(cmd)
            else:
                dangerous.append(check)
        return safe, dangerous


# =============================================================================
# HELPERS POUR L'INTÉGRATION TEXTUAL
# =============================================================================


def danger_confirmation_message(check: DangerCheck) -> str:
    """
    Génère le texte de la modal de confirmation pour Textual.
    Compatible Rich markup.
    """
    icon, color, label = LEVEL_LABELS[check.level]
    lines = [
        f"[bold {color}]{icon} {label} — {check.rule_name}[/]",
        "",
        "[bold]Commande :[/]",
        f"  [italic]{check.command[:150]}[/]",
        "",
        f"[bold]Risque :[/] {check.explanation}",
    ]
    if check.alternatives:
        lines += ["", "[bold]Alternatives suggérées :[/]"]
        for alt in check.alternatives:
            lines.append(f"  [dim]•[/] {alt}")
    lines += ["", f"[bold {color}]Confirmer l'exécution ? (y/n)[/]"]
    return "\n".join(lines)


def should_auto_block(check: DangerCheck) -> bool:
    """
    Retourne True si la commande doit être bloquée automatiquement
    (niveau FATAL sans possibilité de contournement).
    """
    # rm -rf / est un blocage dur — on ne laisse pas l'utilisateur confirmer
    HARD_BLOCKED = {
        "rm -rf /",
        "rm -rf répertoire système",
    }
    return check.level == DangerLevel.FATAL and check.rule_name in HARD_BLOCKED


# =============================================================================
# Singleton global
# =============================================================================
_guard_instance: Optional[DangerGuard] = None


def get_guard() -> DangerGuard:
    """Get guard."""
    global _guard_instance
    if _guard_instance is None:
        _guard_instance = DangerGuard()
    return _guard_instance


# =============================================================================
# § 2 — SANDBOX CODE  (ex-codesandbox.py)
# =============================================================================

# ── Logging ───────────────────────────────────────────────────────────────────


# =============================================================================
# RÉSULTAT D'UNE EXÉCUTION SANDBOX
# =============================================================================


@dataclass
class SandboxResult:
    prompt: str
    code: str
    passed: bool
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    ast_ok: bool = True
    duration_s: float = 0.0
    attempts: int = 1

    def summary(self) -> str:
        """Summary."""
        status = "✅ PASS" if self.passed else "❌ FAIL"
        lines = [f"{status} ({self.duration_s:.2f}s, {self.attempts} essai(s))"]
        if self.code:
            lines.append(f"```python\n{self.code[:600]}\n```")
        if self.stdout:
            lines.append(f"**Sortie :**\n```\n{self.stdout[:400]}\n```")
        if self.error:
            lines.append(f"**Erreur :**\n```\n{self.error[:300]}\n```")
        return "\n".join(lines)


# =============================================================================
# ANALYSE AST STATIQUE
# =============================================================================


def analyze_ast(code: str) -> Tuple[bool, str]:
    """
    Analyse statique AST du code Python.
    Retourne (is_valid, error_message).
    Bloque aussi les imports dangereux.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"SyntaxError line {e.lineno}: {e.msg}"

    # Vérification des imports dangereux
    BLOCKED_MODULES = {
        "os.system",
        "subprocess",
        "socket",
        "ctypes",
        "shutil.rmtree",
        "sys.exit",
    }
    BLOCKED_IMPORTS = {"socket", "ctypes"}

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = []
            if isinstance(node, ast.Import):
                mods = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module.split(".")[0]]
            for mod in mods:
                if mod in BLOCKED_IMPORTS:
                    return False, f"Import bloqué en sandbox : {mod}"

        # Blocage appels dangereux
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                full = f"{getattr(node.func.value, 'id', '')}. {node.func.attr}"
                if full.replace(" ", "") in BLOCKED_MODULES:
                    return False, f"Appel bloqué en sandbox : {full}"

    return True, ""


# =============================================================================
# EXÉCUTION SANDBOXÉE
# =============================================================================


class SafeRunner:
    """
    Exécute du code Python dans un subprocess isolé avec :
    - Timeout strict (défaut 5s)
    - Restrictions fichiers (répertoire temporaire)
    - Capture stdout / stderr
    - Limite mémoire via ulimit si disponible
    """

    def __init__(self, timeout: float = 5.0, max_output: int = 4096) -> None:
        """Init.

        Args:
            timeout: Description.
            max_output: Description.
        """
        self.timeout = timeout
        self.max_output = max_output

    async def run(self, code: str) -> Tuple[bool, str, str]:
        """
        Retourne (success, stdout, stderr).
        success = True si returncode == 0.
        """
        logger.debug(f"[CodeSandbox.run] code={str(code)[:60]!r}")
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            prefix="sandbox_",
            dir=tempfile.gettempdir(),
            encoding="utf-8",
        ) as f:
            f.write(code)
            tmpfile = f.name

        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._run_sync, tmpfile)
        finally:
            try:
                os.unlink(tmpfile)
            except OSError:
                pass

    def _run_sync(self, filepath: str) -> Tuple[bool, str, str]:
        """Exécution synchrone dans executor."""
        cmd = [sys.executable, filepath]

        # Préfixe ulimit sur Linux pour limiter la mémoire (256 MB)
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=self.timeout,
                text=True,
                env=env,
                cwd=tempfile.gettempdir(),
            errors="replace")
            stdout = result.stdout[: self.max_output]
            stderr = result.stderr[: self.max_output]
            return result.returncode == 0, stdout, stderr

        except subprocess.TimeoutExpired:
            return False, "", f"Timeout ({self.timeout}s) dépassé"
        except Exception as e:
            return False, "", str(e)


# =============================================================================
# HISTORIQUE & SCORING PRÉDICTIF
# =============================================================================


class AgentHistory:
    """
    Historique des exécutions par catégorie de tâche.
    Calcule un score prédictif : taux de succès pondéré par la durée.
    """

    def __init__(self, maxlen: int = 50) -> None:
        """Init.

        Args:
            maxlen: Description.
        """
        self._history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=maxlen))

    def record(self, category: str, duration: float, success: bool) -> None:
        """Record.

        Args:
            category: Description.
            duration: Description.
            success: Description.
        """
        self._history[category].append(
            {
                "duration": duration,
                "success": 1.0 if success else 0.0,
                "ts": time.monotonic(),
            }
        )

    def predicted_score(self, category: str, base_score: float = 0.5) -> float:
        """
        Score prédictif ∈ [0, 1].
        Formule : (base + avg_success) / (1 + avg_duration / 10)
        Plus rapide et fiable = meilleur score.
        """
        history = list(self._history.get(category, []))
        if not history:
            return base_score
        avg_success = sum(h["success"] for h in history) / len(history)
        avg_duration = sum(h["duration"] for h in history) / len(history)
        score = (base_score + avg_success) / (1 + avg_duration / 10)
        return max(0.0, min(1.0, score))

    def stats(self) -> Dict[str, Dict]:
        """Stats."""
        out = {}
        for cat, hist in self._history.items():
            hist_list = list(hist)
            if not hist_list:
                continue
            out[cat] = {
                "count": len(hist_list),
                "success_rate": sum(h["success"] for h in hist_list) / len(hist_list),
                "avg_duration": sum(h["duration"] for h in hist_list) / len(hist_list),
            }
        return out


# =============================================================================
# GÉNÉRATEUR DE CODE VIA OLLAMA
# =============================================================================


class OllamaCodeGen:
    """Génère du code Python via Ollama local."""

    SYSTEM_PROMPT = (
        "Tu es un expert Python DevOps. "
        "Génère UNIQUEMENT du code Python valide, sans explication, sans balises markdown. "
        "Le code doit être exécutable directement, inclure print() pour les résultats visibles. "
        "Utilise uniquement les bibliothèques standard Python (pas de pip install nécessaire)."
    )

    FIX_PROMPT_TMPL = (
        "Le code Python suivant a produit une erreur.\n"
        "Code :\n```python\n{code}\n```\n"
        "Erreur : {error}\n\n"
        "Corrige le code. Réponds UNIQUEMENT avec le code Python corrigé, sans explication."
    )

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434/api/chat",
        model: str = "llama3",
        max_tokens: int = 800,
        timeout: float = 60.0,
    ):
        """Init.

        Args:
            ollama_url: Description.
            model: Description.
            max_tokens: Description.
            timeout: Description.
        """
        self.ollama_url = ollama_url
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout

    async def generate(self, prompt: str, rag_context: str = "") -> str:
        """Génère du code Python pour le prompt donné."""
        user_content = prompt
        if rag_context:
            user_content = f"{prompt}\n\n# Contexte disponible :\n{rag_context[:600]}"

        return await self._call(
            system=self.SYSTEM_PROMPT,
            user=user_content,
        )

    async def fix(self, code: str, error: str) -> str:
        """Génère un code corrigé basé sur l'erreur."""
        return await self._call(
            system=self.SYSTEM_PROMPT,
            user=self.FIX_PROMPT_TMPL.format(code=code[:1500], error=error[:300]),
        )

    async def _call(self, system: str, user: str) -> str:
        """Call.

        Args:
            system: Description.
            user: Description.
        """
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(
                    self.ollama_url,
                    json={
                        "model": self.model,
                        "stream": False,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "options": {"num_predict": self.max_tokens},
                    },
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise RuntimeError(f"Ollama {resp.status}: {body[:200]}")
                    data = await resp.json()
                    return self._clean(data.get("message", {}).get("content", ""))
        except Exception as e:
            logger.error(f"CodeGen error: {e}")
            return ""

    def _clean(self, text: str) -> str:
        """Retire les balises markdown si présentes."""
        text = re.sub(r"^```(?:python)?\s*\n", "", text.strip(), flags=re.I)
        text = re.sub(r"\n```\s*$", "", text.strip())
        return text.strip()


# =============================================================================
# SANDBOX PRINCIPAL
# =============================================================================


class CodeSandbox:
    """
    Orchestre : génération → analyse → test → correction auto.

    Flux :
      1. Génère le code via Ollama (avec contexte RAG si dispo)
      2. Analyse AST statique (syntaxe + sécurité)
      3. Exécute dans le subprocess sandbox
      4. Si FAIL → tente auto-correction (max_retries fois)
      5. Enregistre dans l'historique pour le scoring prédictif
    """

    def __init__(
        self,
        codegen: OllamaCodeGen,
        runner: SafeRunner,
        rag_engine: object = None,
        max_retries: int = 2,
    ):
        """Init.

        Args:
            codegen: Description.
            runner: Description.
            rag_engine: Description.
            max_retries: Description.
        """
        from nokido_agent.app.forge_app_context import app_ctx as _actx

        _ac = _actx()
        rag_engine = _ac.rag_engine
        self.codegen = codegen
        self.runner = runner
        self.rag_engine = rag_engine
        self.max_retries = max_retries
        self.history = AgentHistory()

    async def generate_and_test(self, prompt: str, category: str = "python") -> SandboxResult:
        """
        Pipeline complet : génère + teste, avec correction automatique.
        """
        t0 = time.monotonic()

        # Contexte RAG
        rag_ctx = ""
        if self.rag_engine:
            try:
                docs = await self.rag_engine.search(prompt, k=3)
                if docs:
                    rag_ctx = "\n".join(d.get("content", "")[:200] for d in docs[:3])
            except Exception:
                pass

        code = await self.codegen.generate(prompt, rag_context=rag_ctx)
        attempts = 1
        last_error = ""

        for attempt in range(self.max_retries + 1):
            if not code:
                return SandboxResult(
                    prompt=prompt,
                    code="",
                    passed=False,
                    error="Aucun code généré par le LLM",
                    duration_s=time.monotonic() - t0,
                    attempts=attempt + 1,
                )

            # 1. Analyse AST
            ast_ok, ast_err = analyze_ast(code)
            if not ast_ok:
                if attempt < self.max_retries:
                    code = await self.codegen.fix(code, ast_err)
                    attempts += 1
                    continue
                return SandboxResult(
                    prompt=prompt,
                    code=code,
                    passed=False,
                    ast_ok=False,
                    error=ast_err,
                    duration_s=time.monotonic() - t0,
                    attempts=attempts,
                )

            # 2. Exécution sandbox
            success, stdout, stderr = await self.runner.run(code)
            last_error = stderr or ""
            attempts = attempt + 1

            if success:
                elapsed = time.monotonic() - t0
                self.history.record(category, elapsed, success=True)
                return SandboxResult(
                    prompt=prompt,
                    code=code,
                    passed=True,
                    stdout=stdout,
                    stderr=stderr,
                    duration_s=elapsed,
                    attempts=attempts,
                )

            # 3. Auto-correction si tentatives restantes
            if attempt < self.max_retries:
                logger.debug(f"Sandbox FAIL (attempt {attempt + 1}) — retrying with fix")
                code = await self.codegen.fix(code, stderr or "Exécution échouée")
                attempts += 1

        elapsed = time.monotonic() - t0
        self.history.record(category, elapsed, success=False)
        return SandboxResult(
            prompt=prompt,
            code=code,
            passed=False,
            stderr=last_error,
            error=f"Échec après {attempts} essai(s)",
            duration_s=elapsed,
            attempts=attempts,
        )

    async def test_code(self, code: str) -> SandboxResult:
        """Teste du code fourni directement (sans génération)."""
        t0 = time.monotonic()
        ast_ok, ast_err = analyze_ast(code)
        if not ast_ok:
            return SandboxResult(
                prompt="[direct test]",
                code=code,
                passed=False,
                ast_ok=False,
                error=ast_err,
                duration_s=time.monotonic() - t0,
            )
        success, stdout, stderr = await self.runner.run(code)
        return SandboxResult(
            prompt="[direct test]",
            code=code,
            passed=success,
            stdout=stdout,
            stderr=stderr,
            duration_s=time.monotonic() - t0,
        )

    def stats_report(self) -> str:
        """Stats report."""
        stats = self.history.stats()
        if not stats:
            return "Aucune exécution sandbox enregistrée."
        lines = ["**Statistiques sandbox :**\n"]
        for cat, s in stats.items():
            rate = s["success_rate"] * 100
            lines.append(f"  `{cat}` : {s['count']} exécutions, {rate:.0f}% succès, moy. {s['avg_duration']:.2f}s")
        return "\n".join(lines)


# =============================================================================
# DÉTECTION DANGER : filtre les commandes distantes risquées
# =============================================================================

# Patterns de code dangereux à détecter avant d'envoyer sur un hôte
_DANGEROUS_PATTERNS = [
    re.compile(r"\b(rm\s+-rf?|shutil\.rmtree|os\.remove)\b", re.I),
    re.compile(r"\b(format\s*\(|mkfs|wipefs|dd\s+if=)\b", re.I),
    re.compile(r"\b(subprocess\.(?:run|Popen|call))\b", re.I),
    re.compile(r"\b(eval|exec)\s*\(", re.I),
    re.compile(r"__import__\s*\(", re.I),
]


def is_dangerous_code(code: str) -> Tuple[bool, str]:
    """
    Détecte du code potentiellement dangereux.
    Retourne (is_dangerous, reason).
    """
    for pat in _DANGEROUS_PATTERNS:
        m = pat.search(code)
        if m:
            return True, f"Pattern dangereux détecté : `{m.group(0)}`"
    return False, ""


# =============================================================================
# INTÉGRATION NOKIDO — handler @code / @test / @sandbox
# =============================================================================


async def handle_code_command(
    sandbox: "CodeSandbox",
    sub: str,
    args: str,
    chat_write: object,
) -> None:
    """
    Dispatcher pour les commandes @code, @test, @sandbox.
    chat_write = callable(text) pour écrire dans le chat Textual.
    """
    if sub == "code" or sub == "gen":
        if not args:
            chat_write("Usage : `@code <description de ce que le code doit faire>`")
            return
        chat_write(f"[dim]🐍 Génération + test sandbox : {args[:60]}…[/]")
        result = await sandbox.generate_and_test(args)
        chat_write(result.summary())

    elif sub == "test":
        if not args:
            chat_write("Usage : `@test <code python>`")
            return
        dangerous, reason = is_dangerous_code(args)
        if dangerous:
            chat_write(f"[bold red]🛡 Sandbox bloqué — {reason}[/]")
            return
        chat_write("[dim]🧪 Test du code…[/]")
        result = await sandbox.test_code(args)
        chat_write(result.summary())

    elif sub == "sandbox":
        if args.strip().lower() == "status":
            chat_write(sandbox.stats_report())
        else:
            chat_write("Usage : `@sandbox status`")

    else:
        chat_write(
            "`@code <desc>` — génère + teste du code Python\n"
            "`@test <code>` — teste du code directement\n"
            "`@sandbox status` — statistiques d'exécution"
        )


# =============================================================================
# SINGLETON GLOBAL
# =============================================================================
_global_sandbox: Optional[CodeSandbox] = None


def get_sandbox(
    ollama_url: str = "http://localhost:11434/api/chat",
    model: str = "llama3",
    rag_engine: object = None,
    max_retries: int = 2,
    timeout: float = 5.0,
) -> CodeSandbox:
    """Get sandbox.

    Args:
        ollama_url: Description.
        model: Description.
        rag_engine: Description.
        max_retries: Description.
        timeout: Description.
    """
    from nokido_agent.app.forge_app_context import app_ctx as _actx

    _ac = _actx()
    rag_engine = _ac.rag_engine
    global _global_sandbox
    if _global_sandbox is None:
        codegen = OllamaCodeGen(ollama_url=ollama_url, model=model)
        runner = SafeRunner(timeout=timeout)
        _global_sandbox = CodeSandbox(
            codegen=codegen,
            runner=runner,
            rag_engine=rag_engine,
            max_retries=max_retries,
        )
    return _global_sandbox


# =============================================================================
# § 3 — AUTO-AMÉLIORATION  (ex-loops.py)
# =============================================================================

MEMORY_FILE = Path(__file__).resolve().parent.parent / "data" / ".improvement_memory.json"


# =============================================================================
# ANALYSE STATIQUE DU CODE
# =============================================================================


def validate_python_syntax(code: str) -> Tuple[bool, str]:
    """Retourne (ok, message). Bloque tout patch invalide."""
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError ligne {e.lineno}: {e.msg}"
    except Exception as e:
        return False, str(e)


async def pylint_score(code: str) -> float:
    """
    Lance pylint en subprocess async sur le code.
    Retourne un score [0.0 .. 10.0]. Retourne 5.0 si pylint absent.
    Point 1 corrigé : signal de qualité réel, pas seulement heuristique.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3",
            "-c",
            f"import pylint.lint, sys; "
            f"from io import StringIO; "
            f"import tempfile, os; "
            f"f=tempfile.NamedTemporaryFile(suffix='.py',delete=False,mode='w'); "
            f"f.write({repr(code)}); f.close(); "
            f"from pylint.lint import Run; "
            f"from pylint.reporters.text import TextReporter; "
            f"out=StringIO(); "
            f"r=TextReporter(out); "
            f"Run([f.name,'--score=y','--disable=all','--enable=E,W'], reporter=r, exit=False); "
            f"os.unlink(f.name); "
            f"txt=out.getvalue(); "
            f"import re; m=re.search(r'rated at ([\\d.]+)', txt); "
            f"print(m.group(1) if m else '5.0')",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        score_str = out.decode().strip().split("\n")[-1]
        return max(0.0, min(10.0, float(score_str)))
    except Exception:
        return 5.0


def count_real_errors(code: str) -> int:
    """
    Score d'erreurs statiques [0..∞].
    Combine : syntaxe + heuristiques de mauvaises pratiques.
    """
    ok, _ = validate_python_syntax(code)
    if not ok:
        return 100

    count = 0
    lines = code.splitlines()
    for idx, line in enumerate(lines):
        s = line.strip()
        if s == "except Exception:" or re.match(r"^except\s*:", s):
            count += 2
        if re.match(r"^except", s) and idx + 1 < len(lines):
            if lines[idx + 1].strip() == "pass":
                count += 1
        if re.match(r"#\s*(TODO|FIXME|HACK)\b", s, re.IGNORECASE):
            count += 1

    for imp in re.findall(r"^import\s+(\w+)", code, re.MULTILINE):
        if len(re.findall(rf"\b{re.escape(imp)}\b", code)) <= 1:
            count += 1

    for blt in ("list", "dict", "set", "type", "id", "input"):
        if re.search(rf"^\s*{blt}\s*=", code, re.MULTILINE):
            count += 1

    return count


def score_code_quality(code: str) -> int:
    """Score heuristique [0..100]."""
    ok, _ = validate_python_syntax(code)
    if not ok:
        return 0
    score = 50
    lines = code.splitlines()
    if 30 < len(lines) < 8000:
        score += 10
    score += min(10, code.count('"""') + code.count("'''"))
    score += min(10, code.count("except ") * 2)
    score += min(5, code.count("->") + code.count(": str") + code.count(": int"))
    score -= len(re.findall(r"print\(.*DEBUG", code, re.IGNORECASE)) * 3
    score -= len(re.findall(r"#\s*(TODO|FIXME)", code, re.IGNORECASE)) * 2
    return max(0, min(100, score))


def compute_diff_summary(before: str, after: str) -> str:
    """Compute diff summary.

    Args:
        before: Description.
        after: Description.
    """
    diff = list(
        difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile="avant", tofile="après", n=2
        )
    )
    if not diff:
        return "(aucun changement)"
    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    samples = [l.strip()[:70] for l in diff if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))][:3]
    return f"+{added}/-{removed} lignes\n  " + "\n  ".join(samples)


# =============================================================================
# AUDIT PARSER (de TON code — complémentaire à count_real_errors)
# =============================================================================


class AuditParser:
    """
    Parse les réponses textuelles des LLMs (audits).
    Complémentaire à count_real_errors qui analyse le CODE.
    AuditParser analyse ce que le LLM dit sur le code.
    """

    SUGGESTION_RE = re.compile(
        r"(?:Suggestion|Fix|Correction|Patch)\s*[#°N]*\s*(\d+)\s*[:\-]\s*(.*?)\n```python\n(.*?)\n```",
        re.DOTALL | re.IGNORECASE,
    )
    CLEAN_PHRASES = [
        "aucun problème",
        "no issues",
        "code is clean",
        "aucune erreur",
        "no errors found",
        "looks good",
        "bien structuré",
        "no bugs",
        "nothing to fix",
        "pas d'erreur",
    ]

    @classmethod
    def extract_suggestions(cls, text: str) -> List[Dict]:
        """Extract suggestions.

        Args:
            cls: Description.
            text: Description.
        """
        suggestions = []
        for m in cls.SUGGESTION_RE.finditer(text):
            code = m.group(3).strip()
            ok, _ = validate_python_syntax(code)
            suggestions.append(
                {
                    "num": int(m.group(1)),
                    "description": m.group(2).strip(),
                    "code": code,
                    "syntax_ok": ok,
                }
            )
        # Fallback : bloc python seul
        if not suggestions:
            m = re.search(r"```python\n(.*?)\n```", text, re.DOTALL)
            if m:
                code = m.group(1).strip()
                ok, _ = validate_python_syntax(code)
                dm = re.search(r"(?:fix|corriger?|améliorer?|problème|erreur)[^.]{5,80}\.", text[:600], re.IGNORECASE)
                suggestions.append(
                    {
                        "num": 1,
                        "description": dm.group(0)[:80] if dm else "Correction proposée",
                        "code": code,
                        "syntax_ok": ok,
                    }
                )
        return suggestions

    @classmethod
    def count_audit_errors(cls, text: str) -> int:
        """Erreurs mentionnées dans le TEXTE d'audit (pas dans le code)."""
        suggestions = cls.extract_suggestions(text)
        raw = len(re.findall(r"\b(error|erreur|bug|exception|problème|issue|warning)\b", text, re.IGNORECASE))
        return max(len(suggestions), raw // 3)

    @classmethod
    def is_clean(cls, text: str) -> bool:
        """Is clean.

        Args:
            cls: Description.
            text: Description.
        """
        has_clean = any(p in text.lower() for p in cls.CLEAN_PHRASES)
        return has_clean and not cls.extract_suggestions(text)


# =============================================================================
# MÉMOIRE D'APPRENTISSAGE
# =============================================================================


@dataclass
class ErrorMemory:
    """
    Mémoire persistante cross-boucles.
    Point 2 corrigé : sauvegardée sur disque après chaque mise à jour.
    """

    version_history: List[Dict] = field(default_factory=list)
    error_patterns: List[str] = field(default_factory=list)
    failed_approaches: List[str] = field(default_factory=list)
    successful_fixes: List[str] = field(default_factory=list)
    syntax_errors: List[str] = field(default_factory=list)
    rag_snippets: List[str] = field(default_factory=list)
    best_version: Optional[str] = None
    best_error_count: int = 9999
    best_pylint_score: float = 0.0

    # ── Mutations ─────────────────────────────────────────────────────────────

    def record_version(self, version: str, errors: int, pylint: float, fix_desc: str, result: str) -> None:
        """Record version.

        Args:
            version: Description.
            errors: Description.
            pylint: Description.
            fix_desc: Description.
            result: Description.
        """
        self.version_history.append(
            {
                "version": version,
                "errors": errors,
                "pylint": pylint,
                "fix": fix_desc[:80],
                "result": result,
            }
        )
        if result == "ok" and (
            errors < self.best_error_count or (errors == self.best_error_count and pylint > self.best_pylint_score)
        ):
            self.best_error_count = errors
            self.best_pylint_score = pylint
            self.best_version = version
        self._save()

    def record_failure(self, approach: str) -> None:
        """Record failure.

        Args:
            approach: Description.
        """
        key = approach[:100]
        if key not in self.failed_approaches:
            self.failed_approaches.append(key)
            self._save()

    def record_success(self, fix: str) -> None:
        """Record success.

        Args:
            fix: Description.
        """
        key = fix[:100]
        if key not in self.successful_fixes:
            self.successful_fixes.append(key)
            self._save()

    def add_rag(self, content: str) -> None:
        """Add rag.

        Args:
            content: Description.
        """
        t = content[:400]
        if t not in self.rag_snippets:
            self.rag_snippets.append(t)

    def build_prompt_context(self, model_ctx_limit: int = 3000) -> str:
        """
        Contexte à injecter dans les prompts.
        Point 4 corrigé : limité selon la capacité du modèle.
        """
        parts = []
        if self.version_history:
            parts.append("── HISTORIQUE DES VERSIONS ──")
            for v in self.version_history[-8:]:
                icon = "✅" if v["result"] == "ok" else "❌"
                parts.append(
                    f"  {icon} v{v['version']} → {v['errors']} erreurs pylint={v['pylint']:.1f}/10 | fix: {v['fix']}"
                )
        if self.failed_approaches:
            parts.append("\n── APPROCHES ÉCHOUÉES — NE PAS RÉESSAYER ──")
            for f in self.failed_approaches[-6:]:
                parts.append(f"  ✗ {f}")
        if self.successful_fixes:
            parts.append("\n── CORRECTIONS QUI ONT FONCTIONNÉ ──")
            for s in self.successful_fixes[-4:]:
                parts.append(f"  ✓ {s}")
        if self.error_patterns:
            parts.append("\n── PATTERNS D'ERREUR RÉCURRENTS ──")
            for p in self.error_patterns[-5:]:
                parts.append(f"  • {p}")
        if self.syntax_errors:
            parts.append("\n── PATCHES REJETÉS (SYNTAXE INVALIDE) ──")
            for e in self.syntax_errors[-3:]:
                parts.append(f"  ⚠ {e}")

        result = "\n".join(parts)
        # Limite selon capacité du modèle (Point 4)
        return result[:model_ctx_limit] if result else "(première itération)"

    # ── Persistance disque (Point 2) ─────────────────────────────────────────

    def _save(self) -> None:
        """Save."""
        try:
            tmp = MEMORY_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(MEMORY_FILE)
        except Exception as e:
            logger.warning(f"ErrorMemory save: {e}")

    @classmethod
    def load(cls) -> "ErrorMemory":
        """Load.

        Args:
            cls: Description.
        """
        if MEMORY_FILE.exists():
            try:
                data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except Exception as e:
                logger.warning(f"ErrorMemory load: {e}")
        return cls()

    def clear(self) -> None:
        """Clear."""
        self.__init__()
        if MEMORY_FILE.exists():
            MEMORY_FILE.unlink(missing_ok=True)


# =============================================================================
# ÉTAT DE SESSION
# =============================================================================


@dataclass
class LoopIteration:
    iteration: int
    loop_number: int
    version_before: str
    version_after: Optional[str]
    errors_before: int
    errors_after: int
    success: bool
    rollback: bool = False
    rag_fed: bool = False
    syntax_valid: bool = True
    notes: str = ""


@dataclass
class LoopState:
    total_failures: int = 0
    loop1_iterations: int = 0
    loop2_iterations: int = 0
    loop3_iterations: int = 0
    last_successful_version: Optional[str] = None
    rag_error_docs: List[Dict] = field(default_factory=list)
    iterations: List[LoopIteration] = field(default_factory=list)
    memory: ErrorMemory = field(default_factory=ErrorMemory)


# =============================================================================
# APPEL LLM — retry + backoff
# =============================================================================


def _ctx_limit(model: str) -> int:
    """
    Estime la limite de contexte par nom de modèle.
    Point 4 : adapte la taille du contexte injecté.
    """
    ml = model.lower()
    if any(k in ml for k in ("llama3.3", "qwen3", "deepseek-r1", "72b", "70b")):
        return 3000  # grands modèles : contexte complet
    if any(k in ml for k in ("32b", "qwen2.5-coder:32")):
        return 2500
    if any(k in ml for k in ("14b", "13b")):
        return 2000
    return 1500  # petits modèles (7b/8b) : contexte réduit


async def _call_model(
    model: str,
    prompt: str,
    ollama_url: str,
    timeout: int = 180,
    retries: int = 2,
    system_prompt: str = "",
) -> str:
    """Appel Ollama streaming avec retry + backoff exponentiel.

    Si system_prompt est fourni, il est envoyé dans un message {role:system}
    séparé — le modèle reçoit ainsi son rôle via le canal prévu à cet effet,
    ce qui réduit les refus de rôle sur les API qui filtrent le contenu user.
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    for attempt in range(retries + 1):
        full = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    ollama_url,
                    json={"model": model, "messages": messages, "stream": True},
                    timeout=aiohttp.ClientTimeout(total=timeout, connect=10),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"Ollama HTTP {resp.status} ({model})")
                        break
                    async for raw in resp.content:
                        if not raw:
                            continue
                        try:
                            data = json.loads(raw.decode("utf-8", errors="replace").strip())
                            tok = data.get("message", {}).get("content", "")
                            if tok:
                                full.append(tok)
                            if data.get("done"):
                                break
                        except Exception:
                            continue
            result = "".join(full)
            if result.strip():
                return result
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            logger.warning(f"_call_model {model} tentative {attempt + 1}: {e}")
        if attempt < retries:
            await asyncio.sleep(2**attempt)
    return ""


# =============================================================================
# BASE DES BOUCLES D'AMÉLIORATION
# =============================================================================


class BaseLoop:
    """Classe de base pour les boucles d'auto-amélioration.

    Fournit les helpers communs : recherche RAG, on_restart,
    enregistrement d'itération, logging RAG.
    """

    MAX_ITER = 6

    def __init__(self, orc: "RoleOrchestrator", ollama_url: str) -> None:
        """Init.

        Args:
            orc: Description.
            ollama_url: Description.
        """
        self.orc = orc
        self.ollama_url = ollama_url

    async def run(
        self,
        vm: object,
        rag: object,
        state: LoopState,
        log_fn: Callable,
        on_patch: Callable,
        on_restart: Optional[Callable] = None,
    ) -> Tuple[bool, LoopState]:
        """Run.

        Args:
            vm: Description.
            rag: Description.
            state: Description.
            log_fn: Description.
            on_patch: Description.
            on_restart: Description.
        """
        raise NotImplementedError

    # ── Helpers communs ─────────────────────────────────────────────

    async def _fetch_rag(self, rag: object, query: str, k: int = 3, max_chars: int = 250) -> str:
        """Recherche RAG, retourne le contexte concaténé."""
        if not rag:
            return ""
        try:
            docs = await rag.search(query, k=k)
            return "\n".join(d["content"][:max_chars] for d in docs)
        except Exception:
            return ""

    async def _fetch_rag_with_mem(self, rag: object, mem: object, query: str, k: int = 3, max_chars: int = 250) -> str:
        """Recherche RAG, alimente la mémoire, retourne le contexte."""
        if not rag:
            return ""
        try:
            docs = await rag.search(query, k=k)
            ctx = "\n".join(d["content"][:max_chars] for d in docs)
            for d in docs:
                mem.add_rag(d["content"])
            return ctx
        except Exception:
            return ""

    async def _try_on_restart(self, on_restart: Optional[Callable]) -> None:
        """Appelle on_restart (sync ou async) avec guard."""
        if not on_restart:
            return
        try:
            if asyncio.iscoroutinefunction(on_restart):
                await on_restart()
            else:
                on_restart()
        except Exception as e:
            logger.warning(f"on_restart: {e}")

    async def _log_to_rag(self, rag: object, tag: str, msg: str) -> None:
        """Enregistre un message dans le RAG de session."""
        if not rag:
            return
        try:
            await rag.add_session_message("improvement_loop", tag, msg)
        except Exception:
            pass

    def _record_iter(
        self,
        state: LoopState,
        loop_num: int,
        iter_num: int,
        ver_before: object,
        ver_after: object,
        err_before: int,
        err_after: int,
        success: bool,
        notes: str,
    ) -> None:
        """Ajoute une itération au state."""
        state.iterations.append(
            LoopIteration(
                iter_num,
                loop_num,
                ver_before,
                ver_after,
                err_before,
                err_after,
                success=success,
                notes=notes,
            )
        )


# =============================================================================
# BOUCLE 1 — AUTO-REPAIR AUTO-APPRENANT
# =============================================================================


class AutoRepairLoop(BaseLoop):
    """
    Audit dual → valide syntaxe → mesure progression réelle →
    alimente mémoire → rollback intelligent vers best_version.

    on_restart (de TON code) : appelé après chaque patch appliqué avec succès.
    Ne fait PAS return immédiat : on_restart peut relancer le process (os.execv),
    mais la boucle continue pour mesurer la progression sur la nouvelle base.
    """

    MAX_ITER = 6
    STALL_LIMIT = 2

    async def run(
        self,
        vm: object,
        rag: object,
        state: LoopState,
        log_fn: Callable,
        on_patch: Callable,
        on_restart: Optional[Callable] = None,
    ) -> Tuple[bool, LoopState]:
        """Run.

        Args:
            vm: Description.
            rag: Description.
            state: Description.
            log_fn: Description.
            on_patch: Description.
            on_restart: Description.
        """
        log_fn("\n[bold #58a6ff]━━━ BOUCLE 1 : Auto-Repair ━━━[/]")
        assignments = await self.orc.assign_roles(1, True, log_fn)
        debugger = assignments.get(AgentRole.DEBUGGER)
        analyste = assignments.get(AgentRole.ANALYSTE) or debugger
        if not debugger:
            log_fn("[red]❌ Aucun modèle DEBUGGER disponible.[/]")
            return False, state

        stall_count = 0
        mem = state.memory
        dbg_ctx_lim = _ctx_limit(debugger)

        for i in range(1, self.MAX_ITER + 1):
            state.loop1_iterations += 1
            code = vm.get_current_code()
            ver_before = vm.current_version
            errors_now = count_real_errors(code)
            quality = score_code_quality(code)

            log_fn(
                f"\n[dim]── B1 itération {i}/{self.MAX_ITER} "
                f"[bold]v{ver_before}[/] — {errors_now} erreurs, "
                f"qualité={quality}/100[/]"
            )

            if errors_now == 0 and quality >= 70:
                log_fn("[green]✅ Code propre.[/]")
                mem.record_version(ver_before, 0, 10.0, "code propre", "ok")
                state.last_successful_version = ver_before
                return True, state

            # Lire RAG
            rag_ctx = await self._fetch_rag_with_mem(
                rag, mem, ROLE_RAG_QUERIES[AgentRole.DEBUGGER] + f" v{ver_before}", k=3
            )

            ctx = mem.build_prompt_context(model_ctx_limit=dbg_ctx_lim)

            # ── Prompts enrichis ──────────────────────────────────────────
            prompt_dbg = f"""╔══ CONTEXTE SESSION ══╗
{ctx}
╚══════════════════════╝

VERSION COURANTE : v{ver_before}
MÉTRIQUES : {errors_now} erreurs, qualité={quality}/100
{("CONTEXTE RAG :\n" + rag_ctx) if rag_ctx else ""}

INSTRUCTIONS :
1. Identifie le bug le plus critique
2. UNE seule correction complète
3. N'utilise PAS les approches ✗ ci-dessus
4. Code Python COMPLET et valide dans ```python
5. Format : Suggestion 1 : [titre]\n```python\n[code]\n```

CODE (v{ver_before}) :
```python
{code[:8000]}
```"""

            prompt_anl = f"""CONTEXTE SESSION :
{mem.build_prompt_context(model_ctx_limit=_ctx_limit(analyste))}

VERSION : v{ver_before}
Identifie les 3 problèmes structurels. Sois concis.

```python
{code[:4000]}
```"""

            log_fn(f"  🔧 DEBUGGER[{debugger}] + 🔍 ANALYSTE[{analyste}]…")
            t0 = time.perf_counter()
            r_dbg, r_anl = await asyncio.gather(
                _call_model(
                    debugger, prompt_dbg, self.ollama_url, system_prompt=ROLE_SYSTEM_PROMPTS[AgentRole.DEBUGGER]
                ),
                _call_model(
                    analyste, prompt_anl, self.ollama_url, system_prompt=ROLE_SYSTEM_PROMPTS[AgentRole.ANALYSTE]
                ),
                return_exceptions=True,
            )
            log_fn(f"  ⏱ {time.perf_counter() - t0:.1f}s")

            dbg_reply = r_dbg if isinstance(r_dbg, str) else ""
            anl_reply = r_anl if isinstance(r_anl, str) else ""

            if not dbg_reply:
                log_fn("  [red]❌ DEBUGGER sans réponse.[/]")
                stall_count += 1
                mem.record_failure(f"B1-i{i}: DEBUGGER timeout")
                continue

            # Patterns structurels depuis analyste
            if anl_reply:
                for line in anl_reply.splitlines():
                    if any(k in line.lower() for k in ["problème", "bug", "erreur", "issue"]):
                        mem.error_patterns.append(f"[v{ver_before}] {line.strip()[:90]}")

            # Audit LLM indique code propre ?
            if AuditParser.is_clean(dbg_reply) and errors_now <= 2:
                log_fn("[green]✅ Audit : code propre.[/]")
                pl = await pylint_score(code)
                mem.record_version(ver_before, errors_now, pl, "audit clean", "ok")
                state.last_successful_version = ver_before
                return True, state

            # Extraire suggestions
            suggestions = AuditParser.extract_suggestions(dbg_reply)
            if not suggestions:
                log_fn("  [yellow]⚠ Aucune suggestion parsable.[/]")
                stall_count += 1
                mem.record_failure(f"B1-i{i}: réponse non parsable")
                await self._log_to_rag(rag, "b1_nopatch", f"[v{ver_before}] DEBUGGER non parsable: {dbg_reply[:300]}")
                continue

            sugg = suggestions[0]
            log_fn(f"  📌 {sugg['description'][:70]}")

            # Valider syntaxe — OBLIGATOIRE
            if not sugg["syntax_ok"]:
                _, syn_err = validate_python_syntax(sugg["code"])
                log_fn(f"  [red]✗ Syntaxe invalide : {syn_err}[/]")
                mem.syntax_errors.append(f"[v{ver_before}] {syn_err}")
                mem.record_failure(f"B1-i{i}: syntax error — {syn_err[:50]}")
                stall_count += 1
                continue

            # Détecter patch identique
            if sugg["code"].strip() == code.strip():
                log_fn("  [yellow]⚠ Patch identique — ignoré.[/]")
                mem.record_failure(f"B1-i{i}: patch identique")
                stall_count += 1
                continue

            diff_sum = compute_diff_summary(code, sugg["code"])
            log_fn(f"  📝 {diff_sum.splitlines()[0]}")

            # Appliquer
            new_path = await on_patch(
                sugg["code"],
                f"fix(v{ver_before}→B1-i{i}): {sugg['description'][:60]}",
                False,
            )
            if not new_path:
                log_fn("  [red]❌ on_patch échoué.[/]")
                stall_count += 1
                continue

            # ── Mesurer la progression réelle ─────────────────────────────
            ver_after = vm.current_version
            new_code = vm.get_current_code()
            errors_new = count_real_errors(new_code)
            quality_new = score_code_quality(new_code)
            pl_new = await pylint_score(new_code)  # Point 1 : pylint réel

            log_fn(
                f"  [bold]v{ver_before} → v{ver_after}[/]  "
                f"erreurs: {errors_now}→{errors_new}  "
                f"qualité: {quality}→{quality_new}  "
                f"pylint: {pl_new:.1f}/10"
            )

            progressed = errors_new < errors_now or pl_new > (mem.best_pylint_score + 0.3)

            if progressed:
                log_fn("  [green]✅ Progression confirmée[/]")
                mem.record_success(sugg["description"])
                mem.record_version(ver_after, errors_new, pl_new, sugg["description"], "ok")
                stall_count = 0
            else:
                log_fn("  [yellow]⚠ Pas de progression mesurable[/]")
                mem.record_failure(sugg["description"])
                mem.record_version(ver_after, errors_new, pl_new, sugg["description"], "fail")
                stall_count += 1

            # Alimenter RAG
            await self._log_to_rag(
                rag,
                "b1_result",
                f"[v{ver_before}→v{ver_after}] {sugg['description']} "
                f"| {errors_now}→{errors_new} erreurs | pylint={pl_new:.1f}",
            )
            state.rag_error_docs.append({"id": f"b1_i{i}", "version": ver_after, "errors": errors_new})

            self._record_iter(
                state, 1, i, ver_before, ver_after, errors_now, errors_new, progressed, diff_sum.splitlines()[0]
            )

            # on_restart : appelé après chaque patch réussi
            if new_path:
                await self._try_on_restart(on_restart)

            # Rollback intelligent si stagnation (Point 3 : can_rollback_to)
            if stall_count >= self.STALL_LIMIT:
                if mem.best_version and mem.best_version != ver_after:
                    # Point 3 : vérifier avant rollback
                    if vm.can_rollback_to(mem.best_version):
                        log_fn(f"  [yellow]⟳ Stagnation → rollback v{mem.best_version} ({mem.best_error_count} err)[/]")
                        vm.rollback(mem.best_version)
                        mem.record_failure(f"B1 stagnation à v{ver_after}")
                        state.total_failures += 1
                        stall_count = 0
                    else:
                        log_fn(f"  [yellow]⚠ v{mem.best_version} inaccessible pour rollback — continue[/]")
                        stall_count = 0
                else:
                    stall_count = 0

        log_fn(f"[red]❌ B1 : {self.MAX_ITER} itérations sans code propre.[/]")
        state.total_failures += 1
        return False, state


# =============================================================================
# BOUCLE 2 — FORK GUIDÉ PAR MÉMOIRE
# =============================================================================


class ForkEstimLoop(BaseLoop):
    """
    Rollback vers best_version connue → STRATÈGE approche radicalement différente
    → DEBUGGER valide → applique.
    Point 3 : can_rollback_to() vérifié avant rollback.
    """

    MAX_ITER = 4

    async def run(
        self,
        vm: object,
        rag: object,
        state: LoopState,
        log_fn: Callable,
        on_patch: Callable,
        on_restart: Optional[Callable] = None,
    ) -> Tuple[bool, LoopState]:
        """Run.

        Args:
            vm: Description.
            rag: Description.
            state: Description.
            log_fn: Description.
            on_patch: Description.
            on_restart: Description.
        """
        log_fn("\n[bold #f0883e]━━━ BOUCLE 2 : Fork / Estim ━━━[/]")
        mem = state.memory

        # Rollback vers meilleure version connue (Point 3 : can_rollback_to)
        if mem.best_version and vm.can_rollback_to(mem.best_version):
            log_fn(
                f"  ↩ Rollback vers v{mem.best_version} "
                f"({mem.best_error_count} erreurs, "
                f"pylint={mem.best_pylint_score:.1f})"
            )
            vm.rollback(mem.best_version)
        elif mem.best_version:
            log_fn(f"  [yellow]⚠ v{mem.best_version} inaccessible — continuation depuis v{vm.current_version}[/]")
        else:
            log_fn("  [yellow]⚠ Pas de meilleure version connue.[/]")

        assignments = await self.orc.assign_roles(2, False, log_fn)
        stratege = assignments.get(AgentRole.STRATEGE)
        debugger = assignments.get(AgentRole.DEBUGGER) or stratege
        if not stratege:
            log_fn("[red]❌ Aucun STRATÈGE disponible.[/]")
            return False, state

        for i in range(1, self.MAX_ITER + 1):
            state.loop2_iterations += 1
            code = vm.get_current_code()
            ver_before = vm.current_version
            errors_now = count_real_errors(code)
            ctx = mem.build_prompt_context(_ctx_limit(stratege))

            log_fn(f"\n[dim]── B2 fork {i}/{self.MAX_ITER} [bold]v{ver_before}[/] — {errors_now} erreurs[/]")

            rag_ctx = await self._fetch_rag_with_mem(rag, mem, ROLE_RAG_QUERIES[AgentRole.STRATEGE], k=3)

            log_fn(f"  🏗 STRATÈGE [{stratege}]…")
            prompt_fork = f"""╔══ CONTEXTE SESSION ══╗
{ctx}
╚══════════════════════╝

VERSION ACTUELLE : v{ver_before} — {errors_now} erreurs
{("CONTEXTE RAG :\n" + rag_ctx) if rag_ctx else ""}

MISSION : Approche ARCHITECTURALEMENT DIFFÉRENTE.
Ne répète PAS les patterns ✗ ci-dessus.
Code Python COMPLET dans ```python.

CODE ACTUEL (v{ver_before}) :
```python
{code[:6000]}
```"""

            fork_reply = await _call_model(
                stratege,
                prompt_fork,
                self.ollama_url,
                timeout=240,
                system_prompt=ROLE_SYSTEM_PROMPTS[AgentRole.STRATEGE],
            )
            if not fork_reply:
                log_fn("  [red]❌ STRATÈGE timeout.[/]")
                mem.record_failure(f"B2-i{i}: STRATÈGE vide")
                state.total_failures += 1
                continue

            proposal = AuditParser.extract_suggestions(fork_reply)
            prop_code = proposal[0]["code"] if proposal else None
            if not prop_code:
                # Fallback : bloc python direct
                m = re.search(r"```python\n(.*?)\n```", fork_reply, re.DOTALL)
                prop_code = m.group(1).strip() if m else None

            if not prop_code:
                log_fn("  [red]❌ Pas de code extractible.[/]")
                mem.record_failure(f"B2-i{i}: pas de code STRATÈGE")
                state.total_failures += 1
                continue

            ok, syn_err = validate_python_syntax(prop_code)
            if not ok:
                log_fn(f"  [red]✗ Syntaxe invalide : {syn_err}[/]")
                mem.syntax_errors.append(f"[B2 v{ver_before}] {syn_err}")
                mem.record_failure(f"B2-i{i}: syntax error")
                state.total_failures += 1
                continue

            if prop_code.strip() == code.strip():
                log_fn("  [yellow]⚠ Proposition identique — ignorée.[/]")
                mem.record_failure(f"B2-i{i}: identique")
                continue

            errors_prop = count_real_errors(prop_code)
            diff_sum = compute_diff_summary(code, prop_code)

            # DEBUGGER valide (Point 3 : explicite)
            log_fn(f"  🔧 DEBUGGER [{debugger}] valide ({errors_prop} erreurs prop)…")
            ctx_dbg = mem.build_prompt_context(_ctx_limit(debugger))
            prompt_val = f"""CONTEXTE : {ctx_dbg}

Original : v{ver_before} — {errors_now} erreurs
Proposition : {errors_prop} erreurs | {diff_sum.splitlines()[0]}

RÉPONDS SUR LA PREMIÈRE LIGNE :
  APPROUVÉ  — si meilleure et valide
  REJETÉ : [raison]

```python (original)
{code[:1500]}
```

```python (proposition)
{prop_code[:2500]}
```"""

            val_reply = await _call_model(
                debugger,
                prompt_val,
                self.ollama_url,
                timeout=120,
                system_prompt=ROLE_SYSTEM_PROMPTS[AgentRole.DEBUGGER],
            )
            approved = bool(val_reply and re.search(r"\bAPPROUV[EÉ]\b", val_reply, re.IGNORECASE))

            if not approved:
                m = re.search(r"rejet[eé][^:]*:\s*(.{5,120})", val_reply or "", re.IGNORECASE)
                reason = m.group(1).strip() if m else (val_reply or "")[:80]
                log_fn(f"  [yellow]⚠ Rejeté : {reason}[/]")
                mem.record_failure(f"B2-i{i}: rejeté — {reason[:50]}")
                state.total_failures += 1
                continue

            new_path = await on_patch(
                prop_code,
                f"feat(v{ver_before}→B2-fork{i}): approche alternative",
                major=True,
            )
            if new_path:
                ver_after = vm.current_version
                errors_new = count_real_errors(vm.get_current_code())
                pl_new = await pylint_score(vm.get_current_code())
                log_fn(
                    f"  [green]✅ v{ver_before}→v{ver_after} "
                    f"({errors_now}→{errors_new} erreurs, pylint={pl_new:.1f})[/]"
                )
                mem.record_version(ver_after, errors_new, pl_new, f"fork B2-i{i}", "ok")
                mem.record_success(f"fork B2-i{i}")
                state.last_successful_version = ver_after
                self._record_iter(
                    state, 2, i, ver_before, ver_after, errors_now, errors_new, True, diff_sum.splitlines()[0]
                )
                await self._try_on_restart(on_restart)
                await self._log_to_rag(
                    rag,
                    "b2_ok",
                    f"[v{ver_before}→v{ver_after}] fork réussi {errors_now}→{errors_new} err pylint={pl_new:.1f}",
                )
                return True, state

            log_fn("  [red]❌ on_patch échoué.[/]")
            state.total_failures += 1

        log_fn("[red]❌ B2 : aucun fork validé.[/]")
        state.total_failures += 1
        return False, state


# =============================================================================
# BOUCLE 3 — DÉBAT COLLÉGIAL AUTO-APPRENANT
# =============================================================================


def parse_classement(reply: str, label_to_role: Dict[str, str]) -> Dict[str, int]:
    """Rend {role: rang} depuis la reponse du comparateur. Rang 0 = le meilleur.

    Un classement PARTIEL est rendu tel quel (moins d'entrees que d'etiquettes) :
    c'est a l'appelant de le detecter et de retomber sur son heuristique. Ne
    JAMAIS completer un ordre manquant — un ordre invente serait indiscernable
    d'un vrai verdict, et c'est exactement le genre de silence qu'on paye plus
    tard en croyant avoir mesure quelque chose.

    Fonction de MODULE et non code en ligne, pour que le banc de mesure du biais
    de juge (tools/forge_council_bias_bench.py) note avec le parseur de
    PRODUCTION : mesurer une copie ne mesure pas ce qui tourne.
    """
    vus: List[str] = []
    queue = (reply or "").split("CLASSEMENT", 1)[-1]
    for tok in re.findall(r"\b[A-Z]+\b", queue):
        if tok in label_to_role and tok not in vus:
            vus.append(tok)
    return {label_to_role[lb]: pos for pos, lb in enumerate(vus)}


class CollegialDebateLoop(BaseLoop):
    """
    Propositions parallèles → COMPARATEUR note → JUGE synthèse.
    Toute la mémoire de session injectée dans chaque prompt.
    Point 3 : validation avant application.
    """

    MAX_ROUNDS = 3

    async def run(
        self,
        vm: object,
        rag: object,
        state: LoopState,
        log_fn: Callable,
        on_patch: Callable,
        on_restart: Optional[Callable] = None,
    ) -> Tuple[bool, LoopState]:
        """Run.

        Args:
            vm: Description.
            rag: Description.
            state: Description.
            log_fn: Description.
            on_patch: Description.
            on_restart: Description.
        """
        log_fn("\n[bold #3fb950]━━━ BOUCLE 3 : Débat Collégial ━━━[/]")
        mem = state.memory
        n_part = min(5, 2 + state.total_failures)
        log_fn(
            f"  Participants : {n_part} | "
            f"Mémoire : {len(mem.version_history)} versions, "
            f"{len(mem.failed_approaches)} échecs"
        )

        assignments = await self.orc.assign_roles(3, False, log_fn)

        for round_n in range(1, self.MAX_ROUNDS + 1):
            state.loop3_iterations += 1
            code = vm.get_current_code()
            ver_before = vm.current_version
            errors_now = count_real_errors(code)
            ctx = mem.build_prompt_context(2500)

            log_fn(f"\n[dim]── B3 round {round_n}/{self.MAX_ROUNDS} [bold]v{ver_before}[/] — {errors_now} erreurs[/]")

            rag_ctx = await self._fetch_rag(rag, "amélioration correction erreurs code", k=3, max_chars=200)

            # ── Phase 1 : propositions parallèles ────────────────────────
            debater_roles = [AgentRole.ANALYSTE, AgentRole.DEBUGGER, AgentRole.STRATEGE][:n_part]

            # Capture explicite pour éviter bug de closure
            _code_snap = code
            _ver_snap = ver_before
            _self = self

            async def _propose(
                role: AgentRole, code_snap: str = _code_snap, ver_snap: str = _ver_snap
            ) -> Tuple[str, Optional[str], str]:
                """Propose.

                Args:
                    role: Description.
                    code_snap: Description.
                    ver_snap: Description.
                """
                model = assignments.get(role)
                if not model:
                    return role.value, None, "?"
                role_rag = await _self._fetch_rag(rag, ROLE_RAG_QUERIES[role], k=2, max_chars=200)
                role_ctx = mem.build_prompt_context(_ctx_limit(model))
                prompt = f"""{ROLE_SYSTEM_PROMPTS[role]}

CONTEXTE SESSION :
{role_ctx}

VERSION : v{ver_snap} — {errors_now} erreurs
{("RAG :\n" + role_rag) if role_rag else ""}
{("CONTEXTE GLOBAL :\n" + rag_ctx) if rag_ctx else ""}

Propose ta meilleure correction. Code COMPLET dans ```python.
N'utilise PAS les approches ✗.

```python
{code_snap[:5000]}
```"""
                reply = await _call_model(
                    model, prompt, self.ollama_url, timeout=200, system_prompt=ROLE_SYSTEM_PROMPTS.get(role, "")
                )
                return role.value, reply, model

            log_fn(f"  📝 {len(debater_roles)} propositions en parallèle…")
            t0 = time.perf_counter()
            raw = await asyncio.gather(*[_propose(r) for r in debater_roles], return_exceptions=True)
            log_fn(f"  ⏱ {time.perf_counter() - t0:.1f}s")

            proposals: Dict[str, Tuple[str, str]] = {}
            for res in raw:
                if isinstance(res, Exception):
                    continue
                rname, reply, model_used = res
                if not reply:
                    log_fn(f"  [yellow]⚠ {rname.upper()} : vide[/]")
                    continue
                suggs = AuditParser.extract_suggestions(reply)
                extracted = suggs[0]["code"] if suggs else None
                if not extracted:
                    m = re.search(r"```python\n(.*?)\n```", reply, re.DOTALL)
                    extracted = m.group(1).strip() if m else None
                if not extracted:
                    continue
                ok, syn_err = validate_python_syntax(extracted)
                if not ok:
                    log_fn(f"  [red]✗ {rname.upper()} syntaxe : {syn_err}[/]")
                    mem.syntax_errors.append(f"[B3-r{round_n} {rname}] {syn_err}")
                    continue
                if extracted.strip() == code.strip():
                    log_fn(f"  [yellow]⚠ {rname.upper()} : identique — ignoré[/]")
                    continue
                ep = count_real_errors(extracted)
                proposals[rname] = (extracted, model_used)
                log_fn(f"  ✓ {rname.upper():12} [{model_used}] → {ep} erreurs")

            if not proposals:
                log_fn("  [red]❌ Aucune proposition valide ce round.[/]")
                mem.record_failure(f"B3-r{round_n}: zéro proposition valide")
                continue

            # ── Phase 2 : COMPARATEUR (classement RELATIF, auteurs masqués) ──
            # Avant : une note ISOLÉE par proposition, et le comparateur lisait le
            # nom du rôle (« Proposition DEBUGGER »). Deux défauts que le pattern
            # « LLM council » traite explicitement (karpathy/llm-council, ingéré en
            # RAG le 2026-08-04, cf. `label_to_model` dans backend/council.py) :
            #   - noter une proposition SEULE ne dit pas laquelle est meilleure ;
            #   - un juge qui reconnaît l'auteur peut le favoriser.
            # Les étiquettes A/B/C sont LOCALES : `label_to_role` ne quitte jamais
            # ce processus. `LAFORGE_COUNCIL_ANONYMIZE=0` restaure l'affichage
            # nominatif — c'est le TÉMOIN de la mesure : sans lui on ne saurait pas
            # si l'anonymisation change quoi que ce soit sur NOS modèles (l'effet
            # est constaté par karpathy sur des modèles cloud, pas ici).
            comparateur = assignments.get(AgentRole.COMPARATEUR)
            scores: List[Tuple[str, float, int]] = []
            anonymiser = os.getenv("LAFORGE_COUNCIL_ANONYMIZE", "1") != "0"
            ordre = list(proposals.items())
            label_to_role = {
                (chr(65 + i) if anonymiser else rn.upper()): rn
                for i, (rn, _) in enumerate(ordre)
            }
            role_to_label = {rn: lb for lb, rn in label_to_role.items()}

            rangs: Dict[str, int] = {}
            if comparateur and len(ordre) > 1:
                bloc = "\n\n".join(
                    f"=== Réponse {role_to_label[rn]} ({count_real_errors(c)} erreurs, "
                    f"qualité={score_code_quality(c)}/100) ===\n```python\n{c[:2000]}\n```"
                    for rn, (c, _) in ordre
                )
                prompt_cmp = (
                    f"v{ver_before} — {errors_now} erreurs actuelles\n\n"
                    f"{bloc}\n\n"
                    f"Classe CES {len(ordre)} réponses, de la meilleure à la pire.\n"
                    f"Format OBLIGATOIRE, rien d'autre :\n"
                    f"CLASSEMENT: {', '.join(role_to_label[rn] for rn, _ in ordre)}"
                )
                r = await _call_model(
                    comparateur,
                    prompt_cmp,
                    self.ollama_url,
                    timeout=90,
                    system_prompt=ROLE_SYSTEM_PROMPTS[AgentRole.COMPARATEUR],
                )
                rangs = parse_classement(r, label_to_role)
                if len(rangs) < len(ordre):
                    # Classement partiel ou illisible : on le DIT et on retombe sur
                    # la seule heuristique. On ne fabrique pas un ordre par défaut :
                    # un classement invente serait indiscernable d'un vrai verdict.
                    log_fn(
                        f"  [yellow]⚠ classement comparateur incomplet "
                        f"({len(rangs)}/{len(ordre)}) — heuristique seule[/]"
                    )

            for rname, (prop_code, model_used) in ordre:
                ep = count_real_errors(prop_code)
                qp = score_code_quality(prop_code)
                if rname in rangs and len(ordre) > 1:
                    llm_score = 100.0 * (len(ordre) - 1 - rangs[rname]) / (len(ordre) - 1)
                else:
                    llm_score = 50.0
                heuristic = max(0.0, 100.0 - ep * 5.0) * 0.4 + qp * 0.3
                final = llm_score * 0.3 + heuristic
                scores.append((rname, final, ep))
                log_fn(
                    f"    {rname:12} [{role_to_label[rname]}] score={final:.1f} "
                    f"(rang={rangs.get(rname, '?')} err={ep})"
                )

            scores.sort(key=lambda x: x[1], reverse=True)
            winner_name = scores[0][0]
            winner_errors = scores[0][2]
            winner_code = proposals[winner_name][0]
            winner_model = proposals[winner_name][1]
            log_fn(f"\n  🏆 [bold]{winner_name.upper()}[/] [{winner_model}] — {winner_errors} erreurs")

            # ── Phase 3 : JUGE ────────────────────────────────────────────
            juge = assignments.get(AgentRole.JUGE)
            final_code = winner_code

            if juge:
                log_fn(f"  ⚖ JUGE [{juge}]…")
                # Le juge lit les MÊMES étiquettes que le comparateur : anonymiser
                # la notation puis renommer les auteurs pour la synthèse rouvrirait
                # exactement la porte qu'on vient de fermer.
                all_txt = "\n\n".join(
                    f"=== Réponse {role_to_label[rn]} ({count_real_errors(c)} err) ===\n"
                    f"```python\n{c[:1200]}\n```"
                    for rn, (c, _) in proposals.items()
                )
                scores_txt = "\n".join(
                    f"  Réponse {role_to_label[rn]:3} score={sc:.1f} erreurs={er}"
                    for rn, sc, er in scores
                )
                juge_ctx = mem.build_prompt_context(_ctx_limit(juge))
                prompt_juge = f"""CONTEXTE SESSION :
{juge_ctx}

VERSION : v{ver_before} — {errors_now} erreurs

VOTES :
{scores_txt}

GAGNANT : Réponse {role_to_label[winner_name]} ({winner_errors} erreurs)

PROPOSITIONS :
{all_txt}

MISSION : Code final combinant le meilleur de chaque.
Évite les patterns ✗. Moins de {errors_now} erreurs.
Code dans ```python."""

                juge_reply = await _call_model(
                    juge, prompt_juge, self.ollama_url, timeout=240, system_prompt=ROLE_SYSTEM_PROMPTS[AgentRole.JUGE]
                )
                if juge_reply:
                    jsuggs = AuditParser.extract_suggestions(juge_reply)
                    jcode = jsuggs[0]["code"] if jsuggs else None
                    if not jcode:
                        m = re.search(r"```python\n(.*?)\n```", juge_reply, re.DOTALL)
                        jcode = m.group(1).strip() if m else None
                    if jcode:
                        ok, syn_err = validate_python_syntax(jcode)
                        if ok:
                            je = count_real_errors(jcode)
                            if je <= winner_errors:
                                final_code = jcode
                                log_fn(f"  → Verdict juge adopté ({je} erreurs)")
                            else:
                                log_fn(f"  → Verdict juge pire ({je}>{winner_errors}) — gardé vote")
                        else:
                            log_fn(f"  [yellow]⚠ Juge syntaxe invalide : {syn_err}[/]")
                            mem.syntax_errors.append(f"[B3 juge r{round_n}] {syn_err}")

            # Point 3 : vérifier que final_code est meilleur avant d'appliquer
            final_errors = count_real_errors(final_code)
            if final_errors >= errors_now:
                log_fn(f"  [yellow]⚠ Verdict ({final_errors}) pas meilleur ({errors_now}) — skip.[/]")
                mem.record_failure(f"B3-r{round_n}: verdict régressif")
                continue

            diff_sum = compute_diff_summary(code, final_code)
            new_path = await on_patch(
                final_code,
                f"feat(v{ver_before}→B3-r{round_n}): débat collégial ({errors_now}→{final_errors} erreurs)",
                major=True,
            )
            if new_path:
                ver_after = vm.current_version
                pl_new = await pylint_score(vm.get_current_code())
                log_fn(
                    f"  [green]✅ v{ver_before}→v{ver_after} "
                    f"({errors_now}→{final_errors} erreurs, pylint={pl_new:.1f})[/]"
                )
                mem.record_version(ver_after, final_errors, pl_new, f"débat r{round_n}", "ok")
                mem.record_success(f"B3 r{round_n} gagnant={winner_name}")
                state.last_successful_version = ver_after
                self._record_iter(
                    state, 3, round_n, ver_before, ver_after, errors_now, final_errors, True, diff_sum.splitlines()[0]
                )
                await self._try_on_restart(on_restart)
                # Trace MESURABLE. Sans le modèle du comparateur ET celui du gagnant
                # sur la même ligne, l'auto-favoritisme n'est pas testable (« le
                # comparateur choisit-il plus souvent une proposition écrite par SON
                # modèle ? »). Mesuré le 2026-08-04 : la trace précédente ne portait
                # que le nom du rôle, donc aucune campagne A/B n'était possible sur
                # l'historique — c'est ce manque qui rend `anonymise=` nécessaire ici.
                await self._log_to_rag(
                    rag,
                    "b3_ok",
                    f"[v{ver_before}→v{ver_after}] débat r{round_n} "
                    f"gagnant={winner_name} {errors_now}→{final_errors} err "
                    f"anonymise={int(anonymiser)} comparateur={comparateur or '-'} "
                    f"gagnant_modele={winner_model} "
                    f"auto_favoritisme={int(bool(comparateur) and comparateur == winner_model)}",
                )
                return True, state

        log_fn("[red]❌ B3 : aucun consensus appliqué.[/]")
        state.total_failures += 1
        return False, state


# =============================================================================
# ORCHESTRATEUR
# =============================================================================


class ImprovementOrchestrator:
    """
    Chaîne B1 → B2 → B3 avec mémoire partagée.
    Supporte le multi-fichiers via target_files.
    on_restart propagé à chaque boucle.
    """

    def __init__(self, ollama_url: str, ollama_tags_url: str) -> None:
        """Init.

        Args:
            ollama_url: Description.
            ollama_tags_url: Description.
        """
        self.orc = RoleOrchestrator(ollama_url, ollama_tags_url)
        self.loop1 = AutoRepairLoop(self.orc, ollama_url)
        self.loop2 = ForkEstimLoop(self.orc, ollama_url)
        self.loop3 = CollegialDebateLoop(self.orc, ollama_url)
        self.state = LoopState()
        self._running = False

    async def run(
        self,
        vm: object,
        rag: object,
        log_fn: Callable = print,
        on_done: Optional[Callable] = None,
        on_restart: Optional[Callable] = None,
        target_files: Optional[list] = None,
    ) -> LoopState:
        """Run.

        Args:
            vm: Description.
            rag: Description.
            log_fn: Description.
            on_done: Description.
            on_restart: Description.
            target_files: Description.
        """
        if self._running:
            log_fn("[yellow]⚠ Déjà en cours.[/]")
            return self.state

        self._running = True
        self.state = LoopState(memory=ErrorMemory.load())

        # ── Multi-fichiers : itérer sur chaque cible ──────────────────────
        if target_files and len(target_files) > 1:
            return await self._run_multi(vm, rag, log_fn, on_done, on_restart, target_files)

        # ── Mono-fichier (comportement original) ─────────────────────────
        return await self._run_single(vm, rag, log_fn, on_done, on_restart)

    async def _run_multi(
        self, vm: object, rag: object, log_fn: object, on_done: object, on_restart: object, target_files: object
    ) -> LoopState:
        """Exécute le loop séquentiellement sur chaque fichier cible."""
        from pathlib import Path

        log_fn("\n[bold #58a6ff]╔═════════════════════════════════════════════╗[/]")
        log_fn("[bold #58a6ff]║  🔄 AMÉLIORATION MULTI-FICHIERS             ║[/]")
        log_fn("[bold #58a6ff]╚═════════════════════════════════════════════╝[/]")
        log_fn(f"  Fichiers : {', '.join(f.name if hasattr(f, 'name') else str(f) for f in target_files)}")

        combined_state = self.state

        for idx, target in enumerate(target_files, 1):
            target_path = Path(target) if not isinstance(target, Path) else target
            if not target_path.exists():
                log_fn(f"  [yellow]⚠ {target_path.name} introuvable — ignoré[/]")
                continue

            log_fn(f"\n[bold #d2a8ff]━━━ Fichier {idx}/{len(target_files)} : {target_path.name} ━━━[/]")

            # Si c'est le fichier principal → utiliser le vm existant
            if target_path == vm.work_path or target_path == vm.source_path:
                file_state = await self._run_single_inner(vm, rag, log_fn, on_restart)
            else:
                # Pour les modules auxiliaires → lire, corriger, réécrire
                file_state = await self._run_auxiliary_file(target_path, rag, log_fn)

            # Fusionner les compteurs
            combined_state.loop1_iterations += file_state.loop1_iterations
            combined_state.loop2_iterations += file_state.loop2_iterations
            combined_state.loop3_iterations += file_state.loop3_iterations
            combined_state.total_failures += file_state.total_failures
            combined_state.iterations.extend(file_state.iterations)

        self._running = False
        if on_done:
            try:
                if asyncio.iscoroutinefunction(on_done):
                    await on_done(combined_state)
                else:
                    on_done(combined_state)
            except Exception:
                pass

        return combined_state

    async def _run_auxiliary_file(self, file_path: object, rag: object, log_fn: object) -> LoopState:
        """
        Améliore un fichier auxiliaire (forge_*.py) sans VersionManager.
        Lit → audit → corrige → valide syntaxe → écrit.
        """
        import shutil

        state = LoopState(memory=self.state.memory)

        try:
            code = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            log_fn(f"  [red]❌ Lecture impossible : {e}[/]")
            return state

        initial_errors = count_real_errors(code)
        log_fn(f"  Erreurs initiales : {initial_errors}")

        if initial_errors == 0:
            log_fn(f"  [green]✅ {file_path.name} déjà propre.[/]")
            return state

        # Un seul passage B1 simplifié pour les modules auxiliaires
        assignments = await self.orc.assign_roles(1, True, log_fn)
        debugger = assignments.get(AgentRole.DEBUGGER)
        if not debugger:
            log_fn("  [red]❌ Aucun modèle DEBUGGER disponible.[/]")
            return state

        for i in range(1, 4):  # max 3 itérations par fichier auxiliaire
            state.loop1_iterations += 1
            code = file_path.read_text(encoding="utf-8", errors="replace")
            errors_now = count_real_errors(code)

            if errors_now == 0:
                log_fn(f"  [green]✅ {file_path.name} propre après {i - 1} corrections.[/]")
                return state

            prompt = (
                f"Corrige le bug le plus critique dans ce module Python.\n"
                f"Retourne le fichier COMPLET corrigé dans ```python.\n\n"
                f"```python\n{code[:8000]}\n```"
            )

            try:
                reply = await _call_model(
                    debugger,
                    prompt,
                    self.loop1.ollama_url,
                    system_prompt=ROLE_SYSTEM_PROMPTS.get(AgentRole.DEBUGGER, ""),
                )
            except Exception as e:
                log_fn(f"  [red]❌ LLM : {e}[/]")
                state.total_failures += 1
                continue

            suggestions = AuditParser.extract_suggestions(reply) if reply else []
            if not suggestions:
                log_fn("  [yellow]⚠ Aucune suggestion parsable.[/]")
                state.total_failures += 1
                continue

            new_code = suggestions[0]["code"]
            if not suggestions[0]["syntax_ok"]:
                log_fn("  [red]✗ Syntaxe invalide.[/]")
                state.total_failures += 1
                continue

            # Backup + écriture
            _bak = file_path.with_suffix(".py.bak")
            try:
                shutil.copy2(str(file_path), str(_bak))
                file_path.write_text(new_code, encoding="utf-8")
                errors_new = count_real_errors(new_code)
                if errors_new < errors_now:
                    log_fn(f"  [green]✅ {file_path.name} : {errors_now}→{errors_new} erreurs[/]")
                else:
                    # Rollback
                    shutil.copy2(str(_bak), str(file_path))
                    log_fn("  [yellow]⚠ Pas d'amélioration → rollback[/]")
                    state.total_failures += 1
            except Exception as e:
                log_fn(f"  [red]❌ Écriture : {e}[/]")
                try:
                    shutil.copy2(str(_bak), str(file_path))
                except Exception:
                    pass
                state.total_failures += 1

        return state

    async def _run_single(
        self, vm: object, rag: object, log_fn: object, on_done: object, on_restart: object
    ) -> LoopState:
        """Exécution mono-fichier originale (B1 → B2 → B3)."""
        state = await self._run_single_inner(vm, rag, log_fn, on_restart)

        # Rapport final
        initial_version = vm.current_version
        s = state
        mem = s.memory
        total = s.loop1_iterations + s.loop2_iterations + s.loop3_iterations
        final_errors = count_real_errors(vm.get_current_code())

        log_fn(
            f"\n[bold]━━━ Rapport final ━━━[/]\n"
            f"  Itérations : {total} (B1:{s.loop1_iterations} "
            f"B2:{s.loop2_iterations} B3:{s.loop3_iterations})\n"
            f"  Versions testées : {len(mem.version_history)}\n"
            f"  Succès : {len(mem.successful_fixes)}  "
            f"Échecs : {len(mem.failed_approaches)}\n"
            f"  Mémoire persistée : {MEMORY_FILE}"
        )

        self._running = False
        if on_done:
            try:
                if asyncio.iscoroutinefunction(on_done):
                    await on_done(state)
                else:
                    on_done(state)
            except Exception:
                pass
        return state

    async def _run_single_inner(self, vm: object, rag: object, log_fn: object, on_restart: object) -> LoopState:
        """Logique B1 → B2 → B3 sur un seul fichier."""
        initial_version = vm.current_version
        initial_errors = count_real_errors(vm.get_current_code())
        self.state.memory.record_version(initial_version, initial_errors, 0.0, "départ", "init")

        log_fn("\n[bold #58a6ff]╔═════════════════════════════════════════════╗[/]")
        log_fn("[bold #58a6ff]║  🔄 AMÉLIORATION AUTONOME AUTO-APPRENANTE   ║[/]")
        log_fn("[bold #58a6ff]╚═════════════════════════════════════════════╝[/]")
        log_fn(f"  Version départ    : v{initial_version}")
        log_fn(f"  Erreurs initiales : {initial_errors}")
        log_fn(f"  Mémoire chargée   : {len(self.state.memory.version_history)} versions connues")

        models = await self.orc.discover_models()
        log_fn(f"  Modèles : {', '.join(models[:6])}{'…' if len(models) > 6 else ''}")

        async def on_patch(code: object, desc: object, major: object = False) -> object:
            """On patch.

            Args:
                code: Description.
                desc: Description.
                major: Description.
            """
            return await vm.prepare_patch(code, desc, major=major)

        try:
            ok1, self.state = await self.loop1.run(vm, rag, self.state, log_fn, on_patch, on_restart)
            if ok1:
                log_fn("\n[bold green]🎉 Succès en Boucle 1 ![/]")
            else:
                log_fn(
                    f"\n[yellow]⟳ B1 insuffisante ({len(self.state.memory.failed_approaches)} échecs connus) → B2[/]"
                )
                ok2, self.state = await self.loop2.run(vm, rag, self.state, log_fn, on_patch, on_restart)
                if ok2:
                    log_fn("\n[cyan]⟳ B2 réussie → relance B1[/]")
                    ok1b, self.state = await self.loop1.run(vm, rag, self.state, log_fn, on_patch, on_restart)
                    if not ok1b:
                        log_fn("[yellow]⚠ B1 relancée insuffisante → B3[/]")
                        await self.loop3.run(vm, rag, self.state, log_fn, on_patch, on_restart)
                else:
                    log_fn("\n[red]⟳ B1+B2 insuffisantes → B3 (débat)[/]")
                    await self.loop3.run(vm, rag, self.state, log_fn, on_patch, on_restart)
        except asyncio.CancelledError:
            log_fn("\n[yellow]⚠ Interrompu.[/]")
        except Exception as e:
            log_fn(f"\n[red]❌ Erreur : {e}[/]")
            logger.exception("ImprovementOrchestrator.run")

        return self.state

    def stop(self) -> None:
        """Stop."""
        self._running = False

    @property
    def is_running(self) -> bool:
        """Is running."""
        return self._running


__all__ = [
    # Sécurité
    "DangerGuard",
    "DangerLevel",
    "DangerCheck",
    "danger_confirmation_message",
    "should_auto_block",
    "get_guard",
    # Sandbox
    "CodeSandbox",
    "SandboxResult",
    "get_sandbox",
    "handle_code_command",
    "is_dangerous_code",
    # Auto-amélioration
    "BaseLoop",
    "ImprovementOrchestrator",
    "ErrorMemory",
    "validate_python_syntax",
    "count_real_errors",
]

"""
danger_guard.py — Protection contre les commandes SSH dangereuses
=================================================================
OctoDevOps v5

Ce module intercepte les commandes avant exécution et :
  1. Détecte les commandes à risque (destruction, escalade, réseau…)
  2. Classe le niveau de danger : INFO / WARNING / CRITICAL / FATAL
  3. Explique le risque en langage naturel
  4. Expose une API simple pour demander confirmation à l'utilisateur

Usage dans Nokido.py :
    from danger_guard import DangerGuard, DangerLevel, DangerCheck

    guard  = DangerGuard()
    check  = guard.check("rm -rf /var/lib/docker")
    if check.level >= DangerLevel.WARNING:
        # Afficher le widget de confirmation Textual
        await ask_confirmation(check)
    else:
        await execute(cmd)
"""

import re
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional, Tuple


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
        return self.level == DangerLevel.SAFE

    @property
    def icon(self) -> str:
        return LEVEL_LABELS[self.level][0]

    @property
    def color(self) -> str:
        return LEVEL_LABELS[self.level][1]

    @property
    def label(self) -> str:
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

    def __init__(self, custom_rules: Optional[List[Tuple]] = None):
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
    global _guard_instance
    if _guard_instance is None:
        _guard_instance = DangerGuard()
    return _guard_instance

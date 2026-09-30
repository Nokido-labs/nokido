"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_agent_roles
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
forge_agents.py — Intelligence et routage des agents pour La Forge
===================================================================
Fusion de : roles.py · scoring.py · routage.py

Organisation :
  § 1 RÔLES        : AgentRole, system prompts, IntentRouter, RoleOrchestrator
  § 2 SCORING      : ArchitectureProfile, ModelScorer, benchmark dynamique
  § 3 ROUTAGE      : SmartRouter, PromptClassifier, AgentPlanner, OllamaParallelRunner

Les trois modules sont regroupés car ils forment un pipeline cohérent :
  AgentRole → ModelScorer (qui modèle pour ce rôle ?) → SmartRouter (exécution)

Usage dans Nokido.py :
    from forge_agents import (
        AgentRole, RoleOrchestrator, IntentRouter,
        ROLE_META, ROLE_SYSTEM_PROMPTS,
        ModelScorer, ArchitectureProfile,
        SmartRouter, OllamaParallelRunner, PromptClassifier,
        AgentPlanner, PromptCategory, RouteResult,
        init_router, get_router,
    )
"""


import logging
from enum import Enum
from typing import Dict, List, Set

from app.core.settings import get_settings as _forge_settings  # noqa: F401


class _SettingsProxy:
    def __getattr__(self, k) -> object:
        """Getattr.

        Args:
            k: Description.
        """
        s = _forge_settings()
        return getattr(s, k, None) if s else None


settings = _SettingsProxy()


def _forge_run_ssh(*a, **kw) -> object:
    """Forge run ssh."""
    import sys as _s

    m = _s.modules.get("__main__")
    fn = getattr(m, "run_ssh", None)
    if fn:
        return fn(*a, **kw)
    raise RuntimeError("run_ssh non disponible")


run_ssh = _forge_run_ssh


logger = logging.getLogger(__name__)


# =============================================================================
# § 1 — RÔLES ET ORCHESTRATION  (ex-roles.py)
# =============================================================================

# =============================================================================
# ÉNUMÉRATION DES RÔLES
# =============================================================================


class AgentRole(Enum):
    # ── Amélioration de code (loops.py) ─────────────────────────────────────
    ANALYSTE = "analyste"
    DEBUGGER = "debugger"
    COMPARATEUR = "comparateur"
    STRATEGE = "stratege"
    JUGE = "juge"

    # ── DevOps core ──────────────────────────────────────────────────────────
    PLANNER = "planner"
    DISCOVERY = "discovery"
    DEVOPS = "devops"
    NETWORK = "network"
    SECURITY = "security"
    LOG_ANALYSIS = "log_analysis"
    RAG_KNOWLEDGE = "rag_knowledge"
    ACTION_EXEC = "action_exec"
    MEMORY = "memory"

    # ── Optionnels ────────────────────────────────────────────────────────────
    MONITORING = "monitoring"
    PATCH_MGMT = "patch_mgmt"
    COMPLIANCE = "compliance"
    INCIDENT = "incident"
    CONFIG_BACKUP = "config_backup"
    THREAT_INTEL = "threat_intel"

    # ── Infrastructure ────────────────────────────────────────────────────────
    ACTIVE_DIR = "active_dir"
    WINDOWS_MGMT = "windows_mgmt"
    LINUX_MGMT = "linux_mgmt"
    NETWORK_DEVICE = "network_device"
    DNS_PIHOLE = "dns_pihole"
    IDS_ZEEK = "ids_zeek"


# Groupe des rôles "code" — utilisés par loops.py
CODE_ROLES: Set[AgentRole] = {
    AgentRole.ANALYSTE,
    AgentRole.DEBUGGER,
    AgentRole.COMPARATEUR,
    AgentRole.STRATEGE,
    AgentRole.JUGE,
}

# Groupe des rôles "ops" — utilisés par le dispatcher DevOps
OPS_ROLES: Set[AgentRole] = {
    AgentRole.PLANNER,
    AgentRole.DISCOVERY,
    AgentRole.DEVOPS,
    AgentRole.NETWORK,
    AgentRole.SECURITY,
    AgentRole.LOG_ANALYSIS,
    AgentRole.RAG_KNOWLEDGE,
    AgentRole.ACTION_EXEC,
    AgentRole.MEMORY,
}

# Rôles optionnels
OPT_ROLES: Set[AgentRole] = {
    AgentRole.MONITORING,
    AgentRole.PATCH_MGMT,
    AgentRole.COMPLIANCE,
    AgentRole.INCIDENT,
    AgentRole.CONFIG_BACKUP,
    AgentRole.THREAT_INTEL,
}

# Rôles infra spécifiques
INFRA_ROLES: Set[AgentRole] = {
    AgentRole.ACTIVE_DIR,
    AgentRole.WINDOWS_MGMT,
    AgentRole.LINUX_MGMT,
    AgentRole.NETWORK_DEVICE,
    AgentRole.DNS_PIHOLE,
    AgentRole.IDS_ZEEK,
}


# =============================================================================
# METADATA RÔLES — icônes, couleurs, descriptions
# =============================================================================

ROLE_META: Dict[AgentRole, Dict] = {
    AgentRole.ANALYSTE: {"icon": "🔍", "color": "#58a6ff", "label": "Analyste Code"},
    AgentRole.DEBUGGER: {"icon": "🐛", "color": "#f0883e", "label": "Debugger"},
    AgentRole.COMPARATEUR: {"icon": "⚖️", "color": "#79c0ff", "label": "Comparateur"},
    AgentRole.STRATEGE: {"icon": "🏗️", "color": "#ffa657", "label": "Stratège"},
    AgentRole.JUGE: {"icon": "⚖️", "color": "#d2a8ff", "label": "Juge"},
    AgentRole.PLANNER: {"icon": "📋", "color": "#58a6ff", "label": "Planner"},
    AgentRole.DISCOVERY: {"icon": "🗺️", "color": "#3fb950", "label": "Discovery"},
    AgentRole.DEVOPS: {"icon": "⚙️", "color": "#f0883e", "label": "DevOps"},
    AgentRole.NETWORK: {"icon": "🌐", "color": "#79c0ff", "label": "Network"},
    AgentRole.SECURITY: {"icon": "🔐", "color": "#ff7b72", "label": "Security"},
    AgentRole.LOG_ANALYSIS: {"icon": "📊", "color": "#ffa657", "label": "Log Analysis"},
    AgentRole.RAG_KNOWLEDGE: {"icon": "🗄️", "color": "#56d364", "label": "RAG/Knowledge"},
    AgentRole.ACTION_EXEC: {"icon": "⚡", "color": "#f0883e", "label": "Action/Exec"},
    AgentRole.MEMORY: {"icon": "🧠", "color": "#d2a8ff", "label": "Memory"},
    AgentRole.MONITORING: {"icon": "📈", "color": "#3fb950", "label": "Monitoring"},
    AgentRole.PATCH_MGMT: {"icon": "🩹", "color": "#ffa657", "label": "Patch Mgmt"},
    AgentRole.COMPLIANCE: {"icon": "✅", "color": "#56d364", "label": "Compliance"},
    AgentRole.INCIDENT: {"icon": "🚨", "color": "#ff7b72", "label": "Incident"},
    AgentRole.CONFIG_BACKUP: {"icon": "💾", "color": "#79c0ff", "label": "Config Backup"},
    AgentRole.THREAT_INTEL: {"icon": "🕵️", "color": "#ff7b72", "label": "Threat Intel"},
    AgentRole.ACTIVE_DIR: {"icon": "🏢", "color": "#58a6ff", "label": "Active Directory"},
    AgentRole.WINDOWS_MGMT: {"icon": "🪟", "color": "#79c0ff", "label": "Windows Mgmt"},
    AgentRole.LINUX_MGMT: {"icon": "🐧", "color": "#3fb950", "label": "Linux Mgmt"},
    AgentRole.NETWORK_DEVICE: {"icon": "🔌", "color": "#ffa657", "label": "Network Device"},
    AgentRole.DNS_PIHOLE: {"icon": "🌍", "color": "#56d364", "label": "DNS/Pi-hole"},
    AgentRole.IDS_ZEEK: {"icon": "🛡️", "color": "#ff7b72", "label": "IDS/Zeek"},
}


# =============================================================================
# SYSTEM PROMPTS PAR RÔLE
# =============================================================================

ROLE_SYSTEM_PROMPTS: Dict[AgentRole, str] = {
    # ── Code ──────────────────────────────────────────────────────────────────
    AgentRole.ANALYSTE: (
        "Tu es un ANALYSTE expert Python. Ton rôle :\n"
        "  • Comprendre la structure globale du code\n"
        "  • Identifier les patterns problématiques\n"
        "  • Repérer les risques architecturaux\n"
        "  • Détecter les dépendances circulaires, couplages forts\n"
        "Format :\n"
        "  PROBLÈME : description\n"
        "  IMPACT    : conséquences\n"
        "  RACINE    : cause profonde\n"
    ),
    AgentRole.DEBUGGER: (
        "Tu es un DEBUGGER expert Python/DevOps. Ton rôle :\n"
        "  • Localiser précisément les bugs (syntaxe, logique, async, exceptions)\n"
        "  • Corriger de façon chirurgicale — ne pas réécrire ce qui fonctionne\n"
        "  • Retourner le code corrigé complet dans un bloc ```python\n"
        "  • Ajouter des commentaires inline sur chaque correction\n"
        "Format : Suggestion N : Titre\n"
        "```python\n"
        "... code corrigé complet ...\n"
        "```\n"
    ),
    AgentRole.COMPARATEUR: (
        "Tu es un COMPARATEUR expert en revue de code. Ton rôle :\n"
        "  • Évaluer objectivement deux versions d'un code\n"
        "  • Juger : qualité, robustesse, maintenabilité, performance\n"
        "  • Voter pour la meilleure version\n"
        "  • Donner un score de confiance [0-100]\n"
        "Format :\n"
        "  ANALYSE   : points forts/faibles de chaque version\n"
        "  VERDICT   : version A ou B\n"
        "  SCORE     : [0-100]\n"
        "  RAISON    : justification en 2 phrases\n"
    ),
    AgentRole.STRATEGE: (
        "Tu es un STRATÈGE expert en architecture logicielle. Ton rôle :\n"
        "  • Proposer des améliorations profondes (pas cosmétiques)\n"
        "  • Appliquer les patterns : SOLID, DRY, composition > héritage\n"
        "  • Planifier les migrations progressives\n"
        "  • Anticiper les problèmes de scalabilité\n"
        "Format :\n"
        "  VISION   : objectif architectural\n"
        "  ÉTAPES   : plan en 3-5 étapes\n"
        "  RISQUES  : points d'attention\n"
        "  CODE     : implémentation dans un bloc ```python\n"
    ),
    AgentRole.JUGE: (
        "Tu es le JUGE arbitre final. Ton rôle :\n"
        "  • Synthétiser les opinions de tous les agents\n"
        "  • Pondérer les arguments selon leur pertinence\n"
        "  • Rendre un verdict final décisif et motivé\n"
        "  • Combiner le meilleur de chaque proposition\n"
        "Format :\n"
        "  SYNTHÈSE     : résumé des positions\n"
        "  PONDÉRATION  : poids donné à chaque agent\n"
        "  VERDICT      : décision finale\n"
        "  CODE_FINAL   : code dans un bloc ```python\n"
    ),
    # ── DevOps core ───────────────────────────────────────────────────────────
    AgentRole.PLANNER: (
        "Tu es un PLANNER expert en orchestration DevOps. Ton rôle :\n"
        "  • Décomposer les demandes complexes en étapes atomiques\n"
        "  • Identifier les dépendances entre tâches\n"
        "  • Planifier les risques et rollbacks\n"
        "  • Déléguer aux agents spécialisés appropriés\n"
        "Format :\n"
        "  ANALYSE    : compréhension de la demande\n"
        "  PLAN       : liste ordonnée d'étapes\n"
        "  AGENTS     : agents à invoquer (DISCOVERY, DEVOPS, SECURITY, etc.)\n"
        "  ROLLBACK   : procédure d'annulation si échec\n"
    ),
    AgentRole.DISCOVERY: (
        "Tu es un DISCOVERY AGENT expert en inventaire système. Ton rôle :\n"
        "  • Cartographier l'infrastructure (hôtes, services, ports)\n"
        "  • Identifier les versions logicielles installées\n"
        "  • Lister les services actifs et leur état\n"
        "  • Détecter les composants non documentés\n"
        "Commandes préférées : nmap, netstat, ss, ps, systemctl, dpkg/rpm\n"
        "Format :\n"
        "  INVENTAIRE : liste des composants découverts\n"
        "  SERVICES   : état de chaque service\n"
        "  ANOMALIES  : éléments inattendus détectés\n"
    ),
    AgentRole.DEVOPS: (
        "Tu es un DEVOPS AGENT expert en CI/CD et déploiements. Ton rôle :\n"
        "  • Gérer les pipelines (git, Docker, Kubernetes, Ansible)\n"
        "  • Automatiser les déploiements et rollbacks\n"
        "  • Configurer les environnements (dev/staging/prod)\n"
        "  • Gérer les secrets et variables d'environnement\n"
        "Format :\n"
        "  ACTION   : commande ou pipeline à exécuter\n"
        "  RISQUES  : impacts potentiels\n"
        "  ROLLBACK : procédure d'annulation\n"
    ),
    AgentRole.NETWORK: (
        "Tu es un NETWORK AGENT expert en réseaux TCP/IP. Ton rôle :\n"
        "  • Diagnostiquer la connectivité et le routage\n"
        "  • Analyser le trafic réseau (tcpdump, wireshark)\n"
        "  • Configurer les firewalls (iptables, nftables, ufw)\n"
        "  • Gérer les VLANs, VPN, et tunnels\n"
        "Format :\n"
        "  DIAGNOSTIC : état actuel du réseau\n"
        "  PROBLÈME   : origine identifiée\n"
        "  SOLUTION   : commandes correctives\n"
    ),
    AgentRole.SECURITY: (
        "Tu es un SECURITY AGENT expert en cybersécurité. Ton rôle :\n"
        "  • Identifier les vulnérabilités (CVE, mauvaises configs)\n"
        "  • Durcir les systèmes (CIS Benchmarks, STIG)\n"
        "  • Analyser les comportements suspects\n"
        "  • Recommander des contre-mesures\n"
        "Format :\n"
        "  VULNÉRABILITÉS : liste avec criticité (CVSS)\n"
        "  REMÉDIATION    : actions correctives prioritaires\n"
        "  VALIDATION     : commandes de vérification\n"
    ),
    AgentRole.LOG_ANALYSIS: (
        "Tu es un LOG ANALYSIS AGENT expert en analyse de journaux. Ton rôle :\n"
        "  • Parser et corréler les logs système, applicatifs, sécurité\n"
        "  • Identifier les patterns d'erreur et anomalies\n"
        "  • Détecter les séquences d'événements suspects\n"
        "  • Extraire les métriques clés\n"
        "Format :\n"
        "  ÉVÉNEMENTS_CLÉS : liste triée par criticité\n"
        "  PATTERNS        : tendances identifiées\n"
        "  RECOMMANDATIONS : actions à entreprendre\n"
    ),
    AgentRole.RAG_KNOWLEDGE: (
        "Tu es un RAG/KNOWLEDGE AGENT expert en gestion documentaire. Ton rôle :\n"
        "  • Rechercher dans la base de connaissances\n"
        "  • Synthétiser l'information pertinente\n"
        "  • Enrichir la base avec les nouvelles connaissances\n"
        "  • Référencer les sources et procédures\n"
        "Format :\n"
        "  SOURCES    : documents pertinents trouvés\n"
        "  SYNTHÈSE   : information consolidée\n"
        "  LACUNES    : informations manquantes identifiées\n"
    ),
    AgentRole.ACTION_EXEC: (
        "Tu es un ACTION/EXECUTION AGENT expert en exécution de tâches. Ton rôle :\n"
        "  • Exécuter les commandes planifiées par le Planner\n"
        "  • Vérifier les prérequis avant toute action destructive\n"
        "  • Rapporter les résultats et erreurs\n"
        "  • Gérer les dépendances d'exécution\n"
        "Format :\n"
        "  PRÉREQUIS  : vérifications avant exécution\n"
        "  COMMANDE   : instruction précise à exécuter\n"
        "  RÉSULTAT   : sortie attendue et traitement des erreurs\n"
    ),
    AgentRole.MEMORY: (
        "Tu es un MEMORY AGENT expert en gestion du contexte. Ton rôle :\n"
        "  • Maintenir l'historique des actions et décisions\n"
        "  • Identifier les patterns récurrents et leçons apprises\n"
        "  • Enrichir le RAG avec les nouvelles connaissances\n"
        "  • Prévenir la répétition des erreurs passées\n"
        "Format :\n"
        "  CONTEXTE    : historique pertinent\n"
        "  PATTERNS    : tendances observées\n"
        "  LEÇONS      : enseignements à retenir\n"
    ),
    # ── Optionnels ────────────────────────────────────────────────────────────
    AgentRole.MONITORING: (
        "Tu es un MONITORING AGENT expert en observabilité. Ton rôle :\n"
        "  • Analyser métriques CPU/RAM/disque/réseau\n"
        "  • Identifier seuils d'alerte et dégradations\n"
        "  • Corréler métriques et incidents\n"
        "  • Recommander capacités et optimisations\n"
    ),
    AgentRole.PATCH_MGMT: (
        "Tu es un PATCH MANAGEMENT AGENT. Ton rôle :\n"
        "  • Inventorier les paquets et versions installés\n"
        "  • Identifier les CVE applicables\n"
        "  • Planifier les fenêtres de maintenance\n"
        "  • Valider les patchs après application\n"
    ),
    AgentRole.COMPLIANCE: (
        "Tu es un COMPLIANCE/AUDIT AGENT expert en conformité. Ton rôle :\n"
        "  • Vérifier la conformité CIS/NIST/ISO27001\n"
        "  • Générer des rapports d'audit\n"
        "  • Identifier les écarts et non-conformités\n"
        "  • Proposer des plans de remédiation\n"
    ),
    AgentRole.INCIDENT: (
        "Tu es un INCIDENT RESPONSE AGENT. Ton rôle :\n"
        "  • Trier et classifier les incidents (P1-P4)\n"
        "  • Coordonner la réponse multi-équipes\n"
        "  • Isoler les systèmes compromis si nécessaire\n"
        "  • Documenter la timeline et post-mortem\n"
    ),
    AgentRole.CONFIG_BACKUP: (
        "Tu es un CONFIG BACKUP AGENT. Ton rôle :\n"
        "  • Sauvegarder les configurations critiques\n"
        "  • Versionner les changements de configuration\n"
        "  • Restaurer depuis une sauvegarde propre\n"
        "  • Valider l'intégrité des sauvegardes\n"
    ),
    AgentRole.THREAT_INTEL: (
        "Tu es un THREAT INTELLIGENCE AGENT. Ton rôle :\n"
        "  • Identifier les IOC (IPs, hashes, domaines malveillants)\n"
        "  • Corréler avec les bases de menaces connues\n"
        "  • Évaluer l'exposition aux menaces actuelles\n"
        "  • Proposer des contre-mesures proactives\n"
    ),
    # ── Infrastructure ────────────────────────────────────────────────────────
    AgentRole.ACTIVE_DIR: (
        "Tu es un ACTIVE DIRECTORY AGENT expert AD/LDAP. Ton rôle :\n"
        "  • Gérer utilisateurs, groupes, OUs, GPO\n"
        "  • Diagnostiquer réplication et authentification Kerberos\n"
        "  • Auditer les permissions et délégations\n"
        "  • Détecter les comptes suspects ou escalades de privilèges\n"
    ),
    AgentRole.WINDOWS_MGMT: (
        "Tu es un WINDOWS MANAGEMENT AGENT. Ton rôle :\n"
        "  • Administration via PowerShell et WinRM\n"
        "  • Gestion des services Windows et registre\n"
        "  • Déploiement et configuration d'applications\n"
        "  • Gestion des événements Windows (Event Viewer)\n"
    ),
    AgentRole.LINUX_MGMT: (
        "Tu es un LINUX MANAGEMENT AGENT. Ton rôle :\n"
        "  • Administration via SSH, systemd, cron\n"
        "  • Gestion des paquets (apt/yum/dnf)\n"
        "  • Configuration kernel, SELinux/AppArmor\n"
        "  • Gestion des utilisateurs, permissions, ACL\n"
    ),
    AgentRole.NETWORK_DEVICE: (
        "Tu es un NETWORK DEVICE AGENT expert équipements réseau. Ton rôle :\n"
        "  • Configurer switches (VLANs, STP, LACP)\n"
        "  • Gérer routeurs (OSPF, BGP, routes statiques)\n"
        "  • Diagnostiquer les pannes de liaison\n"
        "  • Auditer les ACL et politiques de sécurité réseau\n"
    ),
    AgentRole.DNS_PIHOLE: (
        "Tu es un DNS/PI-HOLE AGENT. Ton rôle :\n"
        "  • Gérer les zones DNS et enregistrements\n"
        "  • Configurer Pi-hole (blocklists, whitelist, DNS-over-HTTPS)\n"
        "  • Diagnostiquer les résolutions DNS défaillantes\n"
        "  • Analyser les requêtes DNS suspectes\n"
    ),
    AgentRole.IDS_ZEEK: (
        "Tu es un IDS/ZEEK AGENT expert en détection d'intrusion. Ton rôle :\n"
        "  • Analyser les logs Zeek (conn, dns, http, ssl, files)\n"
        "  • Identifier les signatures d'attaque connues\n"
        "  • Corréler les événements réseau suspects\n"
        "  • Générer des alertes et recommandations de blocage\n"
    ),
}


# =============================================================================
# REQUÊTES RAG PAR RÔLE
# =============================================================================

ROLE_RAG_QUERIES: Dict[AgentRole, str] = {
    AgentRole.ANALYSTE: "patterns architecturaux problèmes structure Python coupling",
    AgentRole.DEBUGGER: "bugs erreurs corrections exceptions Python async await",
    AgentRole.COMPARATEUR: "comparaison versions diff qualité code métriques refactoring",
    AgentRole.STRATEGE: "architecture refactoring design patterns SOLID migration",
    AgentRole.JUGE: "décision vote consensus arbitrage qualité code verdict",
    AgentRole.PLANNER: "planification tâches orchestration dépendances DevOps",
    AgentRole.DISCOVERY: "inventaire hôtes services ports scan réseau infrastructure",
    AgentRole.DEVOPS: "CI/CD déploiement Docker Kubernetes Ansible pipeline git",
    AgentRole.NETWORK: "réseau routage firewall VPN VLAN trafic diagnostic",
    AgentRole.SECURITY: "sécurité CVE vulnérabilité durcissement audit pentest",
    AgentRole.LOG_ANALYSIS: "logs journaux analyse erreurs événements corrélation",
    AgentRole.RAG_KNOWLEDGE: "documentation procédures runbook base connaissances",
    AgentRole.ACTION_EXEC: "exécution commandes scripts automation tâches",
    AgentRole.MEMORY: "historique contexte mémoire décisions passées patterns",
    AgentRole.MONITORING: "métriques CPU RAM disque réseau alertes SLA performance",
    AgentRole.PATCH_MGMT: "patchs mises à jour CVE maintenance correctifs",
    AgentRole.COMPLIANCE: "conformité CIS NIST ISO27001 audit réglementaire",
    AgentRole.INCIDENT: "incident réponse triage post-mortem escalade",
    AgentRole.CONFIG_BACKUP: "sauvegarde configuration restauration versioning",
    AgentRole.THREAT_INTEL: "menaces IOC malware threat intelligence TTPs",
    AgentRole.ACTIVE_DIR: "Active Directory LDAP Kerberos GPO utilisateurs groupes",
    AgentRole.WINDOWS_MGMT: "Windows PowerShell WinRM services registre événements",
    AgentRole.LINUX_MGMT: "Linux systemd apt yum permissions SELinux cron",
    AgentRole.NETWORK_DEVICE: "switch routeur VLAN STP BGP OSPF ACL équipements",
    AgentRole.DNS_PIHOLE: "DNS zone enregistrement Pi-hole résolution filtrage",
    AgentRole.IDS_ZEEK: "IDS Zeek intrusion détection logs réseau alertes",
}


# =============================================================================
# MOTS-CLÉS DE ROUTAGE — détection automatique du rôle depuis l'input
# =============================================================================

ROLE_KEYWORDS: Dict[AgentRole, List[str]] = {
    AgentRole.PLANNER: ["planifie", "plan", "étapes", "décompose", "stratégie", "comment faire", "que faut-il"],
    AgentRole.DISCOVERY: [
        "inventaire",
        "cartographie",
        "quels services",
        "quels ports",
        "scan",
        "quels hôtes",
        "liste les machines",
        "nmap",
    ],
    AgentRole.DEVOPS: [
        "déploie",
        "pipeline",
        "ci/cd",
        "docker",
        "kubernetes",
        "kubectl",
        "helm",
        "ansible",
        "terraform",
        "git push",
        "build",
        "release",
        "rollback",
        "artifact",
    ],
    AgentRole.NETWORK: [
        "réseau",
        "routage",
        "firewall",
        "iptables",
        "nftables",
        "vlan",
        "vpn",
        "tunnel",
        "latence",
        "ping",
        "traceroute",
        "interface",
        "ip route",
        "netstat",
        "ss -",
    ],
    AgentRole.SECURITY: [
        "sécurité",
        "vulnérabilité",
        "cve",
        "durcissement",
        "pentest",
        "exploit",
        "compromis",
        "attaque",
        "intrusion",
        "fail2ban",
        "selinux",
        "apparmor",
        "audit",
    ],
    AgentRole.LOG_ANALYSIS: [
        "logs",
        "journaux",
        "analyse log",
        "grep log",
        "journalctl",
        "syslog",
        "événements",
        "erreurs log",
        "tail -f",
        "log analysis",
    ],
    AgentRole.RAG_KNOWLEDGE: [
        "documentation",
        "doc",
        "manuel",
        "procédure",
        "runbook",
        "comment",
        "qu'est-ce que",
        "explique",
        "définition",
        "tutoriel",
        "guide",
        "aide",
    ],
    AgentRole.ACTION_EXEC: ["exécute", "lance", "run", "applique", "effectue", "démarre", "arrête", "redémarre"],
    AgentRole.MEMORY: ["rappelle", "historique", "qu'avait-on fait", "précédent", "contexte", "souviens"],
    AgentRole.MONITORING: [
        "métriques",
        "cpu",
        "ram",
        "mémoire",
        "disque",
        "performances",
        "alerte",
        "seuil",
        "grafana",
        "prometheus",
    ],
    AgentRole.PATCH_MGMT: [
        "mise à jour",
        "update",
        "upgrade",
        "patch",
        "correctif",
        "apt upgrade",
        "yum update",
        "dnf update",
    ],
    AgentRole.COMPLIANCE: [
        "conformité",
        "cis",
        "nist",
        "iso27001",
        "audit",
        "réglementation",
        "benchmark",
        "hardening",
    ],
    AgentRole.INCIDENT: [
        "incident",
        "panne",
        "down",
        "urgence",
        "p1",
        "p2",
        "service en panne",
        "down detector",
        "triage",
    ],
    AgentRole.CONFIG_BACKUP: [
        "sauvegarde",
        "backup",
        "restaure",
        "restore",
        "configuration sauvegardée",
        "archiver config",
    ],
    AgentRole.THREAT_INTEL: ["menace", "threat", "ioc", "malware", "ransomware", "virus", "c2", "command and control"],
    AgentRole.ACTIVE_DIR: [
        "active directory",
        "ad",
        "ldap",
        "gpo",
        "kerberos",
        "domaine",
        "utilisateur ad",
        "groupe ad",
        "ou",
    ],
    AgentRole.WINDOWS_MGMT: [
        "windows",
        "powershell",
        "winrm",
        "event viewer",
        "services windows",
        "registre",
        "tâche planifiée",
    ],
    AgentRole.LINUX_MGMT: [
        "linux",
        "systemd",
        "systemctl",
        "apt",
        "yum",
        "crontab",
        "bash",
        "shell",
        "permission",
        "chmod",
    ],
    AgentRole.NETWORK_DEVICE: [
        "switch",
        "routeur",
        "vlan",
        "stp",
        "lacp",
        "bgp",
        "ospf",
        "cisco",
        "juniper",
        "mikrotik",
    ],
    AgentRole.DNS_PIHOLE: [
        "dns",
        "pihole",
        "pi-hole",
        "résolution dns",
        "zone dns",
        "enregistrement",
        "nslookup",
        "dig",
    ],
    AgentRole.IDS_ZEEK: ["zeek", "ids", "suricata", "snort", "détection", "signature", "alerte réseau", "pcap"],
}


# =============================================================================
# PROFILS STATIQUES DES MODÈLES
# Scores [0..10] par rôle + speed [1..10]
# Sources : HumanEval 2025, LiveCodeBench, MMLU-Pro, Aider Code Repair
# =============================================================================

MODEL_PROFILES: Dict[str, Dict] = {
    # ── Spécialistes code ─────────────────────────────────────────────────────
    "qwen2.5-coder:32b": {
        AgentRole.DEBUGGER: 9.8,
        AgentRole.COMPARATEUR: 9.2,
        AgentRole.ANALYSTE: 8.5,
        AgentRole.STRATEGE: 8.0,
        AgentRole.JUGE: 8.5,
        AgentRole.ACTION_EXEC: 8.0,
        AgentRole.DEVOPS: 7.5,
        AgentRole.LINUX_MGMT: 7.5,
        "speed": 5,
        "note": "SOTA HumanEval 92.7%, meilleur repair Aider",
    },
    "qwen2.5-coder:7b": {
        AgentRole.DEBUGGER: 9.2,
        AgentRole.COMPARATEUR: 8.5,
        AgentRole.ANALYSTE: 7.5,
        AgentRole.STRATEGE: 7.0,
        AgentRole.JUGE: 7.5,
        AgentRole.ACTION_EXEC: 7.5,
        AgentRole.DEVOPS: 7.0,
        "speed": 9,
        "note": "Rapide, bon rapport perf/vitesse",
    },
    "qwen2.5-coder": {
        AgentRole.DEBUGGER: 9.5,
        AgentRole.COMPARATEUR: 9.0,
        AgentRole.ANALYSTE: 8.0,
        AgentRole.STRATEGE: 7.5,
        AgentRole.JUGE: 8.0,
        AgentRole.ACTION_EXEC: 7.5,
        "speed": 8,
    },
    "deepseek-coder-v2": {
        AgentRole.DEBUGGER: 9.5,
        AgentRole.COMPARATEUR: 8.5,
        AgentRole.ANALYSTE: 7.5,
        AgentRole.STRATEGE: 7.0,
        AgentRole.JUGE: 7.0,
        AgentRole.DEVOPS: 7.0,
        "speed": 7,
        "note": "300 langages, 2T tokens",
    },
    "codestral": {
        AgentRole.DEBUGGER: 9.0,
        AgentRole.COMPARATEUR: 8.0,
        AgentRole.ANALYSTE: 7.0,
        AgentRole.STRATEGE: 6.5,
        AgentRole.JUGE: 7.0,
        AgentRole.DEVOPS: 7.0,
        "speed": 8,
        "note": "Mistral code, bon fill-in-the-middle",
    },
    # ── Raisonnement / Stratégie ──────────────────────────────────────────────
    "deepseek-r1": {
        AgentRole.ANALYSTE: 9.5,
        AgentRole.STRATEGE: 9.0,
        AgentRole.JUGE: 8.5,
        AgentRole.DEBUGGER: 7.5,
        AgentRole.COMPARATEUR: 7.0,
        AgentRole.PLANNER: 9.0,
        AgentRole.SECURITY: 8.0,
        AgentRole.COMPLIANCE: 8.0,
        "speed": 5,
        "note": "O1-level chain-of-thought, MMLU-Pro 90.8%",
    },
    "deepseek-r1:8b": {
        AgentRole.ANALYSTE: 8.5,
        AgentRole.STRATEGE: 8.0,
        AgentRole.JUGE: 7.5,
        AgentRole.DEBUGGER: 7.0,
        AgentRole.PLANNER: 8.0,
        AgentRole.SECURITY: 7.5,
        "speed": 8,
    },
    "phi4-reasoning": {
        AgentRole.ANALYSTE: 9.0,
        AgentRole.STRATEGE: 9.0,
        AgentRole.JUGE: 8.5,
        AgentRole.DEBUGGER: 7.5,
        AgentRole.COMPARATEUR: 7.5,
        AgentRole.PLANNER: 9.0,
        AgentRole.COMPLIANCE: 8.5,
        "speed": 6,
        "note": "Microsoft, fort raisonnement",
    },
    "phi4": {
        AgentRole.ANALYSTE: 8.5,
        AgentRole.STRATEGE: 8.0,
        AgentRole.JUGE: 8.0,
        AgentRole.DEBUGGER: 7.5,
        AgentRole.PLANNER: 8.0,
        "speed": 7,
    },
    # ── Hybrides polyvalents ──────────────────────────────────────────────────
    "qwen3": {
        AgentRole.STRATEGE: 9.5,
        AgentRole.JUGE: 9.0,
        AgentRole.ANALYSTE: 9.0,
        AgentRole.DEBUGGER: 8.0,
        AgentRole.COMPARATEUR: 8.5,
        AgentRole.PLANNER: 9.0,
        AgentRole.SECURITY: 8.5,
        AgentRole.LOG_ANALYSIS: 8.0,
        AgentRole.NETWORK: 7.5,
        AgentRole.DEVOPS: 8.0,
        "speed": 6,
        "note": "MoE hybride, thinking mode, excellent stratège",
    },
    "qwen3:8b": {
        AgentRole.STRATEGE: 8.5,
        AgentRole.JUGE: 8.5,
        AgentRole.ANALYSTE: 8.0,
        AgentRole.DEBUGGER: 7.5,
        AgentRole.PLANNER: 8.0,
        AgentRole.DEVOPS: 7.5,
        "speed": 9,
    },
    "cogito": {
        AgentRole.STRATEGE: 9.0,
        AgentRole.ANALYSTE: 8.5,
        AgentRole.JUGE: 8.5,
        AgentRole.DEBUGGER: 8.0,
        AgentRole.COMPARATEUR: 8.0,
        AgentRole.PLANNER: 8.5,
        AgentRole.SECURITY: 8.0,
        "speed": 7,
        "note": "Surpasse llama3.1 sur plusieurs benchmarks",
    },
    # ── Arbitrage / Jugement ──────────────────────────────────────────────────
    "llama3.3": {
        AgentRole.JUGE: 9.0,
        AgentRole.ANALYSTE: 8.5,
        AgentRole.STRATEGE: 8.5,
        AgentRole.COMPARATEUR: 8.0,
        AgentRole.DEBUGGER: 7.5,
        AgentRole.PLANNER: 8.5,
        AgentRole.MEMORY: 9.0,
        AgentRole.RAG_KNOWLEDGE: 8.5,
        "speed": 4,
        "note": "128k context, excellent pour synthèse longue",
    },
    "llama3.1": {
        AgentRole.JUGE: 8.5,
        AgentRole.ANALYSTE: 8.0,
        AgentRole.STRATEGE: 7.5,
        AgentRole.COMPARATEUR: 7.5,
        AgentRole.MEMORY: 8.5,
        AgentRole.RAG_KNOWLEDGE: 8.0,
        AgentRole.PLANNER: 7.5,
        "speed": 7,
    },
    "llama3.1:8b": {
        AgentRole.JUGE: 8.0,
        AgentRole.ANALYSTE: 7.5,
        AgentRole.MEMORY: 8.0,
        AgentRole.RAG_KNOWLEDGE: 7.5,
        "speed": 9,
    },
    "llama3": {
        AgentRole.JUGE: 7.5,
        AgentRole.ANALYSTE: 7.5,
        AgentRole.MEMORY: 7.5,
        AgentRole.LINUX_MGMT: 7.0,
        "speed": 9,
    },
    # ── Sécurité / Réseau ─────────────────────────────────────────────────────
    "mistral-small": {
        AgentRole.COMPARATEUR: 8.5,
        AgentRole.JUGE: 8.0,
        AgentRole.ANALYSTE: 7.5,
        AgentRole.DEBUGGER: 7.5,
        AgentRole.SECURITY: 8.0,
        AgentRole.NETWORK: 7.5,
        AgentRole.LOG_ANALYSIS: 8.0,
        AgentRole.IDS_ZEEK: 7.5,
        "speed": 8,
        "note": "Rapide, bon diff/évaluation",
    },
    "mistral": {
        AgentRole.COMPARATEUR: 8.0,
        AgentRole.JUGE: 7.5,
        AgentRole.SECURITY: 7.5,
        AgentRole.NETWORK: 7.0,
        AgentRole.LOG_ANALYSIS: 7.5,
        "speed": 9,
    },
    "gemma3": {
        AgentRole.COMPARATEUR: 8.0,
        AgentRole.ANALYSTE: 7.5,
        AgentRole.JUGE: 7.0,
        AgentRole.LINUX_MGMT: 7.5,
        AgentRole.LOG_ANALYSIS: 7.5,
        "speed": 8,
        "note": "Google, bon contexte créatif",
    },
    # ── Fallback ──────────────────────────────────────────────────────────────
    "__default__": {
        AgentRole.ANALYSTE: 6.0,
        AgentRole.DEBUGGER: 6.0,
        AgentRole.COMPARATEUR: 6.0,
        AgentRole.STRATEGE: 6.0,
        AgentRole.JUGE: 6.0,
        AgentRole.PLANNER: 6.0,
        AgentRole.DISCOVERY: 6.0,
        AgentRole.DEVOPS: 6.0,
        AgentRole.NETWORK: 6.0,
        AgentRole.SECURITY: 6.0,
        AgentRole.LOG_ANALYSIS: 6.0,
        AgentRole.RAG_KNOWLEDGE: 6.0,
        AgentRole.ACTION_EXEC: 6.0,
        AgentRole.MEMORY: 6.0,
        AgentRole.MONITORING: 6.0,
        AgentRole.PATCH_MGMT: 6.0,
        AgentRole.COMPLIANCE: 6.0,
        AgentRole.INCIDENT: 6.0,
        AgentRole.CONFIG_BACKUP: 6.0,
        AgentRole.THREAT_INTEL: 6.0,
        AgentRole.ACTIVE_DIR: 6.0,
        AgentRole.WINDOWS_MGMT: 6.0,
        AgentRole.LINUX_MGMT: 6.0,
        AgentRole.NETWORK_DEVICE: 6.0,
        AgentRole.DNS_PIHOLE: 6.0,
        AgentRole.IDS_ZEEK: 6.0,
        "speed": 7,
        "note": "Profil générique — modèle non répertorié",
    },
}


# =============================================================================
# ROUTAGE INTELLIGENT — détecte le rôle ops depuis le texte utilisateur
# =============================================================================

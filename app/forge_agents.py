from __future__ import annotations

"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_165156_cerberusok
#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: Args/Returns/Raises
"""

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
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

import asyncio
import aiohttp
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.settings import get_settings as _forge_settings  # noqa: F401
# Context:


class _SettingsProxy:
    """Proxy that lazily accesses attributes from the forged settings object.

    When an attribute is requested, it retrieves the current settings via
    :func:`_forge_settings` and returns the attribute value if the settings
    object exists; otherwise it returns ``None``.
    """

    def __getattr__(self, k: str) -> object:
        """Retrieve an attribute from the lazily loaded settings.

        Args:
            k (str): Name of the attribute to fetch from the settings object.

        Returns:
            The attribute value if settings are available, otherwise ``None``.
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


class IntentRouter:
    """
    Détecte automatiquement le(s) rôle(s) DevOps approprié(s)
    à partir du texte utilisateur.
    """

    # Priorité des rôles (ordre de résolution si ambigu)
    PRIORITY: List[AgentRole] = [
        AgentRole.INCIDENT,  # urgence > tout
        AgentRole.SECURITY,  # sécurité ensuite
        AgentRole.DEVOPS,  # CI/CD
        AgentRole.NETWORK,
        AgentRole.ACTIVE_DIR,
        AgentRole.WINDOWS_MGMT,
        AgentRole.LINUX_MGMT,
        AgentRole.NETWORK_DEVICE,
        AgentRole.DNS_PIHOLE,
        AgentRole.IDS_ZEEK,
        AgentRole.LOG_ANALYSIS,
        AgentRole.MONITORING,
        AgentRole.PATCH_MGMT,
        AgentRole.COMPLIANCE,
        AgentRole.CONFIG_BACKUP,
        AgentRole.THREAT_INTEL,
        AgentRole.DISCOVERY,
        AgentRole.ACTION_EXEC,
        AgentRole.RAG_KNOWLEDGE,
        AgentRole.PLANNER,
        AgentRole.MEMORY,
    ]

    def route(self, text: str, max_roles: int = 3) -> List[AgentRole]:
        """
        Retourne une liste ordonnée de rôles pertinents pour la demande.
        Le premier est le rôle principal.
        """
        lower = text.lower()
        scores: Dict[AgentRole, int] = {}

        for role in self.PRIORITY:
            keywords = ROLE_KEYWORDS.get(role, [])
            score = sum(1 for kw in keywords if kw in lower)
            if score > 0:
                scores[role] = score

        # Trier par score décroissant, puis par priorité en cas d'égalité
        ranked = sorted(scores.keys(), key=lambda r: (-scores[r], self.PRIORITY.index(r)))

        # Si aucun rôle détecté → RAG_KNOWLEDGE par défaut (conversation)
        if not ranked:
            return [AgentRole.RAG_KNOWLEDGE]

        return ranked[:max_roles]

    def route_with_confidence(self, text: str) -> Tuple[AgentRole, float, List[AgentRole]]:
        """
        Retourne (rôle_principal, confiance, rôles_secondaires).
        Confiance ∈ [0, 1].
        """
        logger.debug(f"[route_with_confidence] text={text[:80]!r}")
        roles = self.route(text, max_roles=5)
        if not roles:
            return AgentRole.RAG_KNOWLEDGE, 0.3, []

        lower = text.lower()
        main = roles[0]
        main_keywords = ROLE_KEYWORDS.get(main, [])
        hits = sum(1 for kw in main_keywords if kw in lower)
        total_kw = len(main_keywords)
        confidence = min(1.0, hits / max(total_kw * 0.3, 1))

        return main, confidence, roles[1:]


# =============================================================================
# BENCHMARK DYNAMIQUE
# =============================================================================


@dataclass
class ModelBenchmark:
    model: str
    tokens_per_second: float = 0.0
    first_token_latency_ms: float = 0.0
    quality_score: float = 0.0
    available: bool = True


class ModelBenchmarker:
    """
    Benchmark live : prompt de test → mesure tokens/s + qualité.
    Score dynamique = qualité * 0.6 + vitesse * 0.4
    """

    BENCH_PROMPT = (
        "Analyse ce code Python et liste les 3 principaux problèmes en 3 lignes max :\n"
        "```python\n"
        "def process(data):\n"
        "    result = []\n"
        "    for i in range(len(data)):\n"
        "        result.append(data[i] * 2)\n"
        "    return result\n"
        "```"
    )

    def __init__(self, ollama_url: str) -> None:
        """Init.

        Args:
            ollama_url: Description.
        """
        self.ollama_url = ollama_url
        self._cache: Dict[str, ModelBenchmark] = {}

    @staticmethod
    def _is_cloud_model(model: str) -> bool:
        """Détecte les modèles cloud (très lents au premier token)."""
        return any(tag in model.lower() for tag in ("cloud", "671b", "480b", "120b", "405b", "70b"))

    async def benchmark(self, model: str) -> ModelBenchmark:
        """Benchmark.

        Args:
            model: Description.
        """
        if model in self._cache:
            return self._cache[model]

        bench = ModelBenchmark(model=model)
        is_cloud = self._is_cloud_model(model)

        # Modèles cloud : bench incompatible (latence >30s) → score statique seul
        if is_cloud:
            bench.available = True  # marquer disponible
            bench.quality_score = 8.5  # qualité présumée haute
            bench.tokens_per_second = 15.0  # tok/s estimé cloud
            bench.first_token_latency_ms = 3000.0  # latence cloud typique
            self._cache[model] = bench
            logger.debug(f"Benchmark {model}: modèle cloud → score statique (8.5/10)")
            return bench

        try:
            t_start = time.perf_counter()
            first_token_time = None
            tokens = 0
            full = []

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.ollama_url,
                    json={"model": model, "messages": [{"role": "user", "content": self.BENCH_PROMPT}], "stream": True},
                    timeout=aiohttp.ClientTimeout(total=45, connect=5),
                ) as resp:
                    if resp.status != 200:
                        bench.available = False
                        return bench
                    async for line in resp.content:
                        if not line:
                            continue
                        try:
                            data = json.loads(line.decode("utf-8", errors="replace").strip())
                        except Exception:
                            continue
                        tok = data.get("message", {}).get("content", "")
                        if tok:
                            if first_token_time is None:
                                first_token_time = time.perf_counter()
                                bench.first_token_latency_ms = (first_token_time - t_start) * 1000
                            tokens += len(tok.split())
                            full.append(tok)
                        if data.get("done"):
                            break

            elapsed = time.perf_counter() - t_start
            bench.tokens_per_second = tokens / max(elapsed, 0.1)
            bench.quality_score = self._score_response("".join(full))

        except Exception as e:
            logger.warning(f"Benchmark {model} : {e}")
            bench.available = False

        self._cache[model] = bench
        return bench

    def _score_response(self, reply: str) -> float:
        """Score response.

        Args:
            reply: Description.
        """
        if not reply or len(reply) < 20:
            return 0.0
        score = 4.0
        if any(k in reply.lower() for k in ["problème", "problem", "issue", "1.", "•", "-"]):
            score += 1.5
        tech = ["range", "enumerate", "comprehension", "performance", "O(n)", "inefficace", "append", "list"]
        score += min(2.5, sum(0.5 for t in tech if t in reply))
        words = len(reply.split())
        if 25 < words < 250:
            score += 1.0
        if re.search(r"\d+\.", reply):
            score += 0.5
        return min(10.0, score)


# =============================================================================
# ASSIGNATION DES RÔLES
# =============================================================================


@dataclass
class RoleAssignment:
    role: AgentRole
    model: str
    static_score: float
    dynamic_score: float = 0.0
    final_score: float = 0.0

    def __str__(self) -> str:
        """Str."""
        meta = ROLE_META.get(self.role, {})
        icon = meta.get("icon", "?")
        label = meta.get("label", self.role.value)
        return (
            f"  {icon} [{label:20}] → {self.model:30} "
            f"(statique={self.static_score:.1f} "
            f"dynamic={self.dynamic_score:.1f} "
            f"final={self.final_score:.1f})"
        )


class RoleOrchestrator:
    """
    Attribue dynamiquement les rôles aux modèles disponibles.

    Algorithme :
      1. Récupère les modèles depuis Ollama
      2. Benchmark optionnel (live)
      3. Score final = 70% profil statique + 30% benchmark live
      4. Attribution greedy : chaque rôle prend le meilleur modèle libre
         (un modèle peut être partagé si pas assez de modèles)
    """

    # Rôles requis par boucle d'amélioration de code (B1/B2/B3)
    ROLES_PER_LOOP = {
        1: [AgentRole.DEBUGGER, AgentRole.ANALYSTE],
        2: [AgentRole.DEBUGGER, AgentRole.ANALYSTE, AgentRole.STRATEGE],
        3: [AgentRole.DEBUGGER, AgentRole.ANALYSTE, AgentRole.STRATEGE, AgentRole.COMPARATEUR, AgentRole.JUGE],
    }

    # Rôles ops core (toujours assignés si disponibles)
    OPS_CORE_ROLES = [
        AgentRole.PLANNER,
        AgentRole.ACTION_EXEC,
        AgentRole.MEMORY,
        AgentRole.RAG_KNOWLEDGE,
    ]

    def __init__(self, ollama_url: str, ollama_tags_url: str) -> None:
        """Init.

        Args:
            ollama_url: Description.
            ollama_tags_url: Description.
        """
        self.ollama_url = ollama_url
        self.ollama_tags_url = ollama_tags_url
        self.benchmarker = ModelBenchmarker(ollama_url)
        self.router = IntentRouter()
        self._available: List[str] = []
        self._assignments: Dict[AgentRole, str] = {}
        self._benchmarks: Dict[str, ModelBenchmark] = {}

    # ── Découverte ─────────────────────────────────────────────────────────────
    async def discover_models(self) -> List[str]:
        """Discover models."""
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(self.ollama_tags_url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    data = await resp.json()
                    models = [m["name"] for m in data.get("models", []) if "embed" not in m["name"].lower()]
                    self._available = models
                    logger.info(f"Modèles découverts : {models}")
                    return models
        except Exception as e:
            logger.warning(f"Découverte modèles : {e}")
            return []

    # ── Benchmark ──────────────────────────────────────────────────────────────
    async def run_benchmarks(self, log_fn: object = None) -> Dict[str, ModelBenchmark]:
        """Run benchmarks.

        Args:
            log_fn: Description.
        """
        if not self._available:
            await self.discover_models()
        if log_fn:
            log_fn(f"[dim]⏱ Benchmark de {len(self._available)} modèles…[/]")
        results = await asyncio.gather(
            *[self.benchmarker.benchmark(m) for m in self._available],
            return_exceptions=True,
        )
        for model, result in zip(self._available, results):
            if isinstance(result, ModelBenchmark):
                self._benchmarks[model] = result
                if log_fn:
                    if result.available:
                        is_cloud = self.benchmarker._is_cloud_model(model)
                        tag = "[cloud]" if is_cloud else ""
                        log_fn(
                            f"  {model:30} "
                            f"{result.tokens_per_second:5.1f} tok/s  "
                            f"qualité={result.quality_score:.1f}/10  "
                            f"lat={result.first_token_latency_ms:.0f}ms {tag}"
                        )
                    else:
                        log_fn(f"  {model:30} indisponible (timeout/erreur)")
        return self._benchmarks

    # ── Clé de profil ──────────────────────────────────────────────────────────
    def _profile_key(self, model: str) -> str:
        """Profile key.

        Args:
            model: Description.
        """
        ml = model.lower()
        for key in sorted(MODEL_PROFILES.keys(), key=len, reverse=True):
            if key == "__default__":
                continue
            if ml.startswith(key) or key in ml:
                return key
        return "__default__"

    # ── Score final ────────────────────────────────────────────────────────────
    def _score(self, model: str, role: AgentRole) -> RoleAssignment:
        """Score.

        Args:
            model: Description.
            role: Description.
        """
        profile = MODEL_PROFILES.get(self._profile_key(model), MODEL_PROFILES["__default__"])
        static_score = profile.get(role, 6.0)
        bench = self._benchmarks.get(model)
        dynamic_score = 0.0
        if bench and bench.available:
            speed_score = min(10.0, bench.tokens_per_second / 8.0)
            dynamic_score = bench.quality_score * 0.6 + speed_score * 0.4
        # Modèle cloud sans bench mesuré → ne pas pénaliser, score statique seul
        if not bench or not bench.available:
            if self.benchmarker._is_cloud_model(model):
                dynamic_score = 7.0  # score dynamique présumé bon pour cloud
        final = static_score * 0.7 + dynamic_score * 0.3
        return RoleAssignment(
            role=role,
            model=model,
            static_score=static_score,
            dynamic_score=dynamic_score,
            final_score=final,
        )

    # ── Attribution générique ──────────────────────────────────────────────────
    def _greedy_assign(self, roles: List[AgentRole], log_fn: object = None) -> Dict[AgentRole, str]:
        """Attribution greedy : peut partager un modèle si manque de modèles."""
        assignments: Dict[AgentRole, str] = {}
        used: Set[str] = set()

        for role in roles:
            candidates = sorted(
                [self._score(m, role) for m in self._available],
                key=lambda a: a.final_score,
                reverse=True,
            )
            # Préférer modèle non utilisé
            chosen = next((c for c in candidates if c.model not in used), None)
            # Sinon réutiliser le meilleur
            if chosen is None and candidates:
                chosen = candidates[0]
            if chosen:
                assignments[role] = chosen.model
                used.add(chosen.model)
                if log_fn:
                    log_fn(str(chosen))

        return assignments

    # ── Attribution loops (code) ───────────────────────────────────────────────
    async def assign_roles(
        self,
        loop_number: int = 1,
        run_benchmark: bool = True,
        log_fn: object = None,
    ) -> Dict[AgentRole, str]:
        """Attribution pour les boucles d'amélioration de code (B1/B2/B3)."""
        if not self._available:
            await self.discover_models()
        if not self._available:
            return {}
        if run_benchmark and not self._benchmarks:
            await self.run_benchmarks(log_fn)

        roles_needed = self.ROLES_PER_LOOP.get(loop_number, self.ROLES_PER_LOOP[1])

        if log_fn:
            log_fn(f"\n[bold]Attribution des rôles code (boucle {loop_number})[/]")

        assignments = self._greedy_assign(roles_needed, log_fn)
        self._assignments.update(assignments)
        return assignments

    # ── Attribution ops (DevOps runtime) ──────────────────────────────────────
    async def assign_ops_roles(
        self,
        requested_roles: Optional[List[AgentRole]] = None,
        run_benchmark: bool = False,
        log_fn: object = None,
    ) -> Dict[AgentRole, str]:
        """
        Attribution des rôles DevOps opérationnels.
        requested_roles : liste spécifique, ou None pour les rôles core.
        """
        if not self._available:
            await self.discover_models()
        if not self._available:
            return {}
        if run_benchmark and not self._benchmarks:
            await self.run_benchmarks(log_fn)

        roles = requested_roles or self.OPS_CORE_ROLES
        if log_fn:
            log_fn(f"\n[bold]Attribution des rôles ops ({len(roles)} rôles)[/]")

        assignments = self._greedy_assign(roles, log_fn)
        self._assignments.update(assignments)
        return assignments

    # ── Attribution à la volée depuis l'intention ──────────────────────────────
    async def assign_from_intent(
        self,
        user_text: str,
        log_fn: object = None,
    ) -> Tuple[AgentRole, str, List[Tuple[AgentRole, str]]]:
        """
        Détecte le rôle principal et les rôles secondaires depuis le texte,
        puis assigne les meilleurs modèles.

        Retourne : (rôle_principal, modèle_principal, [(rôle_sec, modèle_sec), ...])
        """
        if not self._available:
            await self.discover_models()

        main_role, confidence, secondary_roles = self.router.route_with_confidence(user_text)

        all_roles = [main_role] + secondary_roles
        assignments = self._greedy_assign(all_roles)
        self._assignments.update(assignments)

        main_model = assignments.get(main_role, self._available[0] if self._available else "")
        secondary = [(r, assignments[r]) for r in secondary_roles if r in assignments]

        if log_fn:
            meta = ROLE_META.get(main_role, {})
            log_fn(
                f"[dim]🎯 Rôle détecté : {meta.get('icon', '?')} "
                f"{meta.get('label', main_role.value)} "
                f"(confiance={confidence:.0%}) → {main_model}[/]"
            )
            for r, m in secondary:
                rm = ROLE_META.get(r, {})
                log_fn(f"[dim]   + {rm.get('icon', '?')} {rm.get('label', r.value)} → {m}[/]")

        return main_role, main_model, secondary

    # ── Accès ──────────────────────────────────────────────────────────────────
    def get_model(self, role: AgentRole) -> Optional[str]:
        """Get model.

        Args:
            role: Description.
        """
        return self._assignments.get(role)

    def get_best_model_for_role(self, role: AgentRole) -> Optional[str]:
        """Retourne le meilleur modèle disponible pour un rôle sans l'assigner."""
        if not self._available:
            return None
        candidates = sorted(
            [self._score(m, role) for m in self._available],
            key=lambda a: a.final_score,
            reverse=True,
        )
        return candidates[0].model if candidates else None

    def summary(self) -> str:
        """Summary."""
        if not self._assignments:
            return "Aucun rôle attribué."
        lines = ["Rôles attribués :"]
        for role, model in self._assignments.items():
            meta = ROLE_META.get(role, {})
            note = MODEL_PROFILES.get(self._profile_key(model), MODEL_PROFILES["__default__"]).get("note", "")
            lines.append(
                f"  {meta.get('icon', '?')} [{meta.get('label', role.value):20}] "
                f"{model}  {('← ' + note) if note else ''}"
            )
        return "\n".join(lines)

    @property
    def available_models(self) -> List[str]:
        """Available models."""
        return list(self._available)


# =============================================================================
# § 2 — SCORING ET ARCHITECTURE  (ex-scoring.py)
# =============================================================================

# Import des rôles depuis roles.py (déjà dans le projet)
# =============================================================================
# ARCHITECTURE CIBLE
# =============================================================================


class OSFamily(Enum):
    LINUX = "linux"
    WINDOWS = "windows"
    MACOS = "macos"
    UNKNOWN = "unknown"


class Distrib(Enum):
    DEBIAN = "debian"
    UBUNTU = "ubuntu"
    RHEL = "rhel"  # RHEL / CentOS / AlmaLinux / Rocky
    FEDORA = "fedora"
    ARCH = "arch"
    ALPINE = "alpine"
    SUSE = "suse"
    WINDOWS = "windows"
    MACOS = "macos"
    UNKNOWN = "unknown"


class CPUArch(Enum):
    X86_64 = "x86_64"
    ARM64 = "arm64"
    ARMV7 = "armv7"
    X86_32 = "x86_32"
    UNKNOWN = "unknown"


class ContainerRuntime(Enum):
    DOCKER = "docker"
    PODMAN = "podman"
    CONTAINERD = "containerd"
    NONE = "none"
    UNKNOWN = "unknown"


@dataclass
class ArchitectureProfile:
    """Profil complet de l'hôte distant détecté via SSH."""

    os_family: OSFamily = OSFamily.UNKNOWN
    distrib: Distrib = Distrib.UNKNOWN
    distrib_version: str = ""
    cpu_arch: CPUArch = CPUArch.UNKNOWN
    kernel: str = ""
    hostname: str = ""
    container_runtime: ContainerRuntime = ContainerRuntime.UNKNOWN
    has_systemd: bool = False
    has_docker: bool = False
    has_snap: bool = False
    pkg_manager: str = ""  # apt / dnf / yum / pacman / apk …
    python_version: str = ""
    raw: Dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        """Summary."""
        parts = []
        if self.hostname:
            parts.append(self.hostname)
        parts.append(self.distrib.value)
        if self.distrib_version:
            parts.append(self.distrib_version)
        parts.append(self.cpu_arch.value)
        if self.kernel:
            parts.append(f"kernel={self.kernel}")
        if self.container_runtime != ContainerRuntime.NONE:
            parts.append(self.container_runtime.value)
        return " | ".join(parts)

    def context_hint(self) -> str:
        """Texte injecté dans le system-prompt pour contextualiser les commandes."""
        lines = [
            f"CIBLE : {self.os_family.value} / {self.distrib.value} {self.distrib_version}",
            f"ARCH CPU : {self.cpu_arch.value}",
        ]
        if self.pkg_manager:
            lines.append(f"GESTIONNAIRE DE PAQUETS : {self.pkg_manager}")
        if self.has_systemd:
            lines.append("INIT : systemd")
        if self.has_docker:
            lines.append(f"CONTAINER : {self.container_runtime.value}")
        if self.python_version:
            lines.append(f"PYTHON : {self.python_version}")
        lines.append(
            "⚠ Génère UNIQUEMENT des commandes compatibles avec cette architecture. "
            "N'utilise pas de binaires x86_64 sur arm64, ni apt sur rhel, etc."
        )
        return "\n".join(lines)


# =============================================================================
# DÉTECTEUR D'ARCHITECTURE
# =============================================================================


class ArchitectureDetector:
    """Interroge le host distant via SSH pour construire un ArchitectureProfile."""

    # Commandes de détection (ordre : rapide → précis)
    PROBE_COMMANDS: Dict[str, str] = {
        "uname_sr": "uname -sr 2>/dev/null || echo unknown",
        "uname_m": "uname -m 2>/dev/null || echo unknown",
        "hostname": "hostname -s 2>/dev/null || hostname",
        "os_release": "cat /etc/os-release 2>/dev/null || echo ''",
        "systemd": "systemctl --version 2>/dev/null | head -1 || echo ''",
        "docker": "docker --version 2>/dev/null || echo ''",
        "podman": "podman --version 2>/dev/null || echo ''",
        "python": "python3 --version 2>/dev/null || python --version 2>/dev/null || echo ''",
        "pkg_apt": "apt --version 2>/dev/null | head -1 || echo ''",
        "pkg_dnf": "dnf --version 2>/dev/null | head -1 || echo ''",
        "pkg_yum": "yum --version 2>/dev/null | head -1 || echo ''",
        "pkg_pacman": "pacman --version 2>/dev/null | head -1 || echo ''",
        "pkg_apk": "apk --version 2>/dev/null || echo ''",
        "winver": "cmd /c ver 2>/dev/null || echo ''",
    }

    def __init__(self, run_ssh_fn: object) -> None:
        """
        run_ssh_fn : coroutine async (cmd: str) -> (stdout, stderr, exit_code)
        Typiquement run_ssh() de Nokido.
        """
        self._run = run_ssh_fn
        self._cache: Optional[ArchitectureProfile] = None
        self._cache_ts: float = 0.0
        self._cache_ttl: float = 300.0  # re-détecte toutes les 5 min

    async def detect(self, force: bool = False) -> ArchitectureProfile:
        """Retourne le profil mis en cache ou relance la détection."""
        now = time.monotonic()
        if not force and self._cache is not None and now - self._cache_ts < self._cache_ttl:
            return self._cache

        results: Dict[str, str] = {}
        # Parallélise les probes
        cmds = list(self.PROBE_COMMANDS.items())
        outs = await asyncio.gather(*[self._probe(cmd) for _, cmd in cmds], return_exceptions=True)
        for (key, _), out in zip(cmds, outs):
            results[key] = out if isinstance(out, str) else ""

        profile = self._parse(results)
        self._cache = profile
        self._cache_ts = now
        logger.info(f"Architecture détectée : {profile.summary()}")
        return profile

    async def _probe(self, cmd: str) -> str:
        """Probe.

        Args:
            cmd: Description.
        """
        try:
            stdout, _, _ = await self._run(cmd)
            return stdout.strip()
        except Exception:
            return ""

    def _parse(self, r: Dict[str, str]) -> ArchitectureProfile:
        """Parse.

        Args:
            r: Description.
        """
        p = ArchitectureProfile(raw=r)

        # ── Hostname ──────────────────────────────────────────────────────
        p.hostname = r.get("hostname", "")

        # ── Kernel / OS family ────────────────────────────────────────────
        uname_sr = r.get("uname_sr", "").lower()
        if "linux" in uname_sr:
            p.os_family = OSFamily.LINUX
            p.kernel = re.search(r"[\d\.\-]+", uname_sr.split()[-1] if uname_sr.split() else "")
            p.kernel = p.kernel.group(0) if p.kernel else uname_sr
        elif "windows" in uname_sr or r.get("winver", ""):
            p.os_family = OSFamily.WINDOWS
        elif "darwin" in uname_sr:
            p.os_family = OSFamily.MACOS

        # ── CPU arch ──────────────────────────────────────────────────────
        arch_raw = r.get("uname_m", "").lower()
        if arch_raw in ("x86_64", "amd64"):
            p.cpu_arch = CPUArch.X86_64
        elif arch_raw in ("aarch64", "arm64"):
            p.cpu_arch = CPUArch.ARM64
        elif arch_raw.startswith("armv7"):
            p.cpu_arch = CPUArch.ARMV7
        elif arch_raw in ("i386", "i686"):
            p.cpu_arch = CPUArch.X86_32

        # ── Distribution (/etc/os-release) ────────────────────────────────
        os_rel = r.get("os_release", "").lower()
        id_match = re.search(r'^id="?([^"\n]+)"?', os_rel, re.MULTILINE)
        ver_match = re.search(r'^version_id="?([^"\n]+)"?', os_rel, re.MULTILINE)
        distrib_id = id_match.group(1).strip() if id_match else ""
        p.distrib_version = ver_match.group(1).strip() if ver_match else ""

        if "ubuntu" in distrib_id:
            p.distrib = Distrib.UBUNTU
        elif "debian" in distrib_id:
            p.distrib = Distrib.DEBIAN
        elif any(x in distrib_id for x in ("rhel", "centos", "almalinux", "rocky")):
            p.distrib = Distrib.RHEL
        elif "fedora" in distrib_id:
            p.distrib = Distrib.FEDORA
        elif "arch" in distrib_id:
            p.distrib = Distrib.ARCH
        elif "alpine" in distrib_id:
            p.distrib = Distrib.ALPINE
        elif "opensuse" in distrib_id or "sles" in distrib_id:
            p.distrib = Distrib.SUSE
        elif p.os_family == OSFamily.WINDOWS:
            p.distrib = Distrib.WINDOWS
        elif p.os_family == OSFamily.MACOS:
            p.distrib = Distrib.MACOS

        # ── Systemd ───────────────────────────────────────────────────────
        p.has_systemd = "systemd" in r.get("systemd", "").lower()

        # ── Container runtime ─────────────────────────────────────────────
        if "docker" in r.get("docker", "").lower():
            p.container_runtime = ContainerRuntime.DOCKER
            p.has_docker = True
        elif "podman" in r.get("podman", "").lower():
            p.container_runtime = ContainerRuntime.PODMAN
        else:
            p.container_runtime = ContainerRuntime.NONE

        # ── Package manager ───────────────────────────────────────────────
        if r.get("pkg_apt", "") and "apt" in r["pkg_apt"].lower():
            p.pkg_manager = "apt"
        elif r.get("pkg_dnf", "") and "dnf" in r["pkg_dnf"].lower():
            p.pkg_manager = "dnf"
        elif r.get("pkg_yum", "") and "yum" in r["pkg_yum"].lower():
            p.pkg_manager = "yum"
        elif r.get("pkg_pacman", "") and "pacman" in r["pkg_pacman"].lower():
            p.pkg_manager = "pacman"
        elif r.get("pkg_apk", "") and "apk" in r["pkg_apk"].lower():
            p.pkg_manager = "apk"

        # ── Python ────────────────────────────────────────────────────────
        py_raw = r.get("python", "")
        py_match = re.search(r"(\d+\.\d+\.\d+)", py_raw)
        p.python_version = py_match.group(1) if py_match else ""

        return p


# =============================================================================
# SCORING ENRICHI — tient compte de l'architecture cible
# =============================================================================

# Pénalités de score appliquées si le modèle est mal adapté à la cible
# Format : (condition_fn(arch), rôles_affectés, pénalité)
ARCH_PENALTIES: List[Tuple] = [
    # Si la cible est Windows, pénaliser les modèles sans profil Windows
    (
        lambda arch: arch.os_family == OSFamily.WINDOWS,
        {AgentRole.LINUX_MGMT, AgentRole.ACTION_EXEC, AgentRole.DEVOPS},
        -2.0,
    ),
    # Si la cible est ARM64, légère pénalité sur les profils trop x86-centrés
    (
        lambda arch: arch.cpu_arch == CPUArch.ARM64,
        {AgentRole.DEVOPS, AgentRole.ACTION_EXEC},
        -0.5,
    ),
    # Alpine → pénalise les suggestions apt/yum
    (
        lambda arch: arch.distrib == Distrib.ALPINE,
        {AgentRole.PATCH_MGMT, AgentRole.LINUX_MGMT},
        -1.0,
    ),
]

# Bonus si profil du modèle inclut une mention spécifique (ex: "adguard", "pihole")
ROLE_ARCH_BONUS: Dict[AgentRole, Dict[Distrib, float]] = {
    AgentRole.DNS_PIHOLE: {Distrib.DEBIAN: 0.5, Distrib.UBUNTU: 0.5},
    AgentRole.LINUX_MGMT: {Distrib.UBUNTU: 0.5, Distrib.DEBIAN: 0.5, Distrib.RHEL: 0.5, Distrib.ARCH: 0.3},
    AgentRole.WINDOWS_MGMT: {Distrib.WINDOWS: 1.5},
    AgentRole.ACTIVE_DIR: {Distrib.WINDOWS: 1.5},
}


@dataclass
class ScoredModel:
    model: str
    role: AgentRole
    static_score: float
    dynamic_score: float
    arch_bonus: float
    arch_penalty: float
    final_score: float

    def __str__(self) -> str:
        """Str."""
        meta = ROLE_META.get(self.role, {})
        return (
            f"  {meta.get('icon', '?')} [{meta.get('label', self.role.value):22}] "
            f"→ {self.model:35} "
            f"(S={self.static_score:.1f} D={self.dynamic_score:.1f} "
            f"A={self.arch_bonus:+.1f}/{self.arch_penalty:+.1f} "
            f"F={self.final_score:.2f})"
        )


# =============================================================================
# BENCHMARK DYNAMIQUE (version allégée, sans dépendances loops.py)
# =============================================================================

BENCH_PROMPT = (
    "Réponds en 3 lignes max. Quels sont les 3 principaux risques de sécurité "
    "dans une config SSH par défaut sur Linux ?"
)


@dataclass
class BenchResult:
    model: str
    tok_per_sec: float = 0.0
    latency_ms: float = 0.0
    quality: float = 0.0  # [0-10]
    available: bool = True


# _run_bench — voir forge_agent_hardware.py


def _score_reply(reply: str) -> float:
    """Score reply.

    Args:
        reply: Description.
    """
    if not reply or len(reply) < 15:
        return 0.0
    s = 3.0
    keywords = [
        "ssh",
        "root",
        "password",
        "clé",
        "key",
        "port",
        "firewall",
        "auth",
        "permission",
        "sudo",
        "fail2ban",
        "brute",
    ]
    s += min(4.0, sum(0.5 for k in keywords if k in reply.lower()))
    if re.search(r"\d+\.", reply):
        s += 1.0
    words = len(reply.split())
    if 15 < words < 200:
        s += 1.0
    if len(reply) < 50:
        s -= 1.0
    return min(10.0, max(0.0, s))


# =============================================================================
# SCOREUR CENTRAL
# =============================================================================


class ModelScorer:
    """
    Point d'entrée unique pour le scoring des modèles.

    Workflow :
      1. scorer = ModelScorer(ollama_url, ollama_tags_url, run_ssh_fn)
      2. await scorer.refresh()         → discover + benchmark en arrière-plan
      3. arch = await scorer.get_arch() → profil architecture cible
      4. model = scorer.best_for(role, arch)
    """

    def __init__(
        self,
        ollama_url: str,
        ollama_tags_url: str,
        run_ssh_fn: object = None,  # async fn(cmd) -> (stdout, stderr, rc)
    ):
        """Init.

        Args:
            ollama_url: Description.
            ollama_tags_url: Description.
            run_ssh_fn: Description.
        """
        self.ollama_url = ollama_url
        self.ollama_tags_url = ollama_tags_url
        self._run_ssh = run_ssh_fn
        self._models: List[str] = []
        self._benches: Dict[str, BenchResult] = {}
        self._refreshed: bool = False
        self._arch: Optional[ArchitectureProfile] = None
        self._arch_detector: Optional[ArchitectureDetector] = None
        if run_ssh_fn:
            self._arch_detector = ArchitectureDetector(run_ssh_fn)

    # ── Découverte des modèles ─────────────────────────────────────────────────
    async def discover(self) -> List[str]:
        """Discover."""
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    self.ollama_tags_url,
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    data = await resp.json()
                    self._models = [m["name"] for m in data.get("models", []) if "embed" not in m["name"].lower()]
                    logger.info(f"Modèles Ollama : {self._models}")
        except Exception as e:
            logger.warning(f"Discover models: {e}")
        return self._models

    # ── Benchmark en arrière-plan ─────────────────────────────────────────────
    async def refresh(self, bench: bool = True) -> None:
        """Discover + benchmark asynchrone (non-bloquant pour l'UI)."""
        await self.discover()
        if bench and self._models:
            from nokido_agent.app.forge_agent_hardware import _run_bench

            results = await asyncio.gather(
                *[_run_bench(self.ollama_url, m) for m in self._models],
                return_exceptions=True,
            )
            for m, r in zip(self._models, results):
                if isinstance(r, BenchResult):
                    self._benches[m] = r
        self._refreshed = True

    # ── Détection d'architecture ──────────────────────────────────────────────
    async def get_arch(self, force: bool = False) -> Optional[ArchitectureProfile]:
        """Get arch.

        Args:
            force: Description.
        """
        if self._arch_detector is None:
            return None
        self._arch = await self._arch_detector.detect(force=force)
        return self._arch

    # ── Score d'un modèle pour un rôle ───────────────────────────────────────
    def score(
        self,
        model: str,
        role: AgentRole,
        arch: Optional[ArchitectureProfile] = None,
    ) -> ScoredModel:
        # ── Profil statique ──────────────────────────────────────────────
        """Score.

        Args:
            model: Description.
            role: Description.
            arch: Description.
        """
        profile_key = self._find_profile_key(model)
        profile = MODEL_PROFILES.get(profile_key, MODEL_PROFILES.get("__default__", {}))
        static_s = float(profile.get(role, 6.0))

        # ── Benchmark dynamique ──────────────────────────────────────────
        bench = self._benches.get(model)
        dyn_s = 0.0
        if bench and bench.available:
            speed_s = min(10.0, bench.tok_per_sec / 8.0)
            dyn_s = bench.quality * 0.6 + speed_s * 0.4

        # ── Bonus / Pénalités architecture ───────────────────────────────
        bonus = 0.0
        penalty = 0.0
        if arch:
            # Bonus distrib
            role_bonuses = ROLE_ARCH_BONUS.get(role, {})
            bonus = role_bonuses.get(arch.distrib, 0.0)
            # Pénalités architecture
            for cond_fn, affected_roles, pen in ARCH_PENALTIES:
                if role in affected_roles and cond_fn(arch):
                    penalty += pen

        final = static_s * 0.7 + dyn_s * 0.3 + bonus + penalty
        return ScoredModel(
            model=model,
            role=role,
            static_score=static_s,
            dynamic_score=dyn_s,
            arch_bonus=bonus,
            arch_penalty=penalty,
            final_score=max(0.0, final),
        )

    def _find_profile_key(self, model: str) -> str:
        """Find profile key.

        Args:
            model: Description.
        """
        ml = model.lower()
        # Tri par longueur desc pour préférer la clé la plus précise
        for key in sorted(MODEL_PROFILES.keys(), key=len, reverse=True):
            if key == "__default__":
                continue
            if ml.startswith(key) or key in ml:
                return key
        return "__default__"

    # ── Meilleur modèle pour un rôle ─────────────────────────────────────────
    def best_for(
        self,
        role: AgentRole,
        arch: Optional[ArchitectureProfile] = None,
        exclude: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        Retourne le nom du meilleur modèle disponible pour le rôle donné,
        en tenant compte de l'architecture cible.
        """
        if not self._models:
            return None
        pool = [m for m in self._models if not (exclude and m in exclude)]
        if not pool:
            pool = self._models

        scored = sorted(
            [self.score(m, role, arch) for m in pool],
            key=lambda s: s.final_score,
            reverse=True,
        )
        return scored[0].model if scored else None

    # ── Attribution multi-rôles (greedy sans doublons si possible) ─────────────
    def assign_roles(
        self,
        roles: List[AgentRole],
        arch: Optional[ArchitectureProfile] = None,
    ) -> Dict[AgentRole, str]:
        """
        Attribue un modèle à chaque rôle.
        Préfère éviter les doublons mais les autorise si nécessaire.
        """
        assignments: Dict[AgentRole, str] = {}
        used: List[str] = []
        for role in roles:
            m = self.best_for(role, arch, exclude=used)
            if m is None:
                m = self.best_for(role, arch)  # fallback avec doublons
            if m:
                assignments[role] = m
                used.append(m)
        return assignments

    # ── Rapport de scoring (pour @role list) ─────────────────────────────────
    def report(self, arch: Optional[ArchitectureProfile] = None) -> str:
        """Report.

        Args:
            arch: Description.
        """
        if not self._models:
            return "Aucun modèle découvert."
        lines = ["[bold]Banque de scoring — modèles disponibles :[/]"]
        for m in self._models:
            bench = self._benches.get(m)
            bench_str = ""
            if bench and bench.available:
                bench_str = (
                    f"  {bench.tok_per_sec:5.1f} tok/s  lat={bench.latency_ms:.0f}ms  qualité={bench.quality:.1f}/10"
                )
            lines.append(f"  • {m:40}{bench_str}")
        if arch:
            lines.append(f"\n[bold]Architecture cible :[/] {arch.summary()}")
        return "\n".join(lines)

    @property
    def models(self) -> List[str]:
        """Models."""
        return list(self._models)

    @property
    def is_ready(self) -> bool:
        """Is ready."""
        return self._refreshed and bool(self._models)


# =============================================================================
# § 3 — ROUTAGE INTELLIGENT  (ex-routage.py)
# =============================================================================

# =============================================================================
# CATÉGORIES DE ROUTAGE
# =============================================================================


class PromptCategory(Enum):
    TERMINAL = "terminal"  # commande SSH directe
    WEB = "web"  # recherche web nécessaire
    INFRA = "infra"  # orchestration multi-agents complexe
    CODE = "code"  # code Python, scripts, debugging
    SECURITY = "security"  # audit, CVE, durcissement
    NETWORK = "network"  # réseau, firewall, DNS
    LOG = "log"  # analyse de logs
    CHAT = "chat"  # conversation, explication, doc

    @classmethod
    def from_str(cls, s: str) -> "PromptCategory":
        """From str.

        Args:
            cls: Description.
            s: Description.
        """
        s = s.strip().lower()
        mapping = {
            "terminal": cls.TERMINAL,
            "shell": cls.TERMINAL,
            "ssh": cls.TERMINAL,
            "web": cls.WEB,
            "internet": cls.WEB,
            "search": cls.WEB,
            "infra": cls.INFRA,
            "infrastructure": cls.INFRA,
            "devops": cls.INFRA,
            "code": cls.CODE,
            "python": cls.CODE,
            "script": cls.CODE,
            "security": cls.SECURITY,
            "secu": cls.SECURITY,
            "pentest": cls.SECURITY,
            "network": cls.NETWORK,
            "réseau": cls.NETWORK,
            "firewall": cls.NETWORK,
            "log": cls.LOG,
            "logs": cls.LOG,
            "journal": cls.LOG,
            "chat": cls.CHAT,
            "doc": cls.CHAT,
            "help": cls.CHAT,
        }
        for key, cat in mapping.items():
            if key in s:
                return cat
        return cls.CHAT


# =============================================================================
# DÉFINITION DES 12 RÔLES AGENTS
# =============================================================================

AGENT_ROLES: List[Dict[str, Any]] = [
    {
        "key": "planner",
        "name": "Planner Agent",
        "role": "Planning et décomposition de tâches complexes en étapes atomiques",
        "categories": [PromptCategory.INFRA, PromptCategory.CODE],
        "icon": "📋",
    },
    {
        "key": "discovery",
        "name": "Discovery Agent",
        "role": "Inventaire système, cartographie réseau, scan de services et ports",
        "categories": [PromptCategory.INFRA, PromptCategory.NETWORK],
        "icon": "🗺",
    },
    {
        "key": "devops",
        "name": "DevOps Agent",
        "role": "CI/CD, Docker, Kubernetes, Ansible, Terraform, pipelines de déploiement",
        "categories": [PromptCategory.INFRA, PromptCategory.CODE],
        "icon": "⚙",
    },
    {
        "key": "network",
        "name": "Network Agent",
        "role": "Réseau TCP/IP, firewall iptables/nftables, VPN, VLAN, DNS, diagnostic",
        "categories": [PromptCategory.NETWORK, PromptCategory.INFRA],
        "icon": "🌐",
    },
    {
        "key": "security",
        "name": "Security Agent",
        "role": "Cybersécurité, CVE, durcissement CIS/NIST, pentest, audit de sécurité",
        "categories": [PromptCategory.SECURITY, PromptCategory.INFRA],
        "icon": "🔐",
    },
    {
        "key": "log_analysis",
        "name": "Log Analysis Agent",
        "role": "Analyse de logs système, applicatifs, sécurité, corrélation d'événements",
        "categories": [PromptCategory.LOG, PromptCategory.SECURITY],
        "icon": "📊",
    },
    {
        "key": "rag",
        "name": "RAG / Knowledge Agent",
        "role": "Base de connaissances, documentation, procédures, runbooks",
        "categories": [PromptCategory.CHAT, PromptCategory.WEB],
        "icon": "🗄",
    },
    {
        "key": "action_exec",
        "name": "Action / Execution Agent",
        "role": "Exécution de commandes, scripts, automatisation de tâches système",
        "categories": [PromptCategory.TERMINAL, PromptCategory.INFRA],
        "icon": "⚡",
    },
    {
        "key": "memory",
        "name": "Memory Agent",
        "role": "Contexte long terme, historique des décisions, patterns récurrents",
        "categories": [PromptCategory.CHAT, PromptCategory.INFRA],
        "icon": "🧠",
    },
    {
        "key": "monitoring",
        "name": "Monitoring Agent",
        "role": "Métriques CPU/RAM/disque/réseau, alertes Prometheus/Grafana, SLA",
        "categories": [PromptCategory.INFRA, PromptCategory.LOG],
        "icon": "📈",
    },
    {
        "key": "patch_mgmt",
        "name": "Patch Management Agent",
        "role": "Inventaire des patchs, CVE applicables, planification mises à jour",
        "categories": [PromptCategory.SECURITY, PromptCategory.INFRA],
        "icon": "🩹",
    },
    {
        "key": "compliance",
        "name": "Compliance Agent",
        "role": "Audit de conformité CIS/NIST/ISO27001, rapports réglementaires",
        "categories": [PromptCategory.SECURITY, PromptCategory.INFRA],
        "icon": "✅",
    },
]

# Index par clé
AGENT_BY_KEY: Dict[str, Dict] = {a["key"]: a for a in AGENT_ROLES}


# =============================================================================
# RÉSULTAT DE CONTRIBUTION D'AGENT
# =============================================================================


@dataclass
class AgentContrib:
    agent_key: str
    agent_name: str
    icon: str
    response: str
    score: float = 0.0
    error: bool = False
    elapsed_s: float = 0.0


# =============================================================================
# RUNNER OLLAMA PARALLÈLE (ollama run natif)
# =============================================================================


class OllamaParallelRunner:
    """
    Exécute des appels Ollama en parallèle via l'API HTTP /api/chat.
    Utilise asyncio.Semaphore pour limiter la concurrence.

    Deux modes :
      - stream=False : retourne le texte complet (idéal pour scoring, classification)
      - stream=True  : callback token par token (idéal pour affichage UI)
    """

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434/api/chat",
        max_concurrent: int = 4,
        timeout: float = 120.0,
    ):
        """Init.

        Args:
            ollama_url: Description.
            max_concurrent: Description.
            timeout: Description.
        """
        self.ollama_url = ollama_url
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.timeout = timeout
        self._model_cache: List[str] = []

    async def call(
        self,
        model: str,
        messages: List[Dict],
        system: Optional[str] = None,
        stream: bool = False,
        on_token: Optional[Any] = None,
        max_tokens: int = 512,
    ) -> str:
        """Appel LLM avec routing Engrid si modele cloud."""
        # ── Engrid routing : provider cloud → bridge hybride ─────────────────
        _cloud_prefixes = ("openrouter/", "deepseek/", "google/", "groq/", "anthropic/", "meta-llama/")
        _is_cloud = any(model.lower().startswith(p) for p in _cloud_prefixes)
        if _is_cloud and not stream:
            try:
                import sys as _sys, pathlib as _pl

                _root = str(_pl.Path(__file__).resolve().parent)
                if _root not in _sys.path:
                    _sys.path.insert(0, _root)
                from nokido_agent.app.forge_hybrid_bridge import MultiLLMBridge as _MB

                _bridge = _MB()
                _all_msgs = []
                if system:
                    _all_msgs.append({"role": "system", "content": system})
                _all_msgs.extend(messages)
                _prompt = " ".join(m.get("content", "") for m in _all_msgs)
                _fallback = "ollama/" + model.split("/")[-1]
                import asyncio as _aio

                return await _aio.get_event_loop().run_in_executor(
                    None,
                    lambda: _bridge.call_with_fallback(model, _prompt, _fallback, max_tokens),
                )
            except Exception as _be:
                logger.debug(f"[OllamaRunner] bridge fallback: {_be}")
                model = model.split("/")[-1]

        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)

        payload = {
            "model": model,
            "messages": msgs,
            "stream": stream,
            "options": {"num_predict": max_tokens},
        }

        async with self.semaphore:
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.post(
                        self.ollama_url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=self.timeout, connect=8),
                    ) as resp:
                        if resp.status != 200:
                            body = await resp.text()
                            raise RuntimeError(f"Ollama HTTP {resp.status}: {body[:200]}")

                        if not stream:
                            data = await resp.json()
                            return data.get("message", {}).get("content", "")

                        # Streaming
                        full = []
                        async for raw in resp.content:
                            if not raw:
                                continue
                            line = raw.decode("utf-8", errors="replace").strip()
                            if not line:
                                continue
                            try:
                                data = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            tok = data.get("message", {}).get("content", "")
                            if tok:
                                full.append(tok)
                                if on_token:
                                    on_token(tok)
                            if data.get("done"):
                                break
                        return "".join(full)

            except asyncio.TimeoutError:
                raise RuntimeError(f"Timeout Ollama ({model}) après {self.timeout}s")
            except aiohttp.ClientConnectorError as e:
                raise RuntimeError(f"Ollama inaccessible ({self.ollama_url}): {e}") from e

    async def call_parallel(
        self,
        calls: List[Dict],  # List of {model, messages, system?, max_tokens?}
    ) -> List[str]:
        """
        Lance plusieurs appels Ollama en parallèle.
        Retourne les réponses dans le même ordre.

        calls = [
            {"model": "qwen2.5-coder:7b", "messages": [...], "system": "..."},
            {"model": "llama3.1",          "messages": [...], "system": "..."},
        ]
        """
        tasks = [
            self.call(
                model=c["model"],
                messages=c["messages"],
                system=c.get("system"),
                max_tokens=c.get("max_tokens", 512),
            )
            for c in calls
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r if isinstance(r, str) else f"[Erreur: {r}]" for r in results]

    async def discover_models(self, tags_url: Optional[str] = None) -> List[str]:
        """Découvre les modèles Ollama disponibles."""
        if self._model_cache:
            return self._model_cache
        url = tags_url or self.ollama_url.replace("/api/chat", "/api/tags")
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    data = await resp.json()
                    models = [m["name"] for m in data.get("models", []) if "embed" not in m["name"].lower()]
                    self._model_cache = models
                    return models
        except Exception as e:
            logger.warning(f"discover_models: {e}")
            return []


# =============================================================================
# CLASSIFIEUR DE PROMPT (LLM local)
# =============================================================================


class PromptClassifier:
    """
    Classifie le prompt dans une catégorie via LLM local.
    Priorité : heuristique rapide → LLM si ambiguïté.
    """

    # Heuristiques rapides (regex + mots-clés)
    _SHELL_CMDS = frozenset(
        {
            "ls",
            "cat",
            "grep",
            "ps",
            "kill",
            "systemctl",
            "docker",
            "kubectl",
            "apt",
            "dnf",
            "yum",
            "ip",
            "ss",
            "netstat",
            "ping",
            "curl",
            "wget",
            "chmod",
            "chown",
            "rm",
            "mv",
            "cp",
            "tar",
            "sed",
            "awk",
            "find",
            "journalctl",
            "tail",
            "head",
            "df",
            "du",
            "top",
            "htop",
            "nmap",
            "ssh",
            "scp",
            "rsync",
            "git",
            "python",
            "python3",
            "bash",
        }
    )
    _SHELL_CHARS = frozenset({"|", ">", "<", "&", ";", "$", "`"})
    _CHAT_PAT = re.compile(
        r"^(quel|quelle|quand|pourquoi|comment|est.ce|qu[''']est|c[''']est|"
        r"peux.tu|pourrais|explique|raconte|dis.moi|sais.tu|connais)\b",
        re.I,
    )
    _WEB_PAT = re.compile(
        r"\b(cve-\d{4}|exploit|vuln|actualité|news|dernier|récent|"
        r"changelog|release note|2024|2025|2026)\b",
        re.I,
    )
    _LOG_PAT = re.compile(
        r"\b(log[s]?|journald?|syslog|/var/log|erreur dans|event|"
        r"grep.*log|tail.*log)\b",
        re.I,
    )
    _SECURITY_PAT = re.compile(
        r"\b(cve|pentest|audit|exploit|vulnérabilité|hardening|durcissement|"
        r"fail2ban|iptables|selinux|apparmor|firewall|ids|ips)\b",
        re.I,
    )
    _NETWORK_PAT = re.compile(
        r"\b(réseau|routage|vlan|vpn|dns|dhcp|ping|traceroute|mtu|"
        r"interface|ip route|bgp|ospf|firewall)\b",
        re.I,
    )
    _CODE_PAT = re.compile(
        r"\b(python|script|code|fonction|classe|debug|bug|erreur python|"
        r"traceback|import|asyncio|def |class |pip )\b",
        re.I,
    )
    _INFRA_PAT = re.compile(
        r"\b(docker|kubernetes|k8s|helm|terraform|ansible|ci/cd|pipeline|"
        r"déploie|deploy|cluster|pod|container|bios|gpo|active directory)\b",
        re.I,
    )

    def __init__(self, runner: OllamaParallelRunner, model: Optional[str] = None) -> None:
        """Init.

        Args:
            runner: Description.
            model: Description.
        """
        self.runner = runner
        self.model = model  # None = auto-sélectionné depuis modèles disponibles

    async def _get_model(self) -> str:
        """Get model."""
        if self.model:
            return self.model
        models = await self.runner.discover_models()
        # Préférer un modèle rapide pour la classification
        for m in models:
            ml = m.lower()
            if any(k in ml for k in ("phi4", "qwen", "llama3.1:8", "mistral", "gemma")):
                self.model = m
                return m
        self.model = models[0] if models else "llama3"
        return self.model

    def heuristic(self, text: str) -> Optional[PromptCategory]:
        """Classification heuristique rapide (< 1ms)."""
        lower = text.strip().lower()
        words = lower.split()
        first = words[0] if words else ""

        # Commande shell directe
        if first in self._SHELL_CMDS:
            return PromptCategory.TERMINAL
        if any(c in text for c in self._SHELL_CHARS):
            return PromptCategory.TERMINAL

        # Question conversationnelle sans mot-clé système
        if self._CHAT_PAT.match(lower):
            has_sys = any(
                w in words
                for w in ("log", "logs", "docker", "service", "réseau", "ssh", "ping", "top", "ps", "df", "free", "cve")
            )
            if not has_sys:
                return PromptCategory.CHAT

        # Patterns spécifiques
        if self._WEB_PAT.search(text):
            return PromptCategory.WEB
        if self._SECURITY_PAT.search(text):
            return PromptCategory.SECURITY
        if self._NETWORK_PAT.search(text):
            return PromptCategory.NETWORK
        if self._LOG_PAT.search(text):
            return PromptCategory.LOG
        if self._CODE_PAT.search(text):
            return PromptCategory.CODE
        if self._INFRA_PAT.search(text):
            return PromptCategory.INFRA

        return None  # ambiguïté → LLM

    async def classify(self, text: str) -> Tuple[PromptCategory, float]:
        """
        Retourne (catégorie, confidence).
        Utilise l'heuristique en premier, LLM si nécessaire.
        """
        # Heuristique
        cat = self.heuristic(text)
        if cat is not None:
            return cat, 0.9

        # LLM local pour les cas ambigus
        try:
            model = await self._get_model()
            prompt = (
                f"Classe ce prompt dans UNE SEULE catégorie parmi : "
                f"terminal, web, infra, code, security, network, log, chat\n"
                f'Prompt: "{text[:300]}"\n'
                f"Réponds UNIQUEMENT par le mot-clé exact, sans ponctuation ni explication."
            )
            resp = await self.runner.call(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
            )
            cat = PromptCategory.from_str(resp.strip())
            return cat, 0.75
        except Exception as e:
            logger.debug(f"LLM classify: {e}")
            return PromptCategory.CHAT, 0.5


# =============================================================================
# SCORING DES AGENTS (Ollama en parallèle)
# =============================================================================


class AgentPlanner:
    """
    Score les 12 agents pour une tâche via des appels Ollama parallèles.
    Chaque agent reçoit un score flottant [0.0–1.0].
    """

    # Prompt de scoring par agent
    _SCORE_PROMPT_TMPL = (
        "Tu es un évaluateur d'agents IA DevOps.\n"
        'Tâche demandée : "{task}"\n'
        "Rôle de l'agent à évaluer : {role}\n"
        "Donne un score de pertinence entre 0.0 et 1.0 pour cet agent sur cette tâche.\n"
        "Réponds UNIQUEMENT par un nombre flottant (ex: 0.85), sans texte ni explication."
    )

    # Prompt pour la contribution de chaque agent
    _AGENT_PROMPT_TMPL = (
        "Tu es {name}, un expert DevOps.\n"
        "Ton rôle : {role}\n\n"
        "Tâche : {task}\n"
        "{context}"
        "Réponds en français de façon technique et précise en 3-8 lignes maximum."
    )

    def __init__(self, runner: OllamaParallelRunner) -> None:
        """Init.

        Args:
            runner: Description.
        """
        self.runner = runner

    async def score_agents(
        self,
        task: str,
        models: List[str],
        agents: Optional[List[Dict]] = None,
    ) -> Dict[str, float]:
        """
        Score tous les agents en parallèle.
        Chaque agent est évalué par le modèle le plus rapide disponible.

        Retourne {agent_key: score}
        """
        agents = agents or AGENT_ROLES
        if not models:
            return {a["key"]: 0.5 for a in agents}

        # Choisir le modèle le plus rapide pour le scoring
        fast_model = self._pick_fast_model(models)

        # Préparer les appels parallèles
        calls = [
            {
                "model": fast_model,
                "messages": [
                    {"role": "user", "content": self._SCORE_PROMPT_TMPL.format(task=task[:200], role=a["role"])}
                ],
                "max_tokens": 8,
            }
            for a in agents
        ]

        responses = await self.runner.call_parallel(calls)

        scores: Dict[str, float] = {}
        for agent, resp in zip(agents, responses):
            try:
                score = float(re.search(r"\d+\.?\d*", resp).group())
                score = max(0.0, min(1.0, score))
            except Exception:
                # Fallback : score basé sur la catégorie de l'agent
                score = 0.4
            scores[agent["key"]] = score

        return scores

    async def select_agents(
        self,
        scores: Dict[str, float],
        top_n: int = 3,
        min_score: float = 0.3,
    ) -> List[Dict]:
        """
        Sélectionne les top-N agents par score.
        Filtre les agents sous min_score.
        """
        ranked = sorted(
            [(k, v) for k, v in scores.items() if v >= min_score],
            key=lambda x: x[1],
            reverse=True,
        )
        selected_keys = [k for k, _ in ranked[:top_n]]
        return [AGENT_BY_KEY[k] for k in selected_keys if k in AGENT_BY_KEY]

    async def run_agents(
        self,
        task: str,
        agents: List[Dict],
        models: List[str],
        context: str = "",
        scores: Optional[Dict[str, float]] = None,
    ) -> List[AgentContrib]:
        """
        Exécute tous les agents sélectionnés en parallèle.
        Chaque agent utilise le modèle qui lui correspond le mieux.
        """
        if not agents or not models:
            return []

        calls = []
        for agent in agents:
            model = self._pick_model_for_agent(agent["key"], models)
            ctx_str = f"\nContexte disponible :\n{context[:500]}\n\n" if context else ""
            prompt = self._AGENT_PROMPT_TMPL.format(
                name=agent["name"],
                role=agent["role"],
                task=task[:300],
                context=ctx_str,
            )
            calls.append(
                {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 400,
                    "agent": agent,
                }
            )

        # Appels parallèles
        t0 = time.monotonic()
        raw_calls = [
            {
                "model": c["model"],
                "messages": c["messages"],
                "max_tokens": c["max_tokens"],
            }
            for c in calls
        ]
        responses = await self.runner.call_parallel(raw_calls)
        elapsed = time.monotonic() - t0

        contribs: List[AgentContrib] = []
        for c, resp in zip(calls, responses):
            agent = c["agent"]
            error = resp.startswith("[Erreur:")
            contribs.append(
                AgentContrib(
                    agent_key=agent["key"],
                    agent_name=agent["name"],
                    icon=agent.get("icon", "?"),
                    response=resp if not error else "",
                    score=scores.get(agent["key"], 0.5) if scores else 0.5,
                    error=error,
                    elapsed_s=elapsed,
                )
            )
        return contribs

    def _pick_fast_model(self, models: List[str]) -> str:
        """Choisit le modèle le plus rapide pour le scoring."""
        for m in models:
            ml = m.lower()
            if any(k in ml for k in (":7b", ":8b", "phi4", "gemma", "mistral")):
                return m
        return models[0]

    def _pick_model_for_agent(self, agent_key: str, models: List[str]) -> str:
        """
        Choisit le modèle optimal pour un rôle agent spécifique.
        Logique : spécialistes code → coder, sécurité → modèles de raisonnement, etc.
        """
        if not models:
            return "llama3"

        ml = [m.lower() for m in models]

        preferences: Dict[str, List[str]] = {
            "security": ["deepseek-r1", "phi4", "llama3.3", "qwen3"],
            "compliance": ["deepseek-r1", "phi4", "llama3.3"],
            "log_analysis": ["mistral", "qwen", "llama3"],
            "network": ["mistral", "qwen", "llama3"],
            "devops": ["qwen2.5-coder", "deepseek-coder", "llama3"],
            "action_exec": ["qwen2.5-coder", "deepseek-coder", "llama3"],
            "planner": ["deepseek-r1", "qwen3", "phi4", "llama3.3"],
            "memory": ["llama3.3", "llama3.1", "qwen3"],
            "rag": ["llama3.3", "llama3.1", "mistral"],
            "monitoring": ["qwen", "llama3", "mistral"],
            "patch_mgmt": ["qwen", "llama3", "mistral"],
            "discovery": ["qwen", "llama3", "mistral"],
        }

        prefs = preferences.get(agent_key, [])
        for pref in prefs:
            for i, m in enumerate(ml):
                if pref in m:
                    return models[i]

        return models[0]  # fallback


# =============================================================================
# SYNTHÈSE MULTI-AGENTS
# =============================================================================


class AgentSynthesizer:
    """
    Synthétise les contributions de plusieurs agents en une réponse finale.
    Utilisé pour les modes collaboration et comité.
    """

    _SYNTH_PROMPT_TMPL = (
        "Tu es OctoDevOps, un assistant DevOps senior.\n"
        "Voici les contributions de {n} agents experts sur la tâche :\n"
        "Tâche : {task}\n\n"
        "{contributions}\n\n"
        "Synthétise ces contributions en une réponse claire, technique et actionnable.\n"
        "Évite les redondances. Garde les commandes concrètes si présentes.\n"
        "Réponds en français, maximum 15 lignes."
    )

    _JURY_PROMPT_TMPL = (
        "Tu es le Juge DevOps.\n"
        "Tâche : {task}\n\n"
        "Propositions de {n} experts :\n"
        "{contributions}\n\n"
        "Analyse chaque proposition et désigne la meilleure.\n"
        "Format obligatoire :\n"
        "VERDICT : [nom de l'agent]\n"
        "JUSTIFICATION : [2 phrases]\n"
        "SYNTHÈSE FINALE : [réponse complète à appliquer]"
    )

    def __init__(self, runner: OllamaParallelRunner) -> None:
        """Init.

        Args:
            runner: Description.
        """
        self.runner = runner

    async def synthesize(
        self,
        task: str,
        contribs: List[AgentContrib],
        model: str,
        mode: str = "collaboration",
    ) -> str:
        """
        Synthèse selon le mode :
          - collaboration : fusion équilibrée
          - comite        : vote + justification
        """
        valid = [c for c in contribs if not c.error and c.response]
        if not valid:
            return "Aucune contribution valide des agents."
        if len(valid) == 1:
            return valid[0].response

        contrib_text = "\n\n---\n\n".join(
            f"{c.icon} [{c.agent_name}] (score={c.score:.2f})\n{c.response}" for c in valid
        )

        if mode == "comite":
            prompt = self._JURY_PROMPT_TMPL.format(
                task=task[:200],
                n=len(valid),
                contributions=contrib_text[:3000],
            )
        else:
            prompt = self._SYNTH_PROMPT_TMPL.format(
                task=task[:200],
                n=len(valid),
                contributions=contrib_text[:3000],
            )

        try:
            return await self.runner.call(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
            )
        except Exception as e:
            logger.error(f"Synthesis error: {e}")
            return valid[0].response  # fallback : meilleur agent seul


# =============================================================================
# ROUTEUR PRINCIPAL
# =============================================================================


@dataclass
class RouteResult:
    category: PromptCategory
    confidence: float
    mode: str
    response: str
    agents_used: List[str] = field(default_factory=list)
    contribs: List[AgentContrib] = field(default_factory=list)
    web_used: bool = False
    rag_used: bool = False
    elapsed_s: float = 0.0


class SmartRouter:
    """
    Point d'entrée unique du moteur de routage.
    Orchestre : classification → web → RAG → agents → synthèse.

    Intégration Nokido :
        router = SmartRouter(
            runner     = OllamaParallelRunner(settings.ollama_url),
            classifier = PromptClassifier(runner),
            planner    = AgentPlanner(runner),
            web_engine = get_web_engine(ollama_url),
            rag_engine = rag_engine,
        )
        result = await router.route(user_input, mode=self._collab_mode)
    """

    # ── Mapping catégorie → provider préféré ────────────────────────────────
    # Détermine quel LLM est utilisé selon la nature de la tâche et le mode.
    # Peut être surchargé via SmartRouter.provider_map = {...}
    _DEFAULT_PROVIDER_MAP: dict = {
        # (PromptCategory.value, mode)  → provider
        # Règles spécifiques mode+catégorie
        ("chat", "collaboration"): "gemini",
        ("code", "collaboration"): "local",
        ("devops", "collaboration"): "gemini",
        ("security", "collaboration"): "gemini",
        ("web", "collaboration"): "gemini",
        # Règles par catégorie seule (mode=autonome ou fallback)
        ("chat", "*"): "local",
        ("code", "*"): "local",  # coder local plus rapide
        ("devops", "*"): "local",
        ("security", "*"): "gemini",  # raisonnement complexe
        ("web", "*"): "gemini",
        ("terminal", "*"): "local",
        # Défaut
        ("*", "*"): "local",
    }

    def __init__(
        self,
        runner: OllamaParallelRunner,
        classifier: PromptClassifier,
        planner: AgentPlanner,
        web_engine: object = None,  # WebSearchEngine
        rag_engine: object = None,  # RAGEngine (Nokido)
        scorer: object = None,  # ModelScorer (scoring.py)
    ):
        """Init.

        Args:
            runner: Description.
            classifier: Description.
            planner: Description.
            web_engine: Description.
            rag_engine: Description.
            scorer: Description.
        """
        from nokido_agent.app.forge_app_context import app_ctx as _actx

        _ac = _actx()
        rag_engine = _ac.rag_engine
        self.runner = runner
        self.classifier = classifier
        self.planner = planner
        self.web_engine = web_engine
        self.rag_engine = rag_engine
        self.scorer = scorer
        self.synth = AgentSynthesizer(runner)
        self._models: List[str] = []
        self.provider_map = dict(self._DEFAULT_PROVIDER_MAP)  # surchargeable
        self._gemini = None  # GeminiBridge lazy-init

    def _pick_provider(self, category: str, mode: str) -> str:
        """
        Retourne 'gemini' | 'local' selon la catégorie et le mode.
        Consulte self.provider_map, fallback sur '*'.
        Enrichi par rag_constraints : si la tâche implique sécurité/stratégie
        et que rag_constraints contient une règle explicite, elle override.
        Retourne toujours 'local' si GeminiBridge n'a pas d'api_key.
        """
        cat = category.lower()
        mod = mode.lower()

        # ── QI de routing : consulte rag_constraints si catégorie sensible ──
        if cat in ("security", "strategy", "audit", "web"):
            try:
                from nokido_agent.app.forge_rag_cache import get_rag_cache as _grc
                from nokido_agent.app.forge_npu_embedder import get_npu_embedder as _gnpu
                import numpy as _np

                _npu = _gnpu()
                if _npu and _npu.available:
                    _q = f"provider routing {cat} {mod} cloud local ring"
                    _qvec = _npu.embed_one(_q)
                    if _qvec is not None:
                        _hits = _grc().search(_np.array(_qvec, dtype=_np.float32), k=2, layer="l1")
                        for h in _hits or []:
                            txt = h.get("text", "").lower()
                            src_h = h.get("source", "")
                            if "rag_constraints" in src_h or "ring0" in txt or "cloud_no_patch" in txt:
                                if "cloud" in txt and "interdit" in txt:
                                    logger.debug(f"[_pick_provider] rag_constraints force local pour {cat}")
                                    return "local"
            except Exception:
                pass

        # ── Lookup provider_map ──────────────────────────────────────────────
        provider = (
            self.provider_map.get((cat, mod))
            or self.provider_map.get((cat, "*"))
            or self.provider_map.get(("*", "*"), "local")
        )
        # Vérifie que Gemini est disponible avant de router vers lui
        if provider == "gemini":
            try:
                if self._gemini is None:
                    from nokido_agent.app.forge_gemini_bridge import get_gemini_bridge

                    self._gemini = get_gemini_bridge()
                if not self._gemini.api_key:
                    provider = "local"  # fallback silencieux
            except Exception:
                provider = "local"
        return provider

    async def _gemini_route(
        self,
        user_input: str,
        context: str,
        mode: str,
        max_tokens: int = 800,
    ) -> str:
        """
        Route vers GeminiBridge avec contexte consolidé + system prompt Nokido.
        Utilisé par route() quand _pick_provider() retourne 'gemini'.
        """
        if self._gemini is None:
            from nokido_agent.app.forge_gemini_bridge import get_gemini_bridge

            self._gemini = get_gemini_bridge()

        # System prompt identitaire Nokido — persona canonique unifiée (AXE 8).
        try:
            from nokido_agent.app.forge_persona_engine import nokido_system

            system_identity = nokido_system(ring=3)
        except Exception:
            system_identity = (
                "Tu es un expert IA collaborant avec La Forge (assistant DevOps). "
                "Réponds en français, de façon technique et précise. "
                "Si un contexte de connaissances est fourni, utilise-le en priorité."
            )
        full_ctx = system_identity
        if context:
            full_ctx += f"\n\nContexte :\n{context[:1500]}"

        try:
            resp = await self._gemini.propose(
                task=user_input,
                rag_ctx=full_ctx,
                max_tokens=max_tokens,
            )
            return resp or ""
        except Exception as e:
            logger.warning(f"[SmartRouter/Gemini] {e}")
            return ""

    async def _ensure_models(self) -> List[str]:
        """Ensure models."""
        if not self._models:
            if self.scorer and self.scorer.is_ready:
                self._models = self.scorer.models
            else:
                self._models = await self.runner.discover_models()
        return self._models

    async def route(
        self,
        user_input: str,
        mode: str = "autonome",  # autonome / collaboration / comite
        arch: object = None,  # ArchitectureProfile
        on_role_light: object = None,  # Callable[[str], None] — allume les LEDs UI
    ) -> RouteResult:
        """
        Pipeline complet :
          1. Classifie le prompt
          2. Enrichit via web si nécessaire
          3. Enrichit via RAG
          4. Score et sélectionne les agents
          5. Exécute en parallèle
          6. Synthétise si multi-agents
        """
        t0 = time.monotonic()
        models = await self._ensure_models()
        cat, conf = await self.classifier.classify(user_input)

        logger.debug(f"Routage → {cat.value} (conf={conf:.0%}) mode={mode}")

        # ── Contexte architecture ──────────────────────────────────────────────
        arch_ctx = arch.context_hint() if arch else ""

        # ── Enrichissement Web ────────────────────────────────────────────────
        web_text = ""
        web_used = False
        if self.web_engine and (
            cat in (PromptCategory.WEB, PromptCategory.SECURITY) or self.web_engine.should_search(user_input)
        ):
            if on_role_light:
                on_role_light("discovery")
            try:
                results = await self.web_engine.search(user_input, max_results=4, fetch_content=True, rerank=True)
                if results:
                    web_text = self.web_engine.format_for_prompt(results)
                    web_used = True
                    if self.rag_engine:
                        await self.web_engine.enrich_rag(self.rag_engine, results)
            except Exception as e:
                logger.warning(f"Web search: {e}")

        # ── Enrichissement RAG — RagCache L1/L2 (0.1ms) puis engine fallback ───
        rag_text = ""
        rag_used = False
        if on_role_light:
            on_role_light("rag")
        try:
            from nokido_agent.app.forge_rag_cache import get_rag_cache as _grc
            from nokido_agent.app.forge_npu_embedder import get_npu_embedder as _gnpu
            import numpy as _np

            _npu = _gnpu()
            if _npu and _npu.available:
                _qvec = _npu.embed_one(user_input)
                if _qvec is not None:
                    _cache = _grc()
                    _cache.maybe_reload()  # sync si MCP a écrit dans la DB
                    _hits = _cache.search(_np.array(_qvec, dtype=_np.float32), k=4, layer="auto")
                    if _hits:
                        rag_text = "\n".join(
                            f"[{h.get('source', '')} {h.get('score', 0):.2f}] {h.get('text', '')[:300]}"
                            for h in _hits[:3]
                        )
                        rag_used = True
                        logger.debug(f"[SmartRouter] RagCache {len(_hits)} hits")
        except Exception as _re:
            logger.debug(f"[SmartRouter] RagCache skip: {_re}")
        if not rag_used and self.rag_engine:
            try:
                docs = await self.rag_engine.search(user_input, k=4, include_sessions=True)
                if docs:
                    rag_text = "\n".join(f"[{d.get('source', '')}] {d.get('content', '')[:300]}" for d in docs[:3])
                    rag_used = True
            except Exception as e:
                logger.debug(f"[SmartRouter] engine fallback: {e}")
        # Contexte consolidé
        context = "\n\n".join(filter(None, [arch_ctx, rag_text, web_text]))

        # ── Mode TERMINAL : pas d'agents, exécution directe ───────────────────
        if cat == PromptCategory.TERMINAL:
            if on_role_light:
                on_role_light("action_exec")
            return RouteResult(
                category=cat,
                confidence=conf,
                mode=mode,
                response="[TERMINAL]",  # signale à Nokido d'injecter dans PTY
                agents_used=["action_exec"],
                web_used=web_used,
                rag_used=rag_used,
                elapsed_s=time.monotonic() - t0,
            )

        # ── Sélection du provider (Gemini vs Ollama local) ──────────────────────
        provider = self._pick_provider(cat.value if hasattr(cat, "value") else str(cat), mode)
        logger.debug(f"[SmartRouter] provider={provider} cat={cat} mode={mode}")

        # ── Mode CHAT simple : un seul modèle ─────────────────────────────────
        if cat == PromptCategory.CHAT and mode == "autonome":
            if on_role_light:
                on_role_light("memory")
            model = self._pick_chat_model(models)
            msgs = [{"role": "user", "content": user_input}]
            sys = (
                "Tu es OctoDevOps, un assistant DevOps expert. "
                "Réponds en français, de façon concise et technique." + (f"\n\n{arch_ctx}" if arch_ctx else "")
            )
            if rag_text:
                sys += f"\n\nBase de connaissances :\n{rag_text[:800]}"
            if provider == "gemini":
                # CHAT + Gemini (mode collaboration)
                if on_role_light:
                    on_role_light("gemini")
                response = await self._gemini_route(user_input, context=context, mode=mode, max_tokens=600)
                if not response:  # fallback Ollama si Gemini vide
                    response = await self.runner.call(model=model, messages=msgs, system=sys, max_tokens=600)
            else:
                try:
                    response = await self.runner.call(model=model, messages=msgs, system=sys, max_tokens=600)
                except Exception as e:
                    response = f"Erreur : {e}"
            return RouteResult(
                category=cat,
                confidence=conf,
                mode=mode,
                response=response,
                agents_used=["gemini" if provider == "gemini" else "memory"],
                rag_used=rag_used,
                elapsed_s=time.monotonic() - t0,
            )

        # ── Scoring agents ────────────────────────────────────────────────────
        if on_role_light:
            on_role_light("planner")
        scores = await self.planner.score_agents(user_input, models)

        top_n = {"autonome": 1, "collaboration": 4, "comite": 3}.get(mode, 2)
        selected = await self.planner.select_agents(scores, top_n=top_n)

        if on_role_light:
            for a in selected:
                on_role_light(a["key"])

        # ── Exécution : Gemini OU agents Ollama selon provider ──────────────────
        if provider == "gemini" and mode in ("collaboration", "comite"):
            # Mode multi-providers : Gemini contribue + agents Ollama
            if on_role_light:
                on_role_light("gemini")
            gemini_resp = await self._gemini_route(user_input, context=context, mode=mode, max_tokens=700)
            # Exécution Ollama en parallèle
            contribs = await self.planner.run_agents(
                task=user_input,
                agents=selected,
                models=models,
                context=context,
                scores=scores,
            )
            # Injecte Gemini comme contrib supplémentaire
            if gemini_resp:
                from nokido_agent.app.forge_agents import AgentContrib

                gemini_contrib = AgentContrib(
                    key="gemini",
                    role="Expert Gemini",
                    model=getattr(self._gemini, "model", "gemini"),
                    response=gemini_resp,
                    elapsed_s=0.0,
                )
                contribs = [gemini_contrib] + list(contribs)
        else:
            # Exécution Ollama seule (provider=local)
            contribs = await self.planner.run_agents(
                task=user_input,
                agents=selected,
                models=models,
                context=context,
                scores=scores,
            )

        # ── Synthèse ─────────────────────────────────────────────────────────
        if len(contribs) == 1:
            response = contribs[0].response if not contribs[0].error else "Erreur agent."
        else:
            synth_model = self._pick_synth_model(models)
            response = await self.synth.synthesize(
                task=user_input,
                contribs=contribs,
                model=synth_model,
                mode=mode,
            )

        # ── Enrichissement RAG post-réponse ───────────────────────────────────
        if self.rag_engine:
            try:
                doc = (
                    f"[Échange {time.strftime('%H:%M:%S')}]\n"
                    f"Prompt : {user_input[:300]}\n"
                    f"Réponse : {response[:500]}\n"
                    f"Agents : {[a['key'] for a in selected]}"
                )
                await self.rag_engine.add_session_message("exchange", "system", doc)
            except Exception:
                pass

        return RouteResult(
            category=cat,
            confidence=conf,
            mode=mode,
            response=response,
            agents_used=[a["key"] for a in selected],
            contribs=contribs,
            web_used=web_used,
            rag_used=rag_used,
            elapsed_s=time.monotonic() - t0,
        )

    @staticmethod
    def _pick_model(models: List[str], prefs: Tuple[str, ...]) -> str:
        """Sélectionne le premier modèle dont le nom contient un des préfixes *prefs*."""
        for m in models:
            ml = m.lower()
            if any(k in ml for k in prefs):
                return m
        return models[0] if models else "llama3"

    def _pick_chat_model(self, models: List[str]) -> str:
        """Pick chat model.

        Args:
            models: Description.
        """
        return self._pick_model(models, ("llama3.3", "qwen3", "llama3.1", "mistral"))

    def _pick_synth_model(self, models: List[str]) -> str:
        """Pick synth model.

        Args:
            models: Description.
        """
        return self._pick_model(models, ("llama3.3", "deepseek-r1", "qwen3", "phi4"))


# =============================================================================
# SINGLETON GLOBAL (utilisé par Nokido)
# =============================================================================
_global_runner: Optional[OllamaParallelRunner] = None
_global_classifier: Optional[PromptClassifier] = None
_global_planner: Optional[AgentPlanner] = None
_global_router: Optional[SmartRouter] = None


def init_router(
    ollama_url: str = "http://localhost:11434/api/chat",
    max_concurrent: int = 4,
    web_engine: object = None,
    rag_engine: object = None,
    scorer: object = None,
) -> SmartRouter:
    """Initialise ou retourne le SmartRouter singleton."""
    from nokido_agent.app.forge_app_context import app_ctx as _actx

    _ac = _actx()
    rag_engine = _ac.rag_engine
    global _global_runner, _global_classifier, _global_planner, _global_router

    if _global_router is not None:
        return _global_router

    _global_runner = OllamaParallelRunner(ollama_url, max_concurrent=max_concurrent)
    _global_classifier = PromptClassifier(_global_runner)
    _global_planner = AgentPlanner(_global_runner)
    _global_router = SmartRouter(
        runner=_global_runner,
        classifier=_global_classifier,
        planner=_global_planner,
        web_engine=web_engine,
        rag_engine=rag_engine,
        scorer=scorer,
    )
    return _global_router


def get_router() -> Optional[SmartRouter]:
    """Get router."""
    return _global_router


__all__ = [
    # Rôles
    "AgentRole",
    "RoleOrchestrator",
    "IntentRouter",
    "ROLE_META",
    "ROLE_SYSTEM_PROMPTS",
    "OPS_ROLES",
    "CODE_ROLES",
    "ROLE_RAG_QUERIES",
    "MODEL_PROFILES",
    # Scoring
    "ModelScorer",
    "ArchitectureProfile",
    "ArchitectureDetector",
    "ScoredModel",
    "BenchResult",
    "OSFamily",
    "Distrib",
    "CPUArch",
    # Routage
    "SmartRouter",
    "OllamaParallelRunner",
    "PromptClassifier",
    "AgentPlanner",
    "AgentSynthesizer",
    "RouteResult",
    "PromptCategory",
    "AgentContrib",
    "AGENT_BY_KEY",
    "init_router",
    "get_router",
]

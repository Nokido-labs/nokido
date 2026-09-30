"""
roles.py — Rôles IA DevOps complets v2
=======================================
Fork OctoDevOps v5

Rôles d'amélioration de code (loops.py) :
  ANALYSTE    — structure, patterns, risques architecturaux
  DEBUGGER    — correction chirurgicale bugs
  COMPARATEUR — évaluation deux versions
  STRATEGE    — refactoring, architecture
  JUGE        — verdict final arbitrage

Rôles DevOps opérationnels :
  PLANNER         — planification, décomposition de tâches
  DISCOVERY       — inventaire, cartographie infra
  DEVOPS          — CI/CD, déploiements, pipelines
  NETWORK         — réseaux, routage, firewall
  SECURITY        — pentest, durcissement, CVE
  LOG_ANALYSIS    — parsing logs, corrélation événements
  RAG_KNOWLEDGE   — base de connaissances, documentation
  ACTION_EXEC     — exécution commandes, orchestration
  MEMORY          — contexte long terme, historique

Rôles optionnels :
  MONITORING      — métriques, alertes, SLA
  PATCH_MGMT      — correctifs, mises à jour
  COMPLIANCE      — audit conformité, CIS/NIST
  INCIDENT        — réponse incidents, triage
  CONFIG_BACKUP   — sauvegarde, restauration configs
  THREAT_INTEL    — renseignement menaces, IOC

Rôles infrastructure :
  ACTIVE_DIR      — Active Directory, GPO, LDAP
  WINDOWS_MGMT    — administration Windows, PowerShell
  LINUX_MGMT      — administration Linux, systemd
  NETWORK_DEVICE  — switches, routeurs, VLANs
  DNS_PIHOLE      — DNS, Pi-hole, filtrage
  IDS_ZEEK        — IDS, Zeek, analyse réseau
"""

import asyncio
import aiohttp
import json
import logging
import time
import re
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


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
    # ── Modèles cloud haute capacité ────────────────────────────────────────────
    "gpt-oss:120b": {
        # GPT-OSS 120B cloud : polyvalent haut niveau, excellent raisonnement
        AgentRole.STRATEGE: 9.5,
        AgentRole.ANALYSTE: 9.5,
        AgentRole.JUGE: 9.5,
        AgentRole.DEBUGGER: 9.0,
        AgentRole.COMPARATEUR: 9.0,
        AgentRole.PLANNER: 9.5,
        AgentRole.SECURITY: 9.0,
        AgentRole.COMPLIANCE: 9.0,
        AgentRole.RAG_KNOWLEDGE: 9.0,
        AgentRole.MEMORY: 9.0,
        AgentRole.LOG_ANALYSIS: 8.5,
        AgentRole.DEVOPS: 8.5,
        AgentRole.NETWORK: 8.5,
        AgentRole.ACTION_EXEC: 8.0,
        "speed": 4,
        "note": "120B cloud, généraliste haut de gamme",
    },
    "deepseek-v3": {
        # DeepSeek V3 671B cloud : raisonnement frontier, coding++
        AgentRole.ANALYSTE: 9.8,
        AgentRole.DEBUGGER: 9.8,
        AgentRole.STRATEGE: 9.5,
        AgentRole.JUGE: 9.5,
        AgentRole.COMPARATEUR: 9.5,
        AgentRole.PLANNER: 9.5,
        AgentRole.SECURITY: 9.0,
        AgentRole.DEVOPS: 9.0,
        AgentRole.ACTION_EXEC: 8.5,
        AgentRole.RAG_KNOWLEDGE: 9.0,
        AgentRole.MEMORY: 9.0,
        AgentRole.LINUX_MGMT: 8.5,
        "speed": 3,
        "note": "DeepSeek V3 671B, frontier code+reasoning",
    },
    "deepseek-v3.1": {
        # Alias pour deepseek-v3.1:671b-cloud
        AgentRole.ANALYSTE: 9.8,
        AgentRole.DEBUGGER: 9.8,
        AgentRole.STRATEGE: 9.5,
        AgentRole.JUGE: 9.5,
        AgentRole.COMPARATEUR: 9.5,
        AgentRole.PLANNER: 9.5,
        AgentRole.SECURITY: 9.0,
        AgentRole.DEVOPS: 9.0,
        AgentRole.ACTION_EXEC: 8.5,
        AgentRole.RAG_KNOWLEDGE: 9.0,
        AgentRole.MEMORY: 9.0,
        AgentRole.LINUX_MGMT: 8.5,
        "speed": 3,
        "note": "DeepSeek V3.1 671B cloud",
    },
    "qwen3-coder": {
        # Qwen3-Coder 480B cloud : spécialiste code++, agentic
        AgentRole.DEBUGGER: 9.8,
        AgentRole.ANALYSTE: 9.5,
        AgentRole.COMPARATEUR: 9.5,
        AgentRole.STRATEGE: 9.0,
        AgentRole.JUGE: 9.0,
        AgentRole.ACTION_EXEC: 9.0,
        AgentRole.DEVOPS: 9.0,
        AgentRole.LINUX_MGMT: 8.5,
        AgentRole.SECURITY: 8.5,
        AgentRole.PLANNER: 8.5,
        "speed": 3,
        "note": "Qwen3-Coder 480B, SOTA agentic coding",
    },
    # ── Spécialistes code (modèles locaux) ───────────────────────────────────
    "deepseek-coder:6.7b": {
        AgentRole.DEBUGGER: 8.5,
        AgentRole.ANALYSTE: 7.5,
        AgentRole.COMPARATEUR: 7.5,
        AgentRole.ACTION_EXEC: 7.5,
        AgentRole.DEVOPS: 7.0,
        AgentRole.LINUX_MGMT: 6.5,
        "speed": 9,
        "note": "DeepSeek Coder 6.7B, bon rapport perf/vitesse",
    },
    "deepseek-coder": {
        AgentRole.DEBUGGER: 8.0,
        AgentRole.ANALYSTE: 7.0,
        AgentRole.COMPARATEUR: 7.0,
        AgentRole.ACTION_EXEC: 7.0,
        AgentRole.DEVOPS: 6.5,
        "speed": 9,
    },
    "starcoder2:15b": {
        # StarCoder2 15B : spécialiste complétion code, 600+ langages
        AgentRole.DEBUGGER: 8.0,
        AgentRole.ANALYSTE: 7.5,
        AgentRole.COMPARATEUR: 7.0,
        AgentRole.ACTION_EXEC: 6.5,
        AgentRole.DEVOPS: 6.5,
        "speed": 7,
        "note": "StarCoder2 15B, complétion code multi-langages",
    },
    "starcoder2": {
        AgentRole.DEBUGGER: 7.5,
        AgentRole.ANALYSTE: 7.0,
        AgentRole.COMPARATEUR: 6.5,
        AgentRole.ACTION_EXEC: 6.0,
        "speed": 8,
    },
    # ── Modèles légers / rapides ─────────────────────────────────────────────
    "qwen2:7b": {
        # Qwen2 7B : polyvalent, bon contexte 128k, multilingue
        AgentRole.STRATEGE: 7.5,
        AgentRole.ANALYSTE: 7.5,
        AgentRole.JUGE: 7.5,
        AgentRole.DEBUGGER: 7.0,
        AgentRole.RAG_KNOWLEDGE: 7.5,
        AgentRole.MEMORY: 7.5,
        AgentRole.LOG_ANALYSIS: 7.0,
        AgentRole.DEVOPS: 6.5,
        "speed": 9,
        "note": "Qwen2 7B, multilingue, contexte 128k",
    },
    "qwen2": {
        AgentRole.STRATEGE: 7.0,
        AgentRole.ANALYSTE: 7.0,
        AgentRole.JUGE: 7.0,
        AgentRole.RAG_KNOWLEDGE: 7.0,
        AgentRole.MEMORY: 7.0,
        "speed": 9,
    },
    "glm-4": {
        # GLM-4 Flash : modèle chinois multilingue rapide, bon dialogue FR
        AgentRole.STRATEGE: 7.5,
        AgentRole.ANALYSTE: 7.5,
        AgentRole.JUGE: 7.0,
        AgentRole.COMPARATEUR: 7.0,
        AgentRole.RAG_KNOWLEDGE: 7.5,
        AgentRole.MEMORY: 7.5,
        AgentRole.LOG_ANALYSIS: 7.0,
        "speed": 9,
        "note": "GLM-4 Flash, excellent multilingue FR/ZH",
    },
    "tinyllama": {
        # TinyLlama 1.1B : ultra-rapide, classif simple, suggestions
        AgentRole.ACTION_EXEC: 5.5,
        AgentRole.RAG_KNOWLEDGE: 5.0,
        AgentRole.DEVOPS: 5.0,
        "speed": 10,
        "note": "TinyLlama 1.1B, ultra-rapide, tâches simples",
    },
    "erukude/multiagent-orchestrator": {
        # Multiagent orchestrator 1B : routing/dispatch uniquement
        AgentRole.PLANNER: 7.0,
        AgentRole.DISCOVERY: 7.0,
        AgentRole.ACTION_EXEC: 5.0,
        "speed": 10,
        "note": "1B spécialisé orchestration multi-agents",
    },
    # ── Embeddings (exclus du scoring génération) ─────────────────────────────
    "bge-m3": {
        # BGE-M3 : embeddings uniquement, NE PAS utiliser pour génération
        AgentRole.RAG_KNOWLEDGE: 0.0,  # signal d'exclusion
        "speed": 10,
        "note": "Embeddings uniquement — pas de génération",
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

    def __init__(self, ollama_url: str):
        self.ollama_url = ollama_url
        self._cache: Dict[str, ModelBenchmark] = {}

    async def benchmark(self, model: str) -> ModelBenchmark:
        if model in self._cache:
            return self._cache[model]

        bench = ModelBenchmark(model=model)
        try:
            t_start = time.perf_counter()
            first_token_time = None
            tokens = 0
            full = []

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.ollama_url,
                    json={"model": model, "messages": [{"role": "user", "content": self.BENCH_PROMPT}], "stream": True},
                    timeout=aiohttp.ClientTimeout(total=30, connect=5),
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

    def __init__(self, ollama_url: str, ollama_tags_url: str):
        self.ollama_url = ollama_url
        self.ollama_tags_url = ollama_tags_url
        self.benchmarker = ModelBenchmarker(ollama_url)
        self.router = IntentRouter()
        self._available: List[str] = []
        self._assignments: Dict[AgentRole, str] = {}
        self._benchmarks: Dict[str, ModelBenchmark] = {}

    # ── Découverte ─────────────────────────────────────────────────────────────
    async def discover_models(self) -> List[str]:
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
    async def run_benchmarks(self, log_fn=None) -> Dict[str, ModelBenchmark]:
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
                if log_fn and result.available:
                    log_fn(
                        f"  {model:30} "
                        f"{result.tokens_per_second:5.1f} tok/s  "
                        f"qualité={result.quality_score:.1f}/10  "
                        f"lat={result.first_token_latency_ms:.0f}ms"
                    )
        return self._benchmarks

    # ── Clé de profil ──────────────────────────────────────────────────────────
    def _profile_key(self, model: str) -> str:
        ml = model.lower()
        for key in sorted(MODEL_PROFILES.keys(), key=len, reverse=True):
            if key == "__default__":
                continue
            if ml.startswith(key) or key in ml:
                return key
        return "__default__"

    # ── Score final ────────────────────────────────────────────────────────────
    def _score(self, model: str, role: AgentRole) -> RoleAssignment:
        profile = MODEL_PROFILES.get(self._profile_key(model), MODEL_PROFILES["__default__"])
        static_score = profile.get(role, 6.0)
        bench = self._benchmarks.get(model)
        dynamic_score = 0.0
        if bench and bench.available:
            speed_score = min(10.0, bench.tokens_per_second / 8.0)
            dynamic_score = bench.quality_score * 0.6 + speed_score * 0.4
        final = static_score * 0.7 + dynamic_score * 0.3
        return RoleAssignment(
            role=role,
            model=model,
            static_score=static_score,
            dynamic_score=dynamic_score,
            final_score=final,
        )

    # ── Attribution générique ──────────────────────────────────────────────────
    def _greedy_assign(self, roles: List[AgentRole], log_fn=None) -> Dict[AgentRole, str]:
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
        log_fn=None,
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
        log_fn=None,
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
        log_fn=None,
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
        return list(self._available)

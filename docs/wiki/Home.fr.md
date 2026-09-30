---
type: guide
title: Wiki Nokido
status: draft
resource: repo://docs/wiki/Home.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# Wiki Nokido

<!-- revu-le: 2026-08-14 -->
> Mise à jour : 2026-08-14

> 🌐 [English](Home.md) · **Français**

Bienvenue sur le wiki **Nokido**. Nokido est un système d'exploitation IA
autonome, local-first, avec gouvernance neuro-symbolique.

Ce wiki est le **manuel opérateur** — installation, configuration, workflows
quotidiens, troubleshooting. Pour le *pourquoi* derrière la conception,
lire [MANIFESTO.md](../../MANIFESTO.md). Pour les internals techniques,
lire [docs/ARCHITECTURE.md](../ARCHITECTURE.md).

---

## 🗺️ Table des matières

### Démarrage
- [01 — Installation](01-Installation.fr.md) · Docker, natif, extras pip
- [17 — Premier lancement](17-First-Launch.fr.md) · Walkthrough 10 étapes avec l'UI web admin
- [02 — Démarrage rapide](02-Quick-Start.fr.md) · Premier appel, workflows courants
- [03 — Aperçu architecture](03-Architecture.fr.md) · Anatomie du hub

### Connecter les clients
- [04 — Configuration clients MCP](04-MCP-Clients-Setup.fr.md) · Claude Desktop, Claude Code, Gemini CLI, Codex CLI, Cline
- [24 — Pairs cloud](24-Cloud-Peers.fr.md) · claude.ai et ChatGPT en HTTPS, quarantaine owner
- [05 — Providers LLM](05-LLM-Providers.fr.md) · 29 providers, UI admin web

### Opération
- [06 — Référence API hub](06-Hub-API-Reference.fr.md) · 25 tools MCP
- [07 — Modèle de sécurité](07-Security-Model.fr.md) · Couches Zero-Trust
- [08 — Vault & secrets](08-Vault-and-Secrets.fr.md) · DPAPI, Keychain, libsecret
- [09 — Référence TUI](09-TUI-Reference.fr.md) · Panes, raccourcis
- [10 — Profils Docker](10-Docker-Profiles.fr.md) · core, hub, full, all, dev
- [11 — Notes multi-OS](11-Cross-OS-Notes.fr.md) · Windows vs Linux vs macOS

### Approfondir
- [12 — Pile cognitive AMI](12-AMI-Cognitive-Stack.fr.md) · LeCun, Friston, Hasani
- [13 — Roadmap matérielle](13-Hardware-Roadmap.fr.md) · NPU, neuromorphique, analogique, photonique
- [18 — Lanceurs & fichiers services](18-Launchers.fr.md) · `.bat`, NSSM, systemd, plist
- [19 — Knowledge Pack](19-Knowledge-Pack.fr.md) · Pack optionnel pré-vectorisé code Nokido (5-10 MB)
- [20 — Référence des modules](20-Modules-Reference.fr.md) · Chaque module, défini par sa propre docstring, groupé par organe (généré)
- [23 — Orchestration & workflows](23-Orchestration-and-Workflows.fr.md) · GOAP, boucle d'événements, exécution durable (Temporal / Mistral)
- [21 — SSoT Cross-CLI](21-SSoT-Cross-CLI.fr.md) · source unique de vérité, « point sur X » uniforme entre les CLI, 5 domaines
- [22 — Gouvernance, cognition & auto-sûreté](22-Governance-Cognition-Safety.fr.md) · intégrité de livraison, soif de connaissance, garde held-out, RAG pondéré par l'autorité, sync Qdrant continue

### Aide
- [14 — Troubleshooting](14-Troubleshooting.fr.md)
- [15 — Glossaire](15-Glossary.fr.md)
- [16 — FAQ](16-FAQ.fr.md)

---

## 📍 Liens rapides

| Ressource | URL |
|---|---|
| Hub (local) | <http://127.0.0.1:8766> |
| UI admin providers | <http://127.0.0.1:8766/admin/providers> |
| Dashboard RBAC | <http://127.0.0.1:7400/rbac> |
| Endpoint health | <http://127.0.0.1:8766/health> |
| Endpoint MCP | <http://127.0.0.1:8766/mcp> |
| Repo | <https://github.com/user/Nokido> |
| Contact sécurité | onglet *Security* → *Report a vulnerability* |

---

*Ce wiki suit les branches `alpha` et `beta`. La release publique reflète `main`.
Sections marquées **alpha-only** peuvent évoluer.*

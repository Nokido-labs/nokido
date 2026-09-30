# netcfg-agent — Inspirations & Roadmap vs awesome-network-automation

**Source** : https://github.com/networktocode/awesome-network-automation (108 outils, 13 catégories)
**Date** : 2026-04-23
**Statut netcfg-agent actuel** : v0.1.3 — 5 vendors (Huawei VRP, HPE Comware, HP ProCurve, Aruba AOS-CX, Netgear ProSafe), 9 MCP tools, parsing VSDX + running-config, WAL hash-chain SHA-256, PTY asyncssh, demo 15 switches.

---

## 🎯 Concurrents / inspirations directs

### Tier 1 — Overlap fonctionnel direct

| Projet | URL | Rôle | Ce qu'on peut reprendre |
|---|---|---|---|
| **Hierarchical Configuration** | github.com/netdevops/hier_config | Compare running vs intended, génère plan de remédiation | **Exactement ce que netcfg fait mais en lib Python** — comparer l'approche pour le diff engine |
| **Batfish** | github.com/batfish/batfish | Multi-vendor config parser + simulation (routing, forwarding, security) | Validation réseau à un niveau au-dessus (ACL/forwarding analysis) — pas notre scope court terme mais référence |
| **NAPALM** | github.com/napalm-automation/napalm | Vendor abstraction layer Python (unified API cross-vendor) | **Architecture à étudier** pour v2 : get_config, get_interfaces_counters, get_arp_table unifiés |
| **Nornir** | github.com/nornir-automation/nornir | Framework automation Python pur (remplace Ansible pour lib code) | Pattern d'exécution parallèle cross-device avec inventaire |

### Tier 2 — Outils de parsing / normalisation

| Projet | URL | Note |
|---|---|---|
| **ciscoconfparse** | github.com/mpenning/ciscoconfparse | Parsing Cisco IOS hierarchy — utile pour vendor Cisco futur |
| **NTC Templates / TextFSM** | github.com/networktocode/ntc-templates | Templates TextFSM multi-vendor pour parser `show` outputs → structured data |
| **TTP (Template Text Parser)** | github.com/dmulyalin/ttp | Alternative à TextFSM, syntaxe Jinja-like |
| **Cisco Genie Parsers** | pubhub.devnetcloud.com/media/genie-feature-browser | Parsers Cisco Genie/pyATS |
| **NetCopa** | github.com/cidrblock/netcopa | Config → YAML "industry standard" |

### Tier 3 — Visualisation / diagrams

| Projet | URL | Note |
|---|---|---|
| **D2** | d2lang.com | DSL diagrams simple + beau rendu — alternative à graphviz pour `/api/topology` |
| **Drawthe.net** | github.com/cidrblock/drawthe.net | Network diagrams from YAML — concurrence directe avec notre VSDX parser |
| **Topolograph** | github.com/Vadims06/topolograph | OSPF/IS-IS topology viz + failure prediction |
| **inet-henge** | github.com/codeout/inet-henge | D3.js diagrams from JSON |
| **Need To Graph** | — | GraphML / drawio / JSON output — utile pour exports multiples |

### Tier 4 — Sécurité / anonymisation

| Projet | Note |
|---|---|
| **netconan** | Config anonymizer — déjà dans l'idée de Nokido NoiseGuardian mais spécialisé réseau. À étudier pour enrichir la demo privée. |
| **Aerleon / Capirca** | ACL generation multi-platform YAML — scope adjacent, pas dans netcfg core mais bon pour une extension "firewall rules" |

### Tier 5 — Observability / telemetry

| Stack | Note |
|---|---|
| **Prometheus + Grafana + Telegraf + InfluxDB** | Stack standard pour metrics — netcfg pourrait exposer des metrics via `/metrics` endpoint Prometheus |
| **SuzieQ** | Network observability platform en Python — concurrent pour la partie dashboard/analytics |
| **napalm-logs** | Syslog normalizer cross-vendor → OpenConfig YANG — utile si on veut ingérer des logs live |

### Tier 6 — Protocoles

| Projet | Note |
|---|---|
| **gNMIc / PyGNMI** | gNMI client — alternative moderne à SSH pour les vendors qui supportent (Arista, Cisco récent) |
| **RESTCONF / NETCONF** | Standards IETF — pour les vendors qui exposent l'API (hors Netgear ProSafe…) |
| **OpenConfig YANG** | Standards data models cross-vendor |

---

## 📋 Roadmap proposée pour netcfg-agent (inspirée)

### Phase 1 — court terme (semaines, features "marketing" de la v2)

**P1.1 Parsing enrichi** — intégrer TextFSM + NTC Templates pour parser `show` outputs structurés

- Raison : au lieu de parser manuellement du VRP/Comware dans `core.py`, utiliser NTC Templates existants + ajouter nos 5 vendors si manquants
- Effort : 2-3 jours
- Bénéfice : parsers battle-tested, contribuabilité upstream
- Fichier cible : `netcfg-agent/netcfg/core.py::VendorTemplate` → ajouter un adapter TextFSM

**P1.2 Export topology vers D2 / Drawthe.net YAML** — en plus du rendu web actuel

- Raison : interopérabilité avec des workflows DocOps
- Effort : 1-2 jours
- Endpoint : `GET /api/topology.d2`, `GET /api/topology.drawthe.yml`
- Bénéfice immédiat pour la démo : "topologie auto-diagrammée dans 3 formats"

**P1.3 Export Prometheus metrics** — `/metrics` endpoint

- Raison : intégration avec stacks observability existantes (très demandé en entreprise)
- Effort : 1 jour (lib `prometheus_client` Python)
- Metrics exposées : `netcfg_drift_count{severity}`, `netcfg_audit_events_total`, `netcfg_trunks_total`, `netcfg_switches_reachable`
- Fichier cible : nouveau `netcfg/metrics.py`, mount via FastAPI

### Phase 2 — moyen terme (1-2 mois)

**P2.1 gNMI support pour les vendors compatibles** — Arista, Cisco récent

- Raison : gNMI est l'avenir (streaming telemetry, pas polling SSH)
- Effort : 3-5 jours (intégrer `pygnmi`)
- Impact : supporte Arista EOS sans SSH/CLI parsing

**P2.2 Comparison engine "hier_config style"** — hierarchy-aware diff

- Raison : notre diff actuel est line-based, `hier_config` gère les blocs nested (interface / vlan 10 / trunk…)
- Effort : 5-7 jours ou intégrer la lib directement
- Gain : diff plus sémantique, ops de remédiation plus propres

**P2.3 NAPALM-compatible wrapper** — exposer un adapter NAPALM pour nos 5 vendors

- Raison : nos 5 vendors (ProCurve, ProSafe, Comware) ne sont pas dans NAPALM mainline
- Effort : 2-3 semaines (contribuer upstream)
- Impact : quiconque utilise NAPALM pour automation peut maintenant piloter ces devices via netcfg-agent

### Phase 3 — long terme (3-6 mois)

**P3.1 Batfish integration** — upload VSDX + running-configs à Batfish, récupérer findings

- Rôle : Batfish fait l'analyse cross-device (forwarding tables, reachability, ACL overlap)
- netcfg orchestrerait : parse Visio → normalise → envoie à Batfish → affiche findings dans notre UI
- Différenciation : notre plus-value = la couche Visio-as-source-of-truth + multi-vendor Huawei/HP/Aruba, Batfish apporte l'intelligence analytique

**P3.2 Nornir-style parallel execution** — refactor du run() pour exécuter en parallèle sur tout le parc

- Actuellement : `netcfg preview <visio>` est single-threaded
- Après : préview 15 switches en parallèle via Nornir ou notre propre Future-based executor

**P3.3 Zero-Touch Provisioning (FreeZTP inspiration)**

- Pour les switches neufs : netcfg pousse la config initiale via console/DHCP options 66/67
- Scope étendu : "déploiement lifecycle complet" et pas juste "audit + remediation"

---

## 🚫 À ne **PAS** faire

| Ce qu'on pourrait être tenté | Pourquoi non |
|---|---|
| Abandonner le parsing VSDX au profit d'un "source of truth" type Nautobot / Infrahub | C'est **notre différenciant** — Visio est ce que 90% des admins réseau utilisent déjà. Ne pas les forcer à migrer. |
| Intégrer un LLM pour générer les configs | Scope inflation. Laisser ça à Nokido via MCP bridge. netcfg reste déterministe. |
| Implémenter tout NAPALM en interne | 30+ vendors, 50+ operations. On se fait écraser. Rester sur nos 5 vendors où on fait mieux. |
| Supporter Cisco IOS/NX-OS/IOS-XE | Trop concurrencé (ciscoconfparse, pyATS, NAPALM). Se concentrer sur HP/Aruba/Huawei/Netgear qui sont mal servis. |
| Remplacer SSH par NETCONF/RESTCONF partout | Huawei VRP, HP Comware basic, Netgear ProSafe ne supportent pas. SSH reste le lowest common denominator. |

---

## 📝 Pitch révisé pour la démo

**Ancien pitch** : "Visio + running-config → audit + remediation multi-vendor"

**Nouveau pitch informé par la concurrence** :

> netcfg-agent = **la couche Visio-as-code pour les 5 vendors mal servis par NAPALM/Batfish**.
>
> Pendant que NAPALM et Batfish se concentrent sur Cisco/Juniper/Arista, netcfg-agent apporte :
> - Parsing VSDX natif (les admins réseau ont tous Visio)
> - 5 vendors spécifiquement sous-couverts (Huawei VRP, HPE Comware, HP ProCurve, Aruba AOS-CX, Netgear ProSafe)
> - Audit cryptographique (WAL hash-chain SHA-256) pour la conformité
> - MCP server pour l'intégration directe avec les agents IA
>
> Pas une n-ième réimplémentation de NAPALM. Un **complément** qui s'intègre avec Prometheus/Grafana pour l'observability, s'exporte en D2/drawthe.net pour la documentation, et cède le gNMI/NETCONF à ceux qui le font mieux.

---

## Références JSON

- `sandbox/awesome-network-automation.md` — README complet du repo (59 KB)
- `sandbox/awesome-netauto-parsed.json` — 108 outils parsés, 13 sections
- `netcfg-agent/docs/FEATURES.md` — features existantes netcfg v0.1.3
- `netcfg-agent-mcp/CHANGELOG.md` — historique MCP fork

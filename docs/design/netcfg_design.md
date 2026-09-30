# Couche C — Network Config Agent (netcfg)

**Statut** : design figé, non implémenté
**Date** : 2026-04-21
**Auteur** : Claude Opus 4.7 (session agent réseau)
**Scope** : agent de déploiement de configuration sur équipements réseau gérés par l'utilisateur, piloté par Visio + KeePass + inventaire recon_silo.

---

## §1 — Contexte & rupture de pattern

Nokido comporte à date deux couches **passives** : Couche A (CTF Reports, importeur read-only de sessions CAI) et Couche B (GAIA, archivage read-only de bundles d'agents). Aucune ne modifie un système externe.

La **Couche C** rompt ce pattern : elle pousse des commandes de configuration sur des équipements réseau actifs (switches d'entreprise gérés par l'utilisateur). C'est la première couche active de Nokido.

La rupture est acceptée pour un périmètre strictement borné :
- Cibles = switches dont l'utilisateur est administrateur légitime
- Credentials = issus de son coffre KeePass, jamais stockés par l'agent
- Intent = issu d'un fichier Visio produit par l'utilisateur (son livrable de documentation)
- Aucune action destructive sans triple validation manuelle
- Aucune découverte ou enrôlement automatique d'équipements non listés dans le recon

---

## §2 — Threat model

| Risque | Origine | Mitigation |
|---|---|---|
| Push de config erronée = coupure réseau | Bug traducteur YAML / Visio mal parsé | Dry-run par défaut, diff review manuel, `commit confirm-timer` natif Huawei / rollback timer pour les autres, backup pré-push obligatoire |
| Injection de commande via Visio corrompu | Fichier Visio modifié (tiers malveillant ou corruption) | Validation stricte du parser (whitelist d'attributs, rejet XML suspects), regex sur chaque commande générée avant envoi |
| Fuite du master password KeePass | Agent le capture ou le log | Master password jamais transmis à l'agent : prompt direct via la lib `pykeepass` en mémoire volatile, destruction immédiate après extraction des creds de la cible |
| Push accidentel hors cible | Mauvaise résolution hostname → IP | Target explicite par IP de management, vérification double (hostname Visio ↔ IP résolue ↔ banner SSH post-connexion) |
| Exécution de commande destructive | Bug traducteur, template corrompu | Blacklist par vendor dans le YAML, refus même avec validation utilisateur (fail-closed), liste noire globale hardcodée en plus |
| Deuxième opérateur pousse pendant qu'on audit | Concurrence | Lock exclusif par équipement (fichier `.lock` sur disque + entry `deploy_lock` en DB avec TTL 15 min) |
| Rollback échoué après perte de connectivité | Push a coupé notre propre lien | `confirm-timer 120s` côté Huawei (nécessite un `commit` avant expiration), vérification de reachability post-push, alerte si perte et timer restant < 30s |
| Audit trail effaçable | Log manipulé | Entries `deploy_log` append-only, hash chaîné sur chaque ligne (hash_prev + content → hash_current), vérifiable a posteriori |

---

## §3 — Architecture (arborescence figée)

```
app/netcfg/
├── __init__.py
├── core.py            ~400 L    Equipment, Workflow, Safety, Gates, VendorDetector
├── visio.py           ~150 L    Parser .vsdx minimal (unzip + lxml)
├── views.py           ~100 L    4 endpoints FastAPI sous /netcfg/*
├── static/                      UI fluide (§13)
│   ├── netcfg_workflow.html     Single-page app (réutilise shell forge_graph_explorer)
│   ├── netcfg_workflow.js       ~300 L  Cytoscape + SSE + keyboard shortcuts
│   └── netcfg_workflow.css      ~100 L  Palette états, animations, layout split
└── templates/                   Grammaires vendor (extensible SANS code)
    ├── _generic.yml             Fallback Netmiko générique
    ├── _schema.json             JSON Schema qui valide tout template
    ├── huawei_vrp.yml
    ├── hp_comware.yml           (ex-H3C, datacenter/core)
    ├── hp_procurve.yml          (ArubaOS-Switch legacy edge)
    ├── aruba_aoscx.yml          (Aruba moderne)
    └── netgear_prosafe.yml

recon_silo/recon_data/recon.db   EXTENDED avec 3 tables (§4)

sandbox/
└── netcfg_design.md             ce fichier (design figé)
```

**Total code Python estimé** : ~650 lignes sur 3 fichiers.
**Total JS/CSS/HTML** : ~400 lignes sur 3 fichiers pour l'UI workflow.
**Total YAML** : 6 fichiers (~40-80 L chacun).
**Nouvelles dépendances** : `netmiko>=4.3`, `pykeepass>=4.1`, `lxml>=5.0`, `jinja2` (déjà présent). Cytoscape.js déjà servi par le hub.

---

## §4 — Schéma DB (extensions de `recon.db`)

Pas de nouvelle base. Ajout de 3 tables à `recon_silo/recon_data/recon.db`, toutes préfixées `netcfg_` pour éviter la collision avec les tables recon existantes.

```sql
-- Inventaire enrichi : identifie quels hôtes recon sont des switches gérés
CREATE TABLE netcfg_equipment (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ip_mgmt         TEXT NOT NULL UNIQUE,
    hostname        TEXT NOT NULL,
    vendor_key      TEXT NOT NULL,       -- match templates/*.yml (ex: 'huawei_vrp')
    model           TEXT,
    os_version      TEXT,
    location        TEXT,
    visio_shape_id  TEXT,                -- lien vers shape Visio source
    keepass_entry   TEXT,                -- chemin dans le kdbx (ex: 'Network/Core/SW-CORE-01')
    first_seen      TEXT NOT NULL,       -- ISO-8601
    last_verified   TEXT NOT NULL,
    status          TEXT DEFAULT 'active'  -- active|maintenance|decommissioned
);

-- Backups des configs avant push (audit trail)
CREATE TABLE netcfg_config_backup (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id    INTEGER NOT NULL REFERENCES netcfg_equipment(id),
    taken_at        TEXT NOT NULL,
    config_type     TEXT NOT NULL,       -- 'running'|'startup'
    config_text     TEXT NOT NULL,       -- config intégrale
    sha256          TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    triggered_by    TEXT NOT NULL        -- user|scheduled|pre-push
);

-- Log append-only de chaque déploiement (hash chaîné pour intégrité)
CREATE TABLE netcfg_deploy_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,       -- UUID d'un déploiement (groupe de lignes)
    equipment_id    INTEGER NOT NULL REFERENCES netcfg_equipment(id),
    step_index      INTEGER NOT NULL,    -- ordre dans le workflow
    gate            TEXT NOT NULL,       -- 'plan'|'diff_review'|'cmd_review'|'push'|'post_push'|'save'
    operator        TEXT NOT NULL,       -- user JWT sub
    commands        TEXT,                -- commandes envoyées (NULL si dry-run)
    stdout          TEXT,
    stderr          TEXT,
    dry_run         INTEGER NOT NULL,    -- 0|1
    validated       INTEGER NOT NULL,    -- 0|1 (gate approuvée par user)
    ts              TEXT NOT NULL,
    hash_prev       TEXT,                -- hash de la ligne précédente (même run_id)
    hash_current    TEXT NOT NULL        -- sha256(hash_prev + commands + stdout + ts)
);

CREATE INDEX idx_deploy_log_run ON netcfg_deploy_log(run_id, step_index);
CREATE INDEX idx_equipment_mgmt ON netcfg_equipment(ip_mgmt);
```

---

## §5 — Format des templates vendor (grammaire YAML)

Tout template doit valider contre `templates/_schema.json`. Structure obligatoire :

```yaml
vendor: huawei_vrp                       # clé unique, sert de vendor_key en DB
netmiko_device_type: huawei              # passé à Netmiko.ConnectHandler
display_name: "Huawei VRP (S-series, CE-series)"

# Détection automatique
detection:
  ssh_banner_match:                      # regex OR, matché sur banner SSH
    - "Huawei"
    - "VRP"
  snmp_sysobjectid_prefix:               # optionnel, si SNMP dispo
    - "1.3.6.1.4.1.2011"

# Commandes de base (clés fixes imposées par le schema)
commands:
  show_running:      "display current-configuration"
  show_version:      "display version"
  backup_startup:    "display saved-configuration"
  enter_config:      "system-view"
  exit_config:       "return"
  save_config:       "save"
  commit_confirm:    "commit confirm-timer {timeout}"    # {timeout} substitué
  commit:            "commit"
  rollback:          "rollback configuration to previous"

# Opérations de haut niveau (templates Jinja2)
operations:
  add_vlan:
    template: |
      vlan {{ vlan_id }}
       description {{ description }}
    params: [vlan_id, description]
    validate_regex:
      - "^vlan \\d+$"
      - "^ description .+$"

  set_access_port:
    template: |
      interface {{ interface }}
       port link-type access
       port default vlan {{ vlan_id }}
    params: [interface, vlan_id]
    validate_regex:
      - "^interface .+$"
      - "^ port link-type access$"
      - "^ port default vlan \\d+$"

# Liste noire locale au vendor — refus FAIL-CLOSED
destructive_blacklist:
  - "^reset saved-configuration"
  - "^delete .+"
  - "^format cfcard:"
  - "^undo vlan batch"
  - "^reboot"
  - "^shutdown$"
```

**Ajouter un vendor = écrire un YAML.** Aucune modification Python. La liste de `operations` peut grandir sans casser le moteur (on ignore les opérations non utilisées par la session en cours).

### Blacklist globale hardcodée (en plus du YAML vendor)

Dans `core.py`, une liste de patterns jamais poussés même si absents du YAML :

```python
GLOBAL_DESTRUCTIVE = [
    r"^\s*factory[- ]?reset",
    r"^\s*erase\s+(startup|running|flash)",
    r"^\s*reload\b",
    r"^\s*write\s+erase",
    r"^\s*boot\s+system\s+.*tftp://",    # boot depuis TFTP non authentifié
]
```

---

## §6 — Moteur de workflow & gates de validation

### 6.1 Gates obligatoires (3 minimum, dans cet ordre)

1. **`diff_review`** — après lecture running-config vs intent Visio, l'utilisateur voit le diff textuel coloré. Approve / Reject / Edit-intent.
2. **`cmd_review`** — après traduction intent → commandes vendor via YAML, l'utilisateur voit la liste exacte des lignes qui seront envoyées. Approve / Reject / Edit-manual.
3. **`post_push`** — après push (ou simulation si dry-run), l'utilisateur voit le résultat + reachability check. Approve (= `save`/`commit`) / Rollback (= `rollback configuration to previous` ou équivalent vendor).

Une gate rejetée **abort le run**, entry `deploy_log` marquée `validated=0`, rollback automatique si étape `push` déjà passée.

### 6.2 Auto-construction du workflow (n8n-like)

Le graphe de nodes n'est pas figé : il est généré dynamiquement depuis le diff.

```
Parse Visio (auto)
  └─ Lookup recon inventory (auto)
      └─ Vendor detect (auto, via banner + SNMP)
          └─ KeePass creds (prompt user)
              └─ Backup running-config (auto)
                  └─ Compute diff intent vs running
                      ├─ IF diff.vlans ≠ Ø   → node "VLAN ops"
                      ├─ IF diff.ports ≠ Ø   → node "Port ops"
                      ├─ IF diff.routing ≠ Ø → node "Routing ops" (futur)
                      └─ IF diff == Ø        → skip to "post-audit" node
                          └─ [GATE diff_review]
                              └─ Translate via YAML → commands
                                  └─ [GATE cmd_review]
                                      └─ Push (dry-run ou réel selon flag)
                                          └─ Reachability check
                                              └─ [GATE post_push]
                                                  └─ Save/commit (si approved)
                                                      └─ Update Visio (timestamp)
```

Rendu graphe : réutilise `forge_graph_explorer` en mode `?render=workflow&run_id=<uuid>`.

### 6.3 Dry-run par défaut

Flag `--apply` obligatoire pour push réel. Sans, toutes les commandes sont imprimées mais aucune connexion ConnectHandler en mode écriture : Netmiko est instancié mais seul `send_command` (lecture) est autorisé, jamais `send_config_set` ni `send_command_timing` en écriture.

---

## §7 — Endpoints hub & scopes JWT

Montés sous `/netcfg/` par `app/web_hub/app.py`. Nouveau scope JWT `netcfg:*` distinct du scope général — un token sans `netcfg:*` ne peut pas appeler ces endpoints (403).

| Endpoint | Méthode | Scope requis | Description |
|---|---|---|---|
| `/netcfg/inventory` | GET | `netcfg:read` | Liste des `netcfg_equipment` |
| `/netcfg/preview` | POST | `netcfg:read` | Parse Visio + diff intent vs running, retourne le plan (pas de push) |
| `/netcfg/deploy` | POST | `netcfg:deploy` | Exécute le workflow avec gates (SSE pour les prompts de validation) |
| `/netcfg/runs/{run_id}` | GET | `netcfg:read` | Audit trail d'un run (lit `netcfg_deploy_log`) |
| `/netcfg/runs/{run_id}/stream` | GET (SSE) | `netcfg:read` | Flux live des événements du run (§13.3) |

**POST `/netcfg/deploy`** est le seul endpoint qui mute : protégé par scope séparé, rate-limit 3 req / 5 min par user, logging explicite dans `hub_state.db` + `netcfg_deploy_log`.

---

## §8 — Plan d'implémentation (une seule passe)

Ordre strict, chaque étape ayant ses NR tests verts avant la suivante :

1. **Schéma DB** : 3 CREATE TABLE + migration script `app/netcfg/migrate.py` idempotent. Tests : `test_netcfg_db_schema.py` (4 tests).
2. **Parser Visio** : `visio.py` avec lecture `.vsdx` via `zipfile` + `lxml`, whitelist d'attributs, extraction shapes + connectors + metadata. Tests : `test_netcfg_visio.py` (3 tests, avec fixtures `.vsdx` minimales).
3. **Vendor templates + validator** : 6 YAML + `_schema.json` + fonction `load_template(vendor_key)` avec validation JSON Schema stricte. Tests : `test_netcfg_templates.py` (1 test = "chaque YAML passe le schema" + 1 test par operation obligatoire).
4. **Core** : `Equipment` (Netmiko wrapper), `VendorDetector`, `Workflow`, `Gate`, `Safety` (blacklist checker). Tests : `test_netcfg_core.py` (4 tests : detection vendor, blacklist fail-closed, dry-run bloque écriture, gate rejet abort).
5. **Endpoints + scope JWT** : 5 routes, intégration au hub, test manuel via curl + NR tests end-to-end. Tests : `test_netcfg_views.py` (3 tests : inventory GET, preview POST dry, deploy POST refusé sans scope).
6. **UI workflow** : SPA `netcfg_workflow.{html,js,css}` servie par `views.py`, Cytoscape pour le graphe, SSE pour le live, keyboard shortcuts actifs. Tests : 2 NR (serializer événements SSE + parser keyboard event) + checklist UX manuelle §13.5.

**Pas de commit partiel** : la couche est livrée complète ou pas du tout, pour éviter de laisser une surface d'attaque active sans garde-fous.

---

## §9 — Tests d'acceptation NR (17 obligatoires)

| # | Fichier test | Objet |
|---|---|---|
| 1 | `test_netcfg_db_schema` | 3 tables créées avec les bons champs |
| 2 | `test_netcfg_db_fk` | Foreign keys equipment_id vérifiées |
| 3 | `test_netcfg_db_migration_idempotent` | Re-run migrate = no-op |
| 4 | `test_netcfg_db_hash_chain` | hash_current = sha256(hash_prev + ...) vérifiable |
| 5 | `test_netcfg_visio_parse_minimal` | fixture .vsdx 2 shapes → 2 equipment |
| 6 | `test_netcfg_visio_reject_malformed` | .vsdx corrompu → exception propre, pas de crash |
| 7 | `test_netcfg_visio_whitelist_attrs` | attributs inconnus ignorés, pas propagés |
| 8 | `test_netcfg_templates_all_valid` | les 6 YAML passent `_schema.json` |
| 9 | `test_netcfg_templates_required_ops` | chaque YAML a `add_vlan` + `set_access_port` |
| 10 | `test_netcfg_vendor_detect_banner` | SSH banner "Huawei VRP" → `huawei_vrp` |
| 11 | `test_netcfg_safety_blacklist_local` | `reset saved-configuration` rejeté (YAML) |
| 12 | `test_netcfg_safety_blacklist_global` | `factory-reset` rejeté (hardcoded) |
| 13 | `test_netcfg_dryrun_blocks_write` | mode dry-run → aucun `send_config_set` appelé |
| 14 | `test_netcfg_gate_reject_aborts` | gate rejetée → status=`aborted`, rollback auto si push déjà fait |
| 15 | `test_netcfg_scope_jwt_enforced` | token sans `netcfg:deploy` → 403 sur POST /netcfg/deploy |
| 16 | `test_netcfg_sse_event_serializer` | payload événement SSE conforme au schéma §13.3 |
| 17 | `test_netcfg_sse_auth_required` | SSE stream sans token valide → 401 immédiat |

---

## §10 — Lignes rouges (jamais, même avec validation utilisateur)

1. **Jamais de transfert de fichier** via SCP/TFTP/FTP initié par l'agent : uniquement des commandes CLI ligne par ligne sur SSH. Un fichier malveillant poussé en config source = trop grande surface de compromission.
2. **Jamais de push sans backup préalable** réussi (entry `netcfg_config_backup` créée et validée).
3. **Jamais de stockage du master password KeePass** : prompt interactif uniquement, variable locale effacée (`del` + `gc.collect()`) dès les creds extraits pour la cible unique du run.
4. **Jamais de push de commandes générées par le LLM** : le LLM n'est autorisé qu'avec `--explain` et uniquement pour produire du texte narratif affiché à l'utilisateur (explication du diff, résumé du rapport). Les commandes réelles proviennent exclusivement des templates YAML Jinja2 rendus avec des variables validées.
5. **Jamais d'enrôlement automatique** : un équipement n'entre dans `netcfg_equipment` que par action explicite de l'utilisateur (CLI ou endpoint UI). La présence dans recon_silo ne suffit pas.
6. **Jamais de parallélisme de push** : un seul équipement poussé à la fois par run, verrou exclusif. Si l'utilisateur veut déployer sur 10 switches, 10 runs séquentiels avec 10 gates de validation — pas de "staged push" automatique dans cette version.
7. **Jamais d'override de la blacklist** : même un utilisateur admin ne peut pas la contourner. Pour pousser une commande blacklistée, il doit la faire manuellement dans son terminal, hors de l'agent. Fail-closed absolu.
8. **Jamais de dépendance réseau sortante depuis Nokido vers Internet** pour l'agent : tout est local (Netmiko, Ollama, KeePass local). Pas d'appel à une API cloud pendant un déploiement.
9. **Jamais d'auto-approbation de gate** depuis l'UI : même un double-clic accidentel sur Approve doit être confirmé par un second input dans une fenêtre de 2s (anti-misclick, §13.4). L'UX visuelle ne sacrifie jamais la sécurité.

---

## §11 — Intégration avec l'existant

| Brique Nokido | Usage |
|---|---|
| `recon_silo.nmap_parser.Host` | Source d'inventaire initial. `netcfg_equipment.ip_mgmt` référence une IP déjà connue du recon |
| `app/web_hub/` (JWT, CSP, JTI, rate-limit) | Toute la sécurité HTTP + auth réutilisée, scope `netcfg:*` ajouté |
| `app/forge_graph_explorer` Cytoscape | Shell HTML + assets Cytoscape.js réutilisés, page dédiée `netcfg_workflow.html` servie séparément |
| Pattern SSE (`app/web_hub/proxy.py`) | Streaming des événements de run, déjà benchmarké 2220 msg/s (map.md §1) |
| Pattern tests NR | 17 tests dans `tests/nr/test_netcfg_*.py` |
| `sandbox/` pour design | ce fichier |
| `map.md` | À mettre à jour avec Choix #7 — Couche C netcfg design figé |

---

## §12 — Ce qui est explicitement hors scope de cette v1

- Multi-site avec segmentation (VRF, MPLS, VXLAN) → v2
- Configuration de routage dynamique (OSPF, BGP) → v2
- Gestion des ACL / QoS → v2
- Push parallèle / staged deploy → v2
- Génération automatique de Visio depuis running-config (reverse) → v2 (le Visio est source, pas dérivé, dans cette version)
- Connecteurs cloud (AWS TGW, Azure Virtual WAN) → jamais dans netcfg, couche séparée si besoin
- API vendor propriétaire (Aruba Central, Huawei iMaster NCE) → v2 optionnel, Netmiko SSH suffit pour v1
- Support mobile / smartphone pour l'UI → hors scope v1, cible desktop min 1280×800

---

## §13 — UX/UI : exigences de fluidité, rapidité, lisibilité visuelle

Cette section formalise l'exigence utilisateur « l'interface doit faciliter les actions et doit être fluide rapide et visuel ». Les principes ici ont rang d'invariants de design, au même titre que les lignes rouges §10.

### 13.1 Principes directeurs

1. **Single-page, zéro reload.** Tout un run tient sur un écran. Les transitions d'état passent par SSE/WebSocket. L'URL reflète le `run_id` (deep-linkable) mais la navigation interne ne quitte jamais la page.
2. **Le graphe est la vue principale.** Cytoscape plein écran occupe ~70% de l'espace. Panneau latéral droit (contextuel) = 30%. Le footer sticky héberge le log stream.
3. **Keyboard-first.** Toute action fréquente doit avoir un raccourci clavier. La souris est optionnelle pour l'opérateur expérimenté.
4. **Feedback ≤ 100 ms.** Chaque action utilisateur produit un retour visuel immédiat (changement d'état de node, pulse sur bouton, toast). Le traitement backend peut être plus lent, le feedback UI ne l'est jamais.
5. **Lisibilité avant esthétique.** Code couleur strict, contrastes WCAG AA minimum, information redondante (couleur + forme + texte) pour accessibilité.
6. **Sécurité non sacrifiée par la rapidité.** L'UX peut rendre les actions plus faciles, jamais plus automatiques. Une gate reste une gate : l'utilisateur clique/presse Approve explicitement. Pas d'auto-approve, pas de timeout d'approbation favorable.

### 13.2 Layout fixe

```
┌─────────────────────────────────────────────────────────────────┐
│ [hostname SW-CORE-01] [vendor huawei_vrp] [run_id abc…]  [▌DRY] │  header 40px, fixe
├────────────────────────────────────────────┬────────────────────┤
│                                            │                    │
│                                            │  PANNEAU GATE      │
│     CYTOSCAPE WORKFLOW                     │  (diff / cmds /    │
│     (auto-layout breadthfirst)             │   boutons)         │
│     ~70% largeur                           │  ~30% largeur      │
│                                            │                    │
│                                            │  [A]pprove         │
│                                            │  [R]eject          │
│                                            │  [E]dit            │
│                                            │                    │
├────────────────────────────────────────────┴────────────────────┤
│ LOG STREAM — tail SSE live, 200 lignes max, auto-scroll toggle  │  footer 120px, sticky
└─────────────────────────────────────────────────────────────────┘
```

### 13.3 Palette d'états des nodes (code couleur + forme + animation)

| État | Couleur | Forme | Animation | Accessibilité (redondance) |
|---|---|---|---|---|
| `pending` | `#4a5568` gris neutre | Cercle | aucune | libellé « en attente » + icône `○` |
| `running` | `#3182ce` bleu | Cercle | pulse 1s | libellé « en cours » + icône `▶` |
| `gate_waiting` | `#d69e2e` ambre | Losange | pulse lent 2s + halo | libellé « validation requise » + icône `⏸` |
| `done` | `#38a169` vert | Cercle plein | aucune, transition 200ms | libellé « OK » + icône `✓` |
| `rejected` | `#e53e3e` rouge | Croix | shake 300ms à l'entrée | libellé « rejeté » + icône `✗` |
| `failed` | `#e53e3e` rouge | Cercle barré | shake 300ms à l'entrée | libellé « erreur » + icône `⚠` |
| `skipped` | `#a0aec0` gris clair | Cercle pointillé | fondu entrant 150ms | libellé « ignoré » + icône `→` |
| `commit_node` | `#805ad5` violet | Hexagone | glow 500ms une fois | libellé « commit » + icône `◆` |
| `gate_node` | `#d69e2e` ambre | Losange | — | libellé « gate » |

Les arêtes : grises par défaut, vertes quand les deux extrémités sont `done`, rouges quand l'aval est `rejected`/`failed`.

### 13.4 Format des événements SSE (`/netcfg/runs/{run_id}/stream`)

```json
{
  "type": "node_state_change",
  "ts": "2026-04-21T15:33:04.123Z",
  "run_id": "abc-123",
  "node_id": "push_vlan_42",
  "from_state": "running",
  "to_state": "gate_waiting",
  "payload": {
    "gate": "cmd_review",
    "diff_lines": ["+vlan 42", "+ description Marketing"],
    "commands_preview": ["system-view", "vlan 42", " description Marketing", "return"]
  }
}
```

Autres types d'événements : `log_line`, `gate_approved`, `gate_rejected`, `run_aborted`, `run_completed`, `reachability_result`.

Schéma validé côté client par le test NR #16. Compression gzip activée sur le flux SSE (bénéfice sur les `diff_lines` volumineux).

### 13.5 Keyboard shortcuts (globaux, actifs sur toute la page)

| Touche | Action | Notes |
|---|---|---|
| `A` | Approve la gate active | Premier appui = highlight + 2s de confirmation. Second `A` dans les 2s = approve réel. Anti-misclick (§10 ligne rouge 9). |
| `R` | Reject la gate active | Confirmation double également, pour cohérence. |
| `E` | Éditer intent / commandes | Ouvre un éditeur textarea dans le panneau, pas de modal |
| `D` | Toggle dry-run ↔ apply | Impossible si run déjà démarré |
| `P` | Pause workflow | Suspend entre deux nodes, pas au milieu d'un push |
| `?` | Modal d'aide | Affiche ce tableau + la palette d'états |
| `Esc` | Annule run | Reject auto sur toutes les gates restantes, rollback si push fait |
| `Ctrl+L` | Focus log stream | Permet scroll clavier dans le log |
| `G then E` | Go to Equipment list | Vim-style chord, optionnel |

Les shortcuts sont désactivés si le focus est dans un input/textarea.

### 13.6 Budgets de performance (non-négociables)

| Opération | Budget | Échec → |
|---|---|---|
| Parse Visio (50 shapes) | < 2 s | log warning, pas d'échec bloquant |
| Lookup inventory + detect vendor | < 1 s | fallback `_generic` |
| Diff computation (config < 5000 lignes) | < 500 ms | fallback diff textuel ligne-à-ligne |
| Render initial du graphe Cytoscape | < 300 ms | log, investigation |
| Transition d'état node (animation) | 150 ms | CSS uniquement, jamais bloquant |
| Feedback visuel sur keypress | < 100 ms | toujours synchrone |
| Push d'une opération simple | < 3 s en réel, ~instant en dry-run | timeout SSH = 30 s, gate failed |

### 13.7 Checklist UX manuelle (à passer avant merge)

- [ ] Raccourcis clavier tous fonctionnels, avec confirmation double sur A/R
- [ ] Palette d'états respectée, contraste AA mesuré au moins sur ambre et rouge
- [ ] SSE stream reconnecte automatiquement si coupure < 5 s
- [ ] Log stream scrollable, bouton pause auto-scroll visible
- [ ] Modal `?` documente tous les shortcuts
- [ ] Annulation (`Esc`) propre : rollback si push déjà fait, entry `deploy_log` avec `validated=0`
- [ ] Reachability indicator visible en permanence sur le panneau gate (ping running pendant et après push)
- [ ] Toasts non-bloquants sur events secondaires (backup done, ping OK, Visio update)
- [ ] Deep link `?run_id=abc` reprend un run existant sans rejouer
- [ ] Responsive dégradé : au-dessous de 1280px largeur, message « résolution non supportée » au lieu de layout cassé

### 13.8 Ce que l'UI ne fait PAS

- Pas de drag-and-drop de nodes pour éditer le workflow : le graphe est généré depuis le diff, pas construit à la souris (l'utilisateur ne bidouille pas la logique de workflow, il la valide)
- Pas de « mode batch » multi-switches dans la v1 (cohérent avec §10 ligne 6)
- Pas d'export du graphe en PDF/PNG depuis l'UI v1 (l'audit trail est en DB, suffisant)
- Pas de thème clair : dark theme only pour la v1, calqué sur le reste du hub

---

**Fin du design. Non implémenté. À valider par l'utilisateur avant toute écriture de code.**

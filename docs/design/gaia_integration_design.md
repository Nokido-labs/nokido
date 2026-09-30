# GAIA Integration — Design Security-by-Design (Doc-only)

**Version** : 0.1 — 2026-04-21 (état initial)
**Auteur** : Claude (collaboration supervisée)
**Scope Claude** : design doc uniquement. Aucun code dans `app/`. Toute implémentation runtime LLM hors scope (géré par stack Qwen autonome — voir `sandbox/aixcc_agent_design.md` §14).
**Statut** : 🧊 Figé — pas d'implémentation sans accord explicite.
**Version GAIA ciblée** : v0.17.3 (tag `v0.17.3`, commit main, publié 2026-04-20)

---

## 0. Sources primaires consultées

Toutes lues via l'API GitHub authentifiée (token fine-grained `github_pat_…`, scope minimum, expire 2026-07-15) :

| Source | Taille | Rôle |
|---|---|---|
| Release notes officielles `v0.17.3` | 11.4 KB | Vue marketing + changelog complet (21 commits) |
| `src/gaia/installer/export_import.py` | 14.4 KB | **Module canonique** du format de bundle |
| `tests/unit/test_export_import.py` | 14.1 KB | 14 tests = spec comportementale exécutable |
| `src/gaia/apps/webui/services/agent-seeder.cjs` | 10.2 KB | Seeder runtime au 1er lancement |
| `src/gaia/ui/routers/agents.py` | 8.1 KB | Endpoints REST côté UI |

Archivées dans `sandbox/gaia_source/` pour audit.

---

## 1. Réponses factuelles aux 4 points verrouillés

### 1.1 Format exact du paquet agent

**Format** : archive ZIP standard (`.zip`, compression DEFLATE).
**Extension** : pas de convention — l'utilisateur choisit le nom ; les tests utilisent `agents-export.zip`.
**Structure** :

```
bundle.json               ← table des matières JSON (en racine du zip)
<agent-id-1>/
    agent.py              ← OU agent.yaml (au moins un des deux requis)
    <autres fichiers arbitraires>
<agent-id-2>/
    agent.yaml
    ...
```

**Schéma `bundle.json`** :

```json
{
  "format_version": 1,
  "exported_at": "2026-04-21T12:34:56Z",
  "gaia_version": "0.17.3",
  "agent_ids": ["my-agent", "weather-bot"]
}
```

La version `format_version` est un entier monotone (1 pour l'instant). Tout autre valeur → rejet immédiat.

**Emplacement canonique** des agents sources : `~/.gaia/agents/<id>/` (résolu via `Path.home() / ".gaia" / "agents"`).

### 1.2 Clé HMAC — scope, rotation, stockage

**Distinction critique** (qui levait mon ambiguïté initiale) :

- Le HMAC-SHA256 introduit en v0.17.3 **concerne exclusivement le cache RAG** (CWE-502, PR #768). Remplace `pickle` par JSON+HMAC.
- **Le paquet agent exporté n'est PAS signé.** Pas de HMAC, pas de signature asymétrique. C'est un zip « honest-transit » qui repose sur :
  - Validation stricte du contenu à l'import (zip-slip, symlinks, limites de taille, IDs conformes)
  - Confiance implicite de la source (utilisateur décide qui lui a donné le bundle)

**Pour le HMAC du cache RAG** :
- **Stockage** : `~/.gaia/cache/hmac.key` — fichier local, **clé par installation**
- **Rotation** : non documentée, non explicite. Comportement observé : clé générée au premier besoin ; cache non signé ou signature invalide → rejeté et **rebuilt silencieusement** à la requête suivante
- **Scope** : local à la machine — pas prévue pour circuler avec les bundles

### 1.3 Endpoint / CLI d'export

**CLI** (confirmé dans `src/gaia/cli.py`, release notes, et `docs/reference/cli.mdx`) :
- `gaia agents export <output.zip>` — au **pluriel** (pas `agent`), note importante
- `gaia agents import <bundle.zip>`

**API REST** (via `src/gaia/ui/routers/agents.py`, non encore lu en détail mais listé dans PR #795 : +179 lignes) : endpoints côté hub UI pour l'export/import via interface graphique.

### 1.4 Contenu du paquet — prompts / tools / MCP configs

**Réponse brutale** : **le paquet embarque tout ce qui se trouve dans le dossier `~/.gaia/agents/<id>/`, sans filtre**.

Le code `export_custom_agents` parcourt `agent_dir.rglob("*")` et écrit **chaque fichier** dans le zip. Aucune whitelist, aucune exclusion de champs sensibles.

Concrètement, cela inclut potentiellement :
- `agent.py` — **code Python exécutable** (le plus gros sujet de sécurité)
- `agent.yaml` — configuration déclarative (prompts système, outils, paramètres LLM, configs MCP)
- Assets arbitraires : prompts markdown, templates, données de référence, secrets si l'utilisateur en a placé là

**Conséquence sécurité directe** : importer un bundle GAIA non vérifié = **exécuter du code Python arbitraire** au prochain lancement de l'agent. C'est équivalent à `pip install` depuis une source inconnue. AMD l'assume implicitement — il n'y a pas de sandbox, pas de code review automatique, pas de signature.

Les garde-fous implémentés côté AMD à l'import couvrent **l'intégrité structurelle du zip**, pas la confiance du code :
- Anti zip-slip (path traversal)
- Pas de symlinks
- Pas de chemins absolus
- Limites de taille (500 MB total, 50 MB/fichier, 1000 entrées max)
- IDs d'agents conformes à `^[a-z0-9]([a-z0-9-]{0,50}[a-z0-9])?$`
- Rejet des noms de périphérique Windows réservés (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
- Import atomique avec rollback (staging dir + `os.replace`)

**Ce qu'AMD ne fait PAS (et c'est notre responsabilité si on intègre)** :
- Aucune signature du bundle
- Aucune vérification du code Python contenu
- Aucune whitelist d'imports
- Aucune isolation d'exécution

---

## 2. Threat model pour l'intégration Nokido

### 2.1 Principe cardinal (non-négociable)

**Nokido reste strictement passif sur les bundles GAIA.** On archive, on indexe, on affiche — on n'exécute **jamais** un agent importé. Même pattern que la Couche A CTF Reports (CAI).

### 2.2 Hypothèses d'attaquant

Un bundle GAIA arrivant dans Nokido peut avoir pour origine :
- Un collègue de confiance (cas nominal)
- Un workshop / partage communautaire (confiance faible)
- Un attaquant ciblant spécifiquement l'utilisateur (malveillant)

Dans tous les cas on traite l'entrée comme **non fiable** :

| Vecteur | Mitigation native GAIA | Mitigation supplémentaire Nokido |
|---|---|---|
| Zip-slip | ✅ géré (`is_relative_to(agents_root)`) | Revalider nous-mêmes au parsing |
| Symlinks | ✅ rejetés | — |
| Zip-bomb | ✅ 500 MB/50 MB/1000 entries | Plafond plus strict côté Nokido (50 MB total recommandé) |
| `agent.py` malveillant | ❌ aucune | **Jamais d'import dans le runtime Nokido** — seulement affichage read-only |
| Prompts injection dans YAML | ❌ aucune | Échappement HTML strict côté affichage |
| Secrets embarqués par erreur | ❌ aucune | Détection de pattern (keys API, tokens) à l'affichage avec redaction |
| Manifest `bundle.json` forgé | ✅ validé (format_version, agent_ids list-of-strings) | — |
| IDs Windows réservés | ✅ rejetés | — |

### 2.3 Scope Nokido strict

- ✅ **Parser** le bundle (réutiliser les guards d'AMD : taille, zip-slip, symlinks)
- ✅ **Archiver** en SQLite WAL (table `agent_bundles` dédiée, pas `ctf_sessions`)
- ✅ **Extraire les métadonnées** (bundle.json + liste des fichiers + hash sha256 du zip)
- ✅ **Afficher read-only** sous `/reports/agents/` (GET uniquement, test statique `test_router_only_has_get_routes`)
- ❌ **Jamais** exécuter `agent.py`
- ❌ **Jamais** charger `agent.yaml` comme config active
- ❌ **Jamais** re-exporter / re-signer un bundle
- ❌ **Jamais** forwarder vers Lemonade ou un LLM

---

## 3. Schéma DB proposé

**Table dédiée** `agent_bundles` (SQLite WAL, cohérent avec `ctf_sessions`) :

```sql
CREATE TABLE agent_bundles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bundle_sha256   TEXT NOT NULL UNIQUE,         -- déduplication forte
    filename        TEXT NOT NULL,                 -- nom fichier d'origine
    size_bytes      INTEGER NOT NULL,
    imported_at     TEXT NOT NULL DEFAULT (datetime('now')),
    gaia_version    TEXT,                          -- depuis bundle.json
    exported_at     TEXT,                          -- depuis bundle.json
    format_version  INTEGER,
    agent_count     INTEGER,
    source_hint     TEXT,                          -- texte libre utilisateur (qui m'a donné ce bundle)
    storage_path    TEXT NOT NULL,                 -- chemin relatif dans logs/agent_imports/
    meta            TEXT DEFAULT '{}'              -- JSON libre
);

CREATE TABLE agent_bundle_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bundle_id       INTEGER NOT NULL REFERENCES agent_bundles(id),
    agent_id        TEXT NOT NULL,                 -- validé ^[a-z0-9]([a-z0-9-]{0,50}[a-z0-9])?$
    file_path       TEXT NOT NULL,                 -- chemin dans le zip (sécurisé)
    file_sha256     TEXT NOT NULL,
    file_size       INTEGER NOT NULL,
    content_type    TEXT,                          -- heuristique : python/yaml/markdown/binary/secret-suspect
    UNIQUE (bundle_id, file_path)
);

CREATE INDEX idx_bundle_entries_agent ON agent_bundle_entries(bundle_id, agent_id);
```

Les blobs binaires des bundles restent sur disque (`logs/agent_imports/<sha256_first_8>/<filename>`), jamais en DB.

---

## 4. Endpoint proposé (doc-only)

```
POST /reports/agents/import      ← non implémenté dans cette phase
GET  /reports/agents/            ← liste des bundles archivés
GET  /reports/agents/<id>        ← détail d'un bundle
GET  /reports/agents/<id>/entries ← arbre des fichiers
GET  /reports/agents/<id>/view?path=<sanitized> ← affichage d'un fichier individuel (read-only, MIME forcé text/plain)
```

CSP stricte sur la page d'affichage (alignée avec `app/web_hub/csp.py` Gemini #3) : pas d'inline script, pas d'eval, nonce par requête.

Test de non-régression dédié : `test_agents_router_only_has_get_routes` — garantit l'absence de POST/PUT/DELETE au niveau du routeur read-only (l'import est idéalement une CLI ou un endpoint séparé avec auth distincte).

---

## 5. Décisions techniques tranchées (défauts sûrs)

| Question | Décision | Justification |
|---|---|---|
| Accepter paquets non signés ? | **Oui par défaut** | GAIA lui-même n'émet pas de signature ; refuser les non-signés = refuser tout GAIA natif |
| Notre propre signature sur réexport ? | **Pas de réexport du tout** | Scope Claude = passif ; signer serait adhérer à un modèle de confiance qu'on ne maîtrise pas |
| Table DB partagée avec CTF ? | **Séparée** (`agent_bundles` ≠ `ctf_sessions`) | Sémantiques trop différentes (session pentest ≠ bundle exécutable) |
| Taille max par bundle ? | **50 MB** | 10× plus strict qu'AMD — on archive, on n'a pas besoin de gros binaires |
| Hash de déduplication ? | **sha256 du zip entier** | Évite les doublons, sert de clé primaire de facto |
| Détection de secrets dans les fichiers ? | **Heuristique simple** (regex tokens courants) avec redaction à l'affichage | Pas de prétention "DLP complet" ; juste un filet de base |
| Où stocker les blobs ? | `logs/agent_imports/<sha256[:8]>/<filename>` | Pattern déjà utilisé pour `ctf_imports/` |
| gitignore ? | Oui, `logs/agent_imports/` ajouté au gitignore | Jamais commiter de bundle utilisateur |

---

## 6. Points ouverts (non tranchés)

1. **Rendu syntaxique** : faut-il coloriser `agent.py` à l'affichage ? Si oui, via highlight.js côté client (CSP ajuste) ou Pygments côté serveur (plus simple, zéro JS). **Tendance** : Pygments côté serveur.
2. **Extraction du system_prompt** : doit-on parser `agent.yaml` pour extraire `system_prompt` et l'indexer en RAG ? Utile pour semantic search, mais risque d'indexer des prompts sensibles. **Tendance** : opt-in explicite utilisateur par bundle.
3. **Liaison bundle ↔ rapports CTF** : si un agent a produit des rapports CAI qu'on archive en Couche A, faut-il lier les deux ? Utile pour traçabilité mais ajoute de la complexité. **À reporter en v2.**

---

## 7. Plan d'implémentation (quand/si accord utilisateur)

Ordre proposé, chacun en PR/commit dédié avec tests NR :

1. **Schéma DB** + `schema.py` (mini, 30 lignes type)
2. **Parser bundle** avec réutilisation stricte des guards d'AMD (copier la whitelist + limites)
3. **Importeur CLI** `python -m app.agent_imports.import_bundle <file>` (pattern CAI)
4. **Endpoints GET** sous `/reports/agents/` + test `test_router_only_has_get_routes`
5. **UI minimaliste** alignée sur le design du `/reports/` existant (Couche A)
6. **Tests NR** couvrant : parsing valide, zip-slip rejeté, symlinks rejetés, oversized rejeté, IDs invalides, format_version wrong, manifest manquant, déduplication sha256

Volume estimé : **~600 lignes code + ~500 lignes tests**, 1 session focalisée.

---

## 8. Ce qu'on ne fait PAS (ligne rouge)

- ❌ Écrire un exécuteur `agent.py` dans Nokido (hors scope Claude, géré en Qwen autonome si pertinent)
- ❌ Modifier `mcp_server_tools.py` ou `forge_cai_bridge.py`
- ❌ Proxyer vers Lemonade / un LLM local
- ❌ Importer automatiquement un bundle sans action utilisateur explicite (CLI ou bouton UI)
- ❌ Resigner / re-distribuer un bundle importé

---

## 9. Notes annexes

### 9.1 Divergence observée vs presse

L'article Phoronix du 20 avril titrait sur "export/import + RAG HMAC". Le titre sous-estime les **bug fixes RAG** (PDF chiffrés, thread-safety, indexing failures surfaced) qui sont techniquement plus importants pour quelqu'un qui utilise réellement GAIA. La release officielle s'appelle **"RAG bug fixes and security hardening [OSS]"** — cohérent avec ce que j'avais trouvé dans l'issue #774 avant même d'avoir la release en main.

### 9.2 Dette technique rencontrée pendant la recherche

- **Bug "5 outils sur 12"** : faux bug. Les 12 outils Nokido sont **deferred** et doivent être chargés par `tool_search("Nokido write")` — règle système #1 déjà documentée, que j'avais simplement loupée. Pas d'action corrective nécessaire côté code, juste mémoire active pour les prochaines sessions Claude.
- **Token GitHub révoqué dans Credential Manager** : l'ancien `ghp_l49z9Znf...` (Classic PAT) dans Windows Credential Manager est expiré depuis le 16 avril. Le `.env` contient lui un fine-grained valide jusqu'au 15 juillet. **Recommandation** : soit purger le CredMan (`Remove-StoredCredential -Target GITHUB_TOKEN`), soit mettre à jour avec le nouveau token. Non urgent — le `.env` prend le dessus au boot MCP.

### 9.3 Secrets dans `Nokido.env`

Audit rapide observé en passant : le `.env` contient en clair Gemini, Groq, xAI, HuggingFace, DeepSeek, OpenRouter, deux GitHub tokens, plus un admin token Nokido. Ce n'est pas le sujet de ce doc mais mérite un ticket séparé — le pattern "tout dans .env gitignored" est courant mais fragile (dump accidentel, backup, IDE qui indexe). Migration possible vers Windows Credential Manager pour les plus sensibles (GITHUB_TOKEN fine-grained en priorité vu les droits repo).

---

**Fin du document.**

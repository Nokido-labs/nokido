---
name: forge-anatomy
description: >
  Grille anatomique de Nokido : diagnostic différentiel organe →
  pathologie → remède. À utiliser avant de concevoir un module
  forge_*.py, sur un bug systémique aux symptômes diffus, pour un audit
  d'architecture, ou pour savoir à quel organe appartient un module.
  Autorité : census organ_map_full.json. Jumeau de
  forge-systematic-debugging.
---

# forge-anatomy — Diagnostic différentiel par biomimétisme

## Pourquoi cette grille existe

Une architecture logicielle complexe (Nokido : nombre de modules dans le census)
devient **illisible** si on la lit module-par-module. La grille
anatomique :
- **Compresse** la complexité en 7 systèmes biologiques familiers
- **Révèle des pathologies invisibles** en grille purement IT
  (auto-immunité, cascade, septicémie systémique)
- **Guide la conception** : avant de coder, quel organe ?
- **Accélère le diagnostic** : symptôme → organe suspect → modules
  candidats

Le code Nokido **utilise déjà** cette analogie en commentaires
(`tools/nokido_hub.py` lignes 1070-1077 : Cortex Préfrontal,
Cervelet, Moelle Épinière). Ce skill généralise et opérationnalise.

## Quand m'invoquer

### Conception
- "Je veux ajouter un module qui fait X — où le placer ?"
- "C'est plutôt système nerveux ou immunitaire ?"
- "Quel ring de sécurité pour cet organe ?"
- "Comment ce nouveau composant s'intègre-t-il à la circulation
  des données ?"

### Diagnostic
- Bug systémique avec symptômes diffus (plusieurs modules touchés)
- Comportement aberrant non couvert par `forge-systematic-debugging`
  (RCA classique épuisé)
- Cluster d'erreurs RAG anchored autour d'un même thème → maladie
  chronique d'un organe
- "Pourquoi ce bug se propage-t-il ?" → effet cascade / inflammation
  systémique

### Audit
- Revue architecturale d'un sous-système
- Vérification que les "barrières" (immunitaires) sont bien câblées
- Identification de dégénérescences progressives (sclérose,
  hyperplasie)

### Formation
- Onboarding d'un nouveau LLM ou humain sur Nokido
- Réponse à "qu'est-ce que Nokido sait faire ?" sous angle anatomique

## Cartographie complète (autorité : census `sandbox/workspace/organ_map_full.json` ; vue humaine : `docs/CLAUDE_CARTOGRAPHIE_ANATOMIQUE.md`)

### 🧠 Système Nerveux Central

| Organe | Module | Rôle |
|---|---|---|
| Cerveau (hub) | `tools/nokido_hub.py` :8766 | Conscience globale, ordonnancement |
| Cortex préfrontal | `app/forge_cognitive_router.py` | Décision consciente, INHIBITION |
| Cervelet | `app/forge_spike_router.py` | Réflexes appris (SNN, 38 CTF) |
| Moelle épinière | `app/forge_byte_router.py` | Transport bidirectionnel pur |
| SN périphérique | `app/forge_mcp_registry.py` | Dispatch tools, RBAC |
| Métabolisme énergétique | `app/forge_llm_router.py` | Sélection substrat (24 providers) |

### 💾 Mémoire (Hippocampe + cortex)

| Organe | Module | Rôle |
|---|---|---|
| Hippocampe (consolidation court→long) | `app/forge_self_correction.py` | anchor_*, lessons, session_summary |
| Cortex sensoriel (long terme) | `RAG/embeddings.db` + `app/forge_rag_engine.py` | FAISS + BM25 + RRF |
| Synapses (potentialisation continue) | `app/forge_rag_warmup.py`, `tools/forge_post_commit.py` | Indexation au boot + chaque commit |
| Réseau par défaut (rumination) | `app/forge_ingest_self.py` | Auto-réflexion sur le code |

### 🛡️ Système Immunitaire

| Organe | Module | Rôle |
|---|---|---|
| Barrière hémato-encéphalique | `app/forge_semantic_firewall.py` | pre_flight + post_flight 4 couches |
| Anticorps spécifiques | `app/forge_prompt_guard.py` | 15 patterns injection EN/FR |
| Membrane cellulaire | `app/forge_sovereign_membrane.py` | wrap/unwrap HMAC alias |
| Macrophages | `SkillGuardian` (`forge_clawhub_bridge.py`) | review skills (LLM + regex + SAST) |
| HLA / RBAC | `app/forge_integrity.py::IntegrityRing` | MASTER/SYSTEM/DEV/TRUSTED/COLLAB/UNTRUSTED |
| Détection corps étrangers | `forge_silo_fragmenter.py::NoiseGuardian` | Sanitize IPs MACs CVEs |
| Détection fièvre (homéostasie) | `app/forge_token_monitor.py` | Anomalies coût/latence |

### 🌿 Système Nerveux Végétatif (autonome)

| Organe | Module | Rôle |
|---|---|---|
| Bulbe rachidien (vital reflex) | `app/forge_inspector.py` | Monitoring sys/réseau/zombies |
| Sympathique (alerte) | `app/forge_idle_watchdog.py`, `forge_ping_monitor.py` | Watchdogs |
| Parasympathique (boot, repos) | `app/forge_provider_watcher.py` | Boot des providers |
| Système rénin-angiotensine | `tools/forge_rescue.py` | Canal de secours admin |

### 🍽️ Système Digestif

| Organe | Composant | Rôle |
|---|---|---|
| Bouche / œsophage | `/ingest/url`, `/ingest/bulk` (hub :8766) | Entrée brute |
| Estomac (broyage) | `forge_ingest_self.py`, `MarkdownChunker` | Chunking |
| Intestin grêle (absorption sélective) | `app/forge_rag_qualify.py` | trust_weight |
| Foie (détoxification) | `app/forge_secret_guard.py` | DLP redact |
| Vésicule biliaire (catalyse) | `app/forge_rag_truth.py` | Vérification factuelle |

### 💪 Système Locomoteur (effecteurs)

| Organe | Module | Rôle |
|---|---|---|
| Muscles striés (volontaire) | 7 SiloDomain (`app/forge_silo_engine.py`) | code/security/strategy/synthesis/recon/exploit/doc |
| Squelette / fascia | `app/forge_runtime.py`, `app/forge_runner.py` | Spawn fire-forget, mmap IPC |
| Articulations | `app/forge_message_frame.py`, `tools/forge_broker_base.py` | Cinématique inter-modules |
| Bras prosthétique externe | `forge-android` (Android-MCP) | Effecteur device Android |

### 👁️ Sens (Perception)

| Organe | Module | Rôle |
|---|---|---|
| Vision (œil) | `app/forge_browser_tool.py`, `app/forge_crawl_tool.py` | Web/scraping |
| Ouïe (canaux MCP) | `tools/mcp_stdio_bridge.py` + clients (Claude Desktop, Cline) | Stimuli des LLMs |
| Toucher (effecteur tactile direct) | `netcfg-agent` PTY SSH, `forge-android` | Interaction physique |
| Proprioception (état interne) | `app/forge_context.py`, `app/forge_context_steadiness.py` | Conscience de soi |

## Diagnostic différentiel par symptôme

Format : symptôme → organes suspects → examens à faire.

### 🩺 "Le système se bloque mais aucun crash visible"

**Suspects** :
1. **SN végétatif (bulbe)** — coma, hub UP mais ne répond plus
2. **Sclérose en plaques** — bridge stdio deadlock
3. **Hémorragie** — fuite mémoire async dans un broker

**Examens** :
```bash
# 1. Vérifier le pouls (hub healthy ?)
curl -s -m 2 http://127.0.0.1:8766/health

# 2. Tension (process / RAM / threads)
# Lire app/forge_inspector.py logs récents

# 3. EEG (logs MCP unifiés)
tail -200 logs/mcp_audit.log

# 4. Recherche RAG
preflight_check_verbose("hub deadlock bridge stdio coma timeout", "")
```

### 🩺 "Le système rejette des requêtes légitimes"

**Suspects** :
1. **Auto-immunité** — SemanticFirewall trop strict
2. **Allergie** (faux positif) — patterns regex de SkillGuardian
3. **Lupus systémique** — IntegrityRing mal configuré (ring trop bas)

**Examens** :
- Lire `forge_semantic_firewall.py::pre_flight` ; chercher
  les patterns qui matchent indûment.
- Vérifier `forge_tools.min_ring` en DB pour le tool concerné.
- Test : injecter une requête témoin (canary connue safe) et voir
  où elle est bloquée.

### 🩺 "Cascade d'erreurs en chaîne quand je touche à un module"

**Suspects** :
1. **Inflammation systémique** — couplage fort non documenté
2. **Réaction allergique systémique** — rétroaction + SkillGuardian
3. **Septicémie** — un module pourri qui contamine ses voisins

**Examens** :
```python
# Cartographie des dépendances
import ast
# Parser les imports croisés des forge_*.py
# Identifier les modules les plus connectés (centralité)

# RAG : a-t-on déjà documenté ce couplage ?
preflight_check_verbose("<module> couplage cascade <symptôme>", "")
```

### 🩺 "Le LLM hallucine dans ses réponses"

**Suspects** :
1. **Démence vasculaire** — RAG retourne des chunks périmés
   (`lambda_decay` mal calibré)
2. **Empoisonnement (intox alimentaire)** — un parser pourri injecte
   des données aberrantes (foie défaillant)
3. **Délire de Capgras** (déni de réalité) — `forge_rag_truth` non
   appelé en post-flight

**Examens** :
- Audit `forge_rag_qualify.py::trust_weight` distribution.
- Vérifier `forge_secret_guard` pour redaction excessive (qui
  vide le sens).
- Activer `forge_rag_truth` en post-flight.

### 🩺 "Lenteur progressive sans cause apparente"

**Suspects** :
1. **Sclérose** — accumulation de fragments dans buffers stdio
2. **Athérosclérose RAG** — DB qui grossit, FTS5 plus assez sélectif
3. **Sarcopénie** — modules legacy `_attic` non purgés qui ralentissent
   les imports

**Examens** :
```bash
# Taille du RAG
ls -lh RAG/embeddings.db
sqlite3 RAG/embeddings.db "SELECT COUNT(*) FROM rag_chunks;"

# Latences MCP (forge_token_monitor.py)
preflight_check_verbose("latence p99 MCP slow", "")
```

### 🩺 "Un nouveau module casse des trucs invisibles"

**Suspects** :
1. **Hyperplasie** (tissu redondant) — duplication d'un organe
   existant (cf. forge_pii_detector mort-né, CLAUDE.md §3)
2. **Tumeur** — module qui se développe en dehors du contrôle du
   système immunitaire (pas review Guardian)
3. **Greffe rejetée** — incompatibilité ring de sécurité

**Examens** :
- **Anti-duplication checklist** (CLAUDE.md §3 — non-négociable)
- Vérifier `__FORGE_COLOR__` header présent
- Test isolation : `pytest tests/ -k <new_module>` doit passer **avant**
  d'enregistrer le tool dans `forge_mcp_registry`

## Protocole d'examen général (4-phase)

Inspiré de `forge-systematic-debugging` mais avec lentille anatomique :

### Phase 1 — Anamnèse + Examen général
```python
from forge_self_correction import preflight_check_verbose, read_lessons

# Antécédents (lessons récentes)
print(read_lessons(3000))

# Signes vitaux
import urllib.request
print(urllib.request.urlopen("http://127.0.0.1:8766/health", timeout=2).read())
```

### Phase 2 — Examen systémique
Question pour chaque organe : **fonction normale ?** Si doute, audit
ciblé (logs, métriques, query RAG par domaine).

### Phase 3 — Hypothèse diagnostique
Une seule pathologie suspectée à la fois (cf. table pathologies-types
de docs/CLAUDE_CARTOGRAPHIE_ANATOMIQUE.md).

### Phase 4 — Test thérapeutique
- **Anti-inflammatoire** : timeout, circuit breaker, période réfractaire
- **Antibiotique** : isolation membrane souveraine, sandbox silo
- **Chirurgie** : ablation du module pathogène (avec preflight RAG !)
- **Greffe** : module de remplacement (extension d'un existant)

Toujours **anchor_solution** après guérison :
```python
anchor_solution(
    problem="<pathologie diagnostiquée>",
    solution="<organe + module + traitement appliqué>",
    example="<commande/snippet>",
    domain="<organe en taxonomie biologique : cortex|hippocampe|"
           "immunitaire|vegetatif|digestif|locomoteur|sens>",
    # NB: option C (taxonomie organ explicite) à venir Q3 2026
)
```

## Règle des 3 questions pour un nouveau module

Avant d'écrire un `forge_*.py`, réponds :

1. **Quel organe ?** (parmi les 7 systèmes ci-dessus)
   - Si tu hésites entre 2 organes → c'est probablement à créer comme
     **inter-organe** (genre articulation, glande, ganglion).

2. **Quelle vascularisation ?**
   - Quels modules pompent vers ce nouveau module ? (data flow entrant)
   - Quels modules consomment sa sortie ? (data flow sortant)
   - Quel ring de sécurité (`forge_tools.min_ring`) ?
   - Quelles dépendances singletons (`forge_context.py`) ?

3. **Scénario d'hémorragie ?**
   - Si ce module **fuit** (mémoire, données sensibles) : qui meurt ?
   - Si ce module **crash** : quels organes sont anoxiques ?
   - Si ce module est **compromis** par un attaquant : que peut-il
     atteindre ?

Si tu réponds correctement aux 3, tu peux coder. Sinon, retour à la
case départ : preflight RAG et lecture des modules existants.

## Anti-patterns

1. **Forcer une analogie qui ne fonctionne pas** — si un module ne
   s'inscrit dans aucun organe, c'est probablement un signal de
   **mauvaise modélisation**. Refactor avant de coder.
2. **Utiliser cette grille seul** — l'anatomie est un **cadre
   complémentaire** à la lecture du code, pas un substitut.
3. **Diagnostiquer sans examen** — toute hypothèse anatomique doit
   être confirmée par un examen (logs, RAG query, lecture de code).
4. **Sur-anthropomorphiser** — Nokido n'est PAS un humain. Les
   contraintes (latence µs, sérialisation JSON, persistance SQLite)
   sont fondamentalement non-biologiques. La grille aide à penser,
   pas à dicter.
5. **Skipper `forge-systematic-debugging`** sous prétexte d'utiliser
   l'anatomie — la RCA 4-phase est OBLIGATOIRE, l'anatomie l'enrichit.

## Liens

- **Source de vérité** : census `sandbox/workspace/organ_map_full.json` ; vue humaine `docs/CLAUDE_CARTOGRAPHIE_ANATOMIQUE.md`
- Skill jumeau : `forge-systematic-debugging` (Phase 1 = examen
  systémique anatomique)
- Skill jumeau : `forge-tdd` (greffe contrôlée d'un nouveau muscle)
- Skill jumeau : `forge-security-scan` (système immunitaire renforcé)
- Skill `nokido` : carte des capacités (vue purement IT)
- TODO option C : taxonomie `organ=` dans `anchor_solution` —
  cible Q3 2026 (cf. mémoire `project_anatomy_taxonomy_TODO.md`)
- Inspiration : commentaires dans `tools/nokido_hub.py` lignes
  1070-1077

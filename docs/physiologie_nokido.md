# Physiologie Nokido — Organisme céphalopode numérique

<!-- ports-arretes -->
> ⚠️ **Ports arrêtés cités dans cette page** (note ajoutée le 2026-08-30 ; le corps ci-dessous n'a pas été réécrit) :
>
> - `brain_worker :5557` est **arrete depuis le 2026-06-03** (OOM ONNX BGE-M3) — l'embedder vivant est `:8099` (BGE-M3 GGUF llama.cpp).


**Version** : 2026-05-02 post-Phase G MVP
**Source** : synthèse user (analogie biologique canonique)
**Statut** : Référence partagée tous CLI (Claude/Gemini/Codex/Cline)

> ⚠️ **CHIFFRES PÉRIMÉS (audit 2026-06-11)** — ce doc mentionne "11 services / 19 lobes" ; le
> recensement RÉEL de juin 2026 = **15 organes / ~985 modules** (census `sandbox/workspace/
> organ_map_full.json`, vue live `/forge/network` → onglet Doc Organes → endpoint `/api/organs`,
> `CLAUDE.md` §10). L'analogie biologique reste valable ; pour les COMPTES, voir les sources live.

> Dans cette architecture, Deno est le liquide céphalo-rachidien — il
> baigne tous les organes, protège des chocs, transporte ultra-vite les
> nutriments. Python 3.14 est la matière grise — calcul lourd + logique
> haut niveau.

---

## 🧠 Système Nerveux Central

### Moelle épinière — `proxy_deno :8000`
- Synapse numérique (fente synaptique) : filtre + transmet JSON-RPC
- Communication afférente : sensors (Exegol/Scrapers) → Proxy
- Communication efférente : Dispatcher → muscles (NSSM services)
- Potentiel d action : message transmis si dépasse seuil pertinence
  (motivation + novelty)

### 11 Services NSSM — Organes vitaux
Métazoaire complexe. Si arrêt → biologie effondre.

### 19 Lobes cérébraux — `forge_anatomy_state`
Reconnectés au :8000 = Nokido a **proprioception** (conscience membres).

---

## 🛡️ Système Immunitaire

| Mécanisme | Module | Analogie |
|---|---|---|
| Réflexe de retrait | `preFlightCloudCheck` (Phase B.2) | Arc réflexe — coupe influx Cloud si Hub Python mort |
| Membrane cellulaire | `forge_sovereign_membrane` (Vault HMAC) | Encapsule données sensibles, manipule sans contact ADN |
| Adaptatif | `forge_opsec` (3 niveaux) | PARANOID = inflammation, CTF = repos, Centaure = régulation humaine |
| Kill Switch | `/api/persist/kill_switch` :8000 | Choc anaphylactique contrôlé — coupe TOUS outbounds |

---

## 🚀 Cognition Supérieure

| Composant | Rôle biologique |
|---|---|
| Python 3.14 (4 services) | Néocortex moderne — raisonnement abstrait, no-GIL parallélisme |
| `code_critic.ts` | Lobe frontal (jugement) — surmoi qui filtre pulsions du forgeron Gemini |
| `tool_smith.ts` (Phase G) | Plasticité synaptique — création connexions/neurones JIT |
| NPU Ryzen-AI 1.7.0 | Cervelet (instinct) — coordination motrice ultra-rapide inconsciente |

---

## 🧬 Règle d Or — Code Génétique

Chaque pensée → action via Hub MCP :8769.
Validation `tools[]` dans payload API = transcription génétique ARNm
correcte. Si copie ratée → protéine (action IA) jamais créée.

Implémenté dans `proxy_deno/hub_mcp/main.ts::validateMcpRequest()` +
`preFlightCloudCheck()`.

---

## 🔄 Tableau de coordination des flux

| Émetteur | Message (neurotransmetteur) | Récepteur | Effet biologique |
|---|---|---|---|
| `forge_novelty_search` | `ANOMALY_DETECTED` | `forge_motivation` | Augmente attention cible |
| `forge_active_inference` (FEP) | `HIGH_SURPRISE` | `forge_self_correction` | Déclenche audit code échoué |
| `forge_flow_zone` | `LATENCY_CRITICAL` | `forge_dispatchers` | Pause tâches non-essentielles |
| `forge_sovereign_membrane` | `TOKENIZED_DATA` | Cloud API | Pensée sans exposition sang |
| `code_critic` | `AUDIT_REJECTED` | `tool_smith` retry | Force iteration suivante |
| `forge_opsec` | `KILL_SWITCH_TRIGGERED` | `preFlightCloudCheck` | Reject tous outbounds |
| `forge_synaptic_plasticity` | `WEIGHT_REINFORCED` | `forge_rag_engine` (FAISS) | Tool plus rapidement retrouvé |
| `forge_trajectory` | `PATH_RECORDED` | `forge_hebbian_linker` | Enregistre séquence succès |

---

## 🌊 Cycle Savoir → Savoir-Faire → Faire-Savoir

```
1. Dispatcher exécute commande
2. Self-Correction juge résultat
3. Trajectory enregistre chemin
4. Synaptic renforce poids tool dans catalogue MCP
   ↓
   Le futur "moi" de Nokido saura que ce tool est efficace.
```

---

## 📂 Lobes fonctionnels (4 grandes zones)

### Lobe Sensoriel
- `forge_novelty_search` — détecteur nouveauté (anti-boucle)
- `forge_active_inference` — mesure surprise (écart prédiction/réel)

### Lobe Limbique
- `forge_motivation` — moteur recherche objectifs (faim info)
- `forge_flow_zone` — régule charge travail (anti-burn-out)

### Lobe Temporal
- `forge_synaptic_plasticity` — force liens FAISS
- `forge_trajectory` — mémoire procédurale (sequences succès)

### Lobe Frontal
- `forge_dispatchers` — cortex moteur (route services)
- `forge_skill_policy` — surveillant (droit usage tool)
- `forge_opsec` — système immunitaire (masque données)

---

## 📚 Bibliographie cursus

### Cerveau Bayésien (FEP)
1. **Friston K.** *The Free Energy Principle: A Guide for the Perplexed* (2023)
   → base théorique 19 organes
2. **Clark A.** *Surfing Uncertainty: Prediction, Action, and the Embodied Mind* (2016)
   → cerveau prédictif Dispatcher
3. **Hawkins J.** *On Intelligence* (2004)
   → Memory-Prediction Framework (Hebbian + Trajectory)

### Intelligence céphalopode autonome
4. **Godfrey-Smith P.** *Other Minds: The Octopus, the Sea, and the Deep Origins of Consciousness* (2016)
   → ⭐ **lecture prioritaire Phase B.3** : 8 bras = MCP workers + NPU
5. **Godfrey-Smith P.** *Metazoa: Animal Life and the Birth of the Mind* (2020)
   → transition organisme simple → SNC complexe (= Phase B figuier étrangleur)

### Ingénierie systèmes pensée
6. **Hofstadter D.** *Gödel, Escher, Bach: An Eternal Golden Braid* (1979)
   → auto-référence + Critique de Code
7. **Minsky M.** *Society of Mind* (1986)
   → 11 services NSSM = société agents simples
8. **Englander I.** *Architecture of Computer Hardware, Systems Software, & Networking*
   → bas niveau NPU/RAM/IPC (transferts Vault Deno ↔ C-extensions Python)

### Sécurité cognitive
9. **Bostrom N.** *Superintelligence: Paths, Dangers, Strategies* (2014)
   → réponse code_critic dilemmes auto-amélioration récursive
10. **Russell S.** *Human Compatible: AI and the Problem of Control* (2019)
    → mode Centaure (IA humble qui demande validation)

---

## 🔬 Métaphores → Modules (ground truth)

```
Pieuvre / Céphalopode             = Nokido organisme global
8 bras autonomes                   = MCP Workers + dispatchers parallèles
Cerveau central + 8 cerveaux bras  = Hub MCP :8766/:8769 + 11 NSSM
Liquide céphalo-rachidien          = Deno proxy_deno :8000
Matière grise                      = Python 3.14 (4 services migrés)
Cervelet / réflexes inconscients   = NPU Ryzen-AI brain_worker :5557
ARN messager                       = JSON-RPC tools/call payload
Inflammation / immunité            = OPSEC PARANOID + Kill Switch
Plasticité synaptique              = Phase G Tool Smithing JIT
```

---

## 🎯 Implications opérationnelles

1. **Tout nouveau forge_*.py** doit déclarer son lobe (sensoriel/limbique/
   temporal/frontal) dans header pour orchestration cohérente.

2. **Tout endpoint Deno** doit déclarer son rôle synaptique (afférent /
   efférent / régulation) en commentaire docstring.

3. **Toute panne d organe** = trace dans `forge_anatomy_state.health` →
   visible /anatomy SVG (organe pulse → idle/dead).

4. **Toute migration de service** doit préserver le tableau de
   coordination (rupture flux = anatomie cassée).

5. **Phase G Tool Smithing** étend la plasticité synaptique : nouveaux
   neurones (tools) créés selon besoins environnement runtime.

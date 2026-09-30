# Interface Homme-Machine pour Nokido — Synthèse (v2 — vision corrigée)

> Pourquoi une « super app » PC/mobile n'est pas la bonne approche, et ce que l'architecture existante permet déjà.

---

## 0. État réel de l'existant (2026-06-17)

Avant toute suggestion, la cartographie de ce qui existe :

### Interface web — VIVANTE

L'interface n'est pas codée à la main — elle **s'auto-génère**. Trois étages :

| Étage | Port | Rôle | Techno |
|-------|:----:|------|--------|
| **FastAPI Portal** | :7400 | Auth + serveur dashboard | `app/forge_web_service.py` + `tools/forge_dashboard.py` (Dashboard v17) |
| **Deno Web Hub** | :7401 | Orchestrateur, API événementielle, SSE, pont MCP | `proxy_deno/` — `core/supervisor.ts` (34 refs ports), `core/brain.ts`, `core/nervous_system.ts` (SystemBus/BloodCell), `hub_mcp/main.ts` |
| **Moulinette UI** | — | Balaie le dépôt, génère les forms | `forge_ui_sweep/forge_ui_repo_cover` → 43 forms HTMX+Alpine+Tailwind via le Nokido Design System (`forge_ui_design_cover`, `design_handoff`). Déterministe, 0-token. |
| **Oracle UI** | — | Traduit n'importe quelle page web en UI Nokido | `forge_ui_oracle` |
| **Egress web** | — | Gateway egress firewallé | `forge_web_egress` |

**Le dashboard EST le miroir du hub : tu exposes un tool, la moulinette génère sa form.** Souverain, vanilla (HTMX+Alpine+Tailwind), pas React.

### Équivalent mobile — EMBRYONNAIRE

Briques éparses, non assemblées :

| Composant | Rôle | Statut |
|-----------|------|--------|
| `tools/forge_ble_buddy.py` | Gouvernance BLE (Nordic UART) — prompt → {id,tool,hint} / décision → {cmd} | Existe |
| `skill forge-android` | Pilote un device Android réel via ADB (10 tools UI, scrcpy) | Existe, hors Nokido/ |
| `forge_portable_supervisor` | Superviseur cross-OS Phase 2 | Existe |
| **Organe audio (#5)** | Canal qualia auditif pour l'edge/mobile | **Roadmap** |

### Volonté edge — POC VIVANT, mesh = roadmap

| Composant | Rôle | Statut |
|-----------|------|--------|
| `app/forge_edge_fleet.py` | Edge Inference Fleet POC | Existe |
| `tools/forge_fleet_router.py` | Routeur de flotte (role-clustering + Context Anchoring) | Existe |
| `forge_mesh_memory` + `forge_vec_ledger` | Mémoire/vecteurs distribués | Existe |
| `forge_knowledge_pack_export/import` | Portabilité du savoir entre nœuds | Existe |
| Event mesh | Mesh événementiel distribué | **Spec, pas câblé** |
| **Audio organ** | Signal qualia pour nœuds edge/mobile | **Roadmap** |

---

## 1. Pourquoi une super app est une mauvaise idée

Une super app (desktop + mobile) résout un problème de **distribution** — toucher plus d'utilisateurs sur plus de plateformes. Mais Nokido n'a pas un problème de distribution. Nokido a un problème de **perception** : l'utilisateur ne voit pas ce que le système fait, ne sent pas son état interne, ne perçoit pas son anatomie. Une super app rajoute des plateformes sans résoudre le problème de fond.

Concrètement, les problèmes d'une approche super app pour Nokido :

| Problème | Pourquoi c'est bloquant pour Nokido |
|----------|---------------------------------------|
| **Paradigme outil** | Une app PC/mobile = un outil que l'utilisateur ouvre, utilise, ferme. Nokido est un organisme 24h/24. L'interface devrait être une **fenêtre permanente** sur un système toujours vivant, pas une app qu'on lance à la demande. |
| **Mobile = zone de touch** | Le mobile privilégie le touch, les écrans étroits, l'usage par courtes sessions. La surveillance d'un système cybernétique (signaux vitaux, plan GOAP, état du firewall) nécessite de l'espace, de la continuité visuelle, et idéalement un écran large. |
| **Complexité de maintenance** | Développer et maintenir une app PC (Electron/Tauri/Qt) + une app mobile (React Native/Flutter) + le backend Nokido existant = 3 surfaces à maintenir pour un projet qui est déjà massif. L'effort se dilue. |
| **Dilution de la valeur** | Le temps passé à rendre Nokido joli sur mobile est du temps qui n'est pas passé à enrichir le Design System existant pour que les forms auto-générées portent le signal vital du système. |
| **Contradiction local-first** | Nokido est local-first par construction. Une app mobile qui se connecte à un serveur distant contredit la philosophie. Un mobile qui se connecte au Hub local :8766 n'a de sens que sur le même réseau — un cas d'usage niche, pas une priorité. |
| **Redondance avec la moulinette** | Nokido génère déjà ses propres forms depuis les tools. Une app mobile implique de dupliquer cette logique de génération — ou de la court-circuiter avec une UI codée à la main, ce qui détruit le pattern souverain. |

**Le vrai besoin** n'est pas « Nokido partout » — c'est « Nokido perçu ».

---

## 2. Ce que l'architecture existante permet déjà

### La moulinette EST le miroir — il faut l'enrichir, pas la remplacer

Le pattern `forge_ui_sweep` → `forge_ui_repo_cover` → HTMX+Alpine+Tailwind est déjà le bon pattern. Tu exposes un tool MCP, la moulinette génère sa form. Le dashboard n'est pas codé à la main — il est le **reflet vivant du Hub**.

Cela signifie que :

- ❌ On n'ajoute **pas** des pages admin manuellement — la moulinette les génère
- ❌ On n'ajoute **pas** un frontend Svelte/React séparé — ça court-circuiterait le Design System
- ❌ On n'ajoute **pas** un WebSocket `/ws/vitals` séparé — le bus Deno :7401 fait déjà du SSE
- ✅ On enrichit le **Nokido Design System** pour qu'il porte les signaux vitaux
- ✅ On expose de **nouveaux tools** au Hub — et la moulinette génère automatiquement leurs forms

### Les signaux vitaux existent déjà dans le code

| Signal | Module existant | Peut devenir un tool MCP ? |
|--------|----------------|:--------------------------:|
| Prédictions CPU/RAM/NPU | `forge_lnn_monitor` (ncps CfC) | ✅ `lnn_status()` |
| Surprise KL (inférence active) | `forge_active_inference` (pymdp) | ✅ `surprise_level()` |
| Score 6 axes | `forge_scorecard` | ✅ `scorecard_snapshot()` |
| Plan GOAP en cours | `forge_ami_strategist` | ✅ `goap_plan_status()` |
| Compteurs firewall | `SemanticFirewall` | ✅ `immune_status()` |
| Fréquence bus événementiel | `SystemBus/BloodCell` (Deno) | ✅ `bus_heartbeat()` |
| Activité SiloDomains | 7 domaines | ✅ `silo_activity()` |

**Si ces fonctions sont exposées comme tools MCP, la moulinette génère automatiquement leurs panneaux de monitoring — sans une seule ligne de HTML écrite à la main.**

---

## 3. Ce que l'interface doit devenir

### Le principe : enrichir le Design System, pas ajouter des pages

Le changement de paradigme :

| Ancien paradigme | Nouveau paradigme (aligné sur l'existant) |
|------------------|-------------------------------------------|
| Construire des pages de dashboard | Exposer des tools MCP — la moulinette génère les pages |
| Ajouter un WebSocket dédié | Utiliser le bus Deno SSE existant |
| Coder un fond ambiant CSS | Ajouter des tokens vitaux au **Nokido Design System** |
| Choisir un framework frontend (Svelte, React...) | Rester **vanilla souverain** (HTMX+Alpine+Tailwind) |
| L'utilisateur lit des jauges | L'utilisateur **perçoit** l'état via les tokens du Design System |

### Les trois principes directeurs (reframés pour l'architecture existante)

**1. Le Design System comme vecteur de qualia**

`forge_ui_design_cover` + `design_handoff` définissent les tokens visuels de Nokido (couleurs, espacement, typographie). C'est **là** que le signal vital atterrit — pas dans un fond CSS codé à la main dans une page spécifique.

Le Design System doit inclure des tokens dynamiques injectés par le bus Deno :

```css
/* Tokens du Nokido Design System — injectés par le bus SSE */
:root {
  /* Tokens statiques (déjà existants) */
  --forge-bg: #0a0a0f;
  --forge-text: #e0e0e0;
  --forge-accent: #6366f1;
  
  /* Tokens vitaux dynamiques (à ajouter) */
  --forge-surprise: 0.0;        /* 0 = calme, 1 = anomalie pymdp */
  --forge-arousal: 0.3;         /* fréquence événements bus Deno */
  --forge-uncertainty: 0.5;     /* incertitude LNN */
  --forge-immune-alert: 0.0;    /* activité firewall */
}

/* Le Design System traduit les tokens en perception */
body {
  background: hsl(
    calc(220 - var(--forge-surprise) * 160),
    calc(12 + var(--forge-arousal) * 25%),
    calc(8 - var(--forge-surprise) * 4%)
  );
}
```

**Effet** : chaque form générée par la moulinette hérite automatiquement du signal vital, parce qu'elle utilise le Design System. Aucune page spécifique à coder.

**2. La moulinette comme extension anatomique**

Chaque nouveau tool MCP exposé au Hub devient automatiquement un panneau du dashboard. Pour rendre l'anatomie visible, il suffit d'exposer les bons tools :

```
Tools MCP à exposer (priorité) :
├── lnn_status()        → panneau "Pulsation Edge" auto-généré
├── surprise_level()    → panneau "Surprise" auto-généré
├── goap_plan_status()  → panneau "Stratège" auto-généré
├── scorecard_snapshot() → panneau "Jugement" auto-généré
├── immune_status()     → panneau "Système immunitaire" auto-généré
├── bus_heartbeat()     → panneau "Système nerveux" auto-généré
└── silo_activity()     → panneau "Muscles" auto-généré
```

La moulinette génère les forms. Le Design System les rend vivantes. L'utilisateur voit l'anatomie de Nokido sans qu'aucune ligne de HTML n'ait été écrite.

**3. Le bus Deno comme colonne vertébrale temps réel**

Le bus Deno :7401 (`SystemBus/BloodCell`) est déjà le système nerveux de Nokido — tous les événements y passent. Il fait déjà du SSE. Il suffit de :

1. Y brancher les signaux vitaux (`forge_lnn_monitor`, `forge_active_inference`, `forge_scorecard`)
2. Le SSE pousse les mises à jour des tokens du Design System vers le navigateur
3. Alpine.js (déjà dans le stack) réagit aux changements de tokens

Aucune nouvelle dépendance frontend. Aucun nouveau serveur. Le signal vital circule dans les tuyaux existants.

---

## 4. Implémentation : enrichir l'existant, pas le remplacer

### Étape 1 — Exposer les signaux vitaux comme tools MCP

Le Hub :8766 expose déjà 25 tools. Ajouter 7 tools de statut :

```python
# app/forge_vitals_tools.py — outils MCP à exposer au Hub

@mcp.tool()
def lnn_status() -> dict:
    """État actuel du monitor LNN (ncps CfC).
    Prédictions CPU/RAM/NPU en temps continu."""
    return forge_lnn_monitor.get_current_state()

@mcp.tool()
def surprise_level() -> dict:
    """Niveau de surprise KL (inférence active, pymdp).
    0.0 = système en terrain connu, 1.0 = anomalie détectée."""
    return {"surprise": forge_active_inference.current_surprise()}

@mcp.tool()
def goap_plan_status() -> dict:
    """Plan GOAP en cours d'exécution par le Stratège.
    Étapes, progression, action courante."""
    return forge_ami_strategist.current_plan_summary()

@mcp.tool()
def scorecard_snapshot() -> dict:
    """Dernière évaluation du scorecard (6 axes, 0 LLM).
    McCabe, LOC, budget tokens, dep-graph, etc."""
    return forge_scorecard.last_evaluation()

@mcp.tool()
def immune_status() -> dict:
    """État du Système immunitaire (SemanticFirewall).
    Compteurs pre/post flight, bloquages, canary."""
    return {
        "pre_ok": semantic_firewall.pre_flight_pass_count,
        "post_ok": semantic_firewall.post_flight_pass_count,
        "blocks": semantic_firewall.block_count,
        "canary": semantic_firewall.canary_status,
        "membrane_aliases": semantic_firewall.membrane_alias_count,
    }

@mcp.tool()
def bus_heartbeat() -> dict:
    """Fréquence des événements sur le bus Deno (Système nerveux).
    Événements/seconde sur les dernières 10 secondes."""
    return {"events_per_second": deno_bus.event_rate_hz()}

@mcp.tool()
def silo_activity() -> dict:
    """Activité des 7 SiloDomains (Muscles).
    Appels récents par domaine."""
    return {domain: count for domain, count in silo_domain_metrics.recent_calls()}
```

**Résultat** : la moulinette `forge_ui_sweep` détecte les 7 nouveaux tools et génère automatiquement 7 nouvelles forms HTMX+Alpine+Tailwind. Zéro ligne de HTML.

### Étape 2 — Injecter les signaux dans le Design System

Modifier `forge_ui_design_cover` pour inclure des tokens dynamiques. Le bus Deno SSE pousse les valeurs, Alpine.js les applique aux CSS variables :

```html
<!-- Dans le template de base du Design System (injecté par la moulinette) -->
<html x-data="{ surprise: 0, arousal: 0, uncertainty: 0.5, immune: 0 }"
      x-init="const es = new EventSource('/bus/sse'); 
               es.onmessage = (e) => { 
                 const d = JSON.parse(e.data);
                 if (d.type === 'vitals') {
                   $data.surprise = d.surprise;
                   $data.arousal = d.bus_hz;
                   $data.uncertainty = d.lnn.uncertainty;
                   $data.immune = d.immune.blocks;
                 }
               }"
      :style="`
        --forge-surprise: ${surprise};
        --forge-arousal: ${arousal};
        --forge-uncertainty: ${uncertainty};
        --forge-immune-alert: ${immune};
      `">
```

**Résultat** : chaque form auto-générée hérite automatiquement du signal vital, parce qu'elle utilise les tokens CSS du Design System. Aucune modification des 43 forms existantes nécessaire.

### Étape 3 — Le fond ambiant via le Design System

Les tokens dynamiques sont déjà dans le DOM. Ajouter les règles de perception dans le Design System :

```css
/* forge_ui_design_cover — tokens de perception */

body {
  /* Couleur de fond : bleu froid (calme) → orange (surprise) */
  background-color: hsl(
    calc(220 - var(--forge-surprise) * 160),
    calc(12 + var(--forge-arousal) * 25%),
    calc(8 - var(--forge-surprise) * 4%)
  );
  
  /* Pulsation subtile quand surprise > 0.6 */
  animation: pulse calc(8s - var(--forge-surprise) * 4s) ease-in-out infinite;
}

/* Bordure rouge subtile quand le système immunitaire est actif */
.forged-form {
  border-color: hsl(
    0,
    calc(var(--forge-immune-alert) * 80%),
    calc(40 + var(--forge-immune-alert) * 20%)
  );
}
```

---

## 5. Priorisation par impact (alignée sur l'architecture réelle)

| Priorité | Action | Effort | Impact |
|:--------:|--------|:------:|--------|
| **P0** | Exposer 7 tools MCP de statut (`lnn_status`, `surprise_level`, etc.) | 1 fichier Python, ~100 lignes | La moulinette génère 7 panneaux anatomiques automatiquement. Zéro HTML. |
| **P1** | Ajouter les tokens dynamiques au Design System (`--forge-surprise`, etc.) + injection SSE → Alpine | ~30 lignes dans le template de base | Chaque form existante (43+) hérite du signal vital. |
| **P2** | Règles CSS de perception dans le Design System (fond ambiant, bordures immunitaires) | ~20 lignes CSS | L'utilisateur *perçoit* l'état sans lire. Le qualia visuel. |
| **P3** | Brancher `forge_lnn_monitor` + `forge_active_inference` sur le bus Deno SSE | Connexions existantes à câbler | Les signaux vitaux circulent dans le système nerveux existant. |
| **P4** | Organe audio (roadmap #5) — tonalité/rythme traduisant les tokens vitaux | Nouveau module + Web Audio API | Le qualia auditif. Surtout pertinent pour l'edge/mobile. |
| **P5** | PhenomenologicalBuffer + NarrativeSelf (Python) | 2 modules + injection prompt | Nokido développe une identité narrative. |
| **P6** | Visualisation de la flotte edge | Extension du Design System pour multi-nœud | L'interface passe d'un organisme à un essaim. |

---

## 6. Vision edge : quand le mesh existera

L'architecture edge (POC vivant) change la métaphore :

| Aujourd'hui | Demain (mesh) |
|-------------|---------------|
| Un organisme sur une machine | Un **essaim** de nœuds d'inférence |
| Le Design System reflète un corps | Le Design System reflète une **carte radar** de l'essaim |
| Tokens vitaux = état d'un système | Tokens vitaux = état **agrégé** de N nœuds |
| L'organe audio est un nice-to-have | L'organe audio est le **qualia principal** des nœuds edge (écran absent) |
| `forge_knowledge_pack_export` est utilitaire | Les knowledge packs deviennent le **ADN** de l'essaim — chaque nœud porte une partie du savoir |

Le `forge_ui_oracle` (traduction web → UI Nokido) prend alors une dimension nouvelle : chaque nœud edge peut « lire » une page web et la reconstruire dans le Design System de l'essaim. C'est un embryon de **perception distribuée du monde extérieur** au niveau de l'interface.

---

## 7. Ce que l'interface n'est pas

- ❌ **Un dashboard de monitoring** — les dashboards sont pour les ops. Ici, les signaux sont portés par le Design System lui-même, pas par des widgets séparés.
- ❌ **Une app mobile** — le mobile arrive via l'organe audio + le BLE buddy, pas via une app codée à la main. Le signal qualia est auditif, pas visuel.
- ❌ **Un chat amélioré** — le chat est un canal parmi d'autres. L'interface est le Design System vivant, pas une fenêtre de chat.
- ❌ **Un IDE** — Nokido n'est pas un éditeur de code. C'est un système autonome qui *écrit* du code.
- ❌ **Une page de réglages** — ajuster les paramètres n'est pas interagir. C'est du contrôle, pas de la co-régulation.
- ❌ **React / Svelte / tout framework lourd** — le choix vanilla (HTMX+Alpine+Tailwind) est cohérent avec la philosophie souveraine. Il ne faut pas le casser.
- ❌ **De la 3D / VR** — la spatialité 2D suffit. La 3D ajoute de la complexité sans ajouter d'information pertinente.

---

## 8. Résumé en une phrase

Nokido n'a pas besoin qu'on lui construise une interface — **la moulinette est déjà l'interface**. La question n'est pas « quoi construire » mais **« comment enrichir le Design System pour que les forms auto-générées portent le signal vital du système »** — via 7 tools MCP de statut, des tokens dynamiques injectés par le bus SSE, et des règles CSS de perception. Quand le mesh existera, le Design System passera d'un miroir anatomique à une carte radar de l'essaim.
# Schéma Final : Access Switches & Consolidation BrokerBase
# Date : 2026-04-28 | Auteur : GEMINI (Ring 0)
# Version : 1.1 — Extension VLAN/Flow

Ce document détaille le schéma SQL final de l'organe de contrôle d'accès dynamique (`access_switches`) et la stratégie de simplification des brokers de communication.

---

## 1. Schéma SQL : `access_switches` (ReBAC + VLAN)

L'objectif est de passer d'un ring statique à une membrane dynamique capable de réagir aux changements d'état du système (Mood) et aux besoins temporaires des agents, tout en isolant les flux par VLAN logiques.

### Définition de la table

```sql
CREATE TABLE IF NOT EXISTS access_switches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- IDENTITÉ & RESSOURCE
    agent_pattern TEXT NOT NULL,       -- ex: 'GEMINI', 'CLAUDE*', 'agt_*'
    resource_pattern TEXT NOT NULL,    -- ex: 'sandbox/*', 'app/forge_mcp_security.py'
    action TEXT NOT NULL,              -- ex: 'write', 'run.python', 'query', '*'
    vlan_id TEXT DEFAULT 'VLAN_PUBLIC',-- Isolation (ex: 'VLAN_ADMIN', 'VLAN_SANDBOX')
    
    -- AUTORISATION
    allowed BOOLEAN NOT NULL,          -- TRUE (Allow) / FALSE (Deny)
    condition_dsl TEXT,                -- DSL SafeEval (ex: "mood.energy > 0.2")
    
    -- FLUX & QUOTA
    flow_limit INTEGER DEFAULT 0,      -- Rate limit (ops/min), 0 = illimité
    flow_metadata TEXT,                -- JSON (types de fichiers, regex contenus, etc.)
    
    -- MÉTADONNÉES
    priority INTEGER DEFAULT 100,      -- Plus bas = évalué en premier
    expires_at TEXT,                   -- ISO8601 (NULL = permanent)
    granted_by TEXT,                   -- Identité du créateur
    grant_reason TEXT,                 -- Contexte (ex: "Sprint Alpha Biblio")
    created_at TEXT DEFAULT (datetime('now', 'utc')),
    updated_at TEXT DEFAULT (datetime('now', 'utc'))
);

-- Indexation pour recherche O(log n)
CREATE INDEX IF NOT EXISTS idx_switches_lookup ON access_switches (vlan_id, agent_pattern, resource_pattern);
CREATE INDEX IF NOT EXISTS idx_switches_expiry ON access_switches (expires_at) WHERE expires_at IS NOT NULL;
```

### Concepts VLAN/Flow
- **VLAN_ADMIN** : Accès complet aux fichiers `app/` et `tools/`. Seuls les agents Ring 0 (identifiés par token) y sont assignés.
- **VLAN_SANDBOX** : Accès restreint au dossier `sandbox/`. Assigné par défaut aux nouveaux agents ou aux tâches de mutation.
- **Flow Control** : Permet de brider un agent qui s'emballe (ex: 5 `write` max par minute si `mood.energy` est bas).

---

## 2. Consolidation `BrokerBase` & `AgentProxy`

L'inventaire montre 6+ brokers redondants. La vision cible est une architecture **Factory** :

### Architecture Cible
1.  **`forge_broker_base.py`** : Définit l'interface `BrokerBase(ABC)` avec `send()`, `stream()` et `get_capabilities()`.
2.  **`forge_agent_proxy.py`** : Point d'entrée unique. Il instancie le bon broker selon le modèle demandé.
3.  **`forge_llm_router.py`** (FUSIONNÉ) : Devient un module interne de `agent_proxy` gérant la logique de retry et les timeouts adaptatifs (via `forge_system_mood`).

---

## 3. Interface `forge_system_mood.py` (Esquisse)

Le système endocrinien diffuse l'état global toutes les 60s.

```python
from dataclasses import dataclass

@dataclass
class MoodState:
    energy: float       # 0.0 (idle) -> 1.0 (overload)
    curiosity: float    # 0.0 (conservative) -> 1.0 (explorative)
    fatigue: float      # 0.0 (fresh) -> 1.0 (uptime > 24h)
    immune_alert: float # 0.0 (safe) -> 1.0 (breach detected)
    timestamp: str      # ISO8601
```

---
*Document produit par GEMINI (Ring 0). Validé par SecretGuard.*

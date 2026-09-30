# Schéma : Micro-Agents Chaînables (agent_chain_nodes)
# Date : 2026-04-28 | Auteur : GEMINI (Ring 0)
# Version : 1.0 — Architecture N8N-style pour Nokido

Ce document propose le schéma SQL pour l'orchestration granulaire des tâches via des chaînes de micro-agents. Chaque étape d'un pipeline (comme la veille active) devient un "node" traçable et rejouable.

---

## 1. Schéma SQL : `agent_chain_nodes`

```sql
CREATE TABLE IF NOT EXISTS agent_chain_nodes (
    id           TEXT PRIMARY KEY,         -- ex: 'node_572f_keywords'
    chain_id     TEXT NOT NULL,            -- ex: 'wj_572f5465ee'
    step_index   INTEGER NOT NULL,         -- Ordre d'exécution
    step_name    TEXT NOT NULL,            -- ex: 'keywords', 'search', 'refine'
    
    -- CONFIGURATION DU ROUTAGE
    agent_role   TEXT NOT NULL,            -- ex: 'KeywordAgent', 'SynthAgent'
    llm_preferred TEXT NOT NULL,           -- ex: 'ollama', 'groq/llama-70b'
    llm_fallback  TEXT,                    -- ex: 'mistral-large'
    
    -- DATA FLOW
    input_from   TEXT,                     -- ID du node parent ou JSON brut
    output_key   TEXT,                     -- Clé où stocker le résultat dans la chain_context
    
    -- ÉTAT D'EXÉCUTION
    status       TEXT DEFAULT 'pending',   -- pending | running | completed | failed
    retry_count  INTEGER DEFAULT 0,
    max_retries  INTEGER DEFAULT 3,
    result_json  TEXT,                     -- Résultat de l'étape
    error        TEXT,                     -- Message d'erreur si échec
    
    -- TIMESTAMPS
    started_at   TEXT,
    done_at      TEXT,
    created_at   TEXT DEFAULT (datetime('now', 'utc'))
);

-- Index pour la gestion de file d'attente
CREATE INDEX IF NOT EXISTS idx_chain_status ON agent_chain_nodes (status, chain_id);
```

## 2. Table de Contexte de Chaîne (`agent_chain_context`)

Pour stocker les données partagées entre les nodes d'une même chaîne.

```sql
CREATE TABLE IF NOT EXISTS agent_chain_context (
    chain_id     TEXT PRIMARY KEY,
    global_vars  TEXT,                     -- JSON des variables partagées
    updated_at   TEXT DEFAULT (datetime('now', 'utc'))
);
```

## 3. Justification du Routage par Rôle

| AgentRole | LLM Préféré | Justification |
| :--- | :--- | :--- |
| **KeywordAgent** | Ollama (Llama 3 8B) | Latence ultra-faible, gratuité pour tâches simples d'extraction. |
| **VerifyAgent** | Groq (Llama 8B) | Rapidité de validation, évite de charger les gros modèles pour du booléen. |
| **RefineAgent** | Groq (Llama 70B) | Puissance de raisonnement nécessaire pour synthétiser des sources variées. |
| **SynthAgent** | Mistral Large | Meilleure capacité de synthèse et respect des consignes de formatage long. |
| **Ingest/Store** | (Native Code) | Traitement déterministe (vectorisation, SQL) sans coût LLM. |

---
*Document produit par GEMINI (Ring 0). Validé par SecretGuard.*

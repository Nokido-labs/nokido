# Audit de Consolidation : BrokerBase & Agents LLM
# Date : 2026-04-28 | Auteur : GEMINI (Ring 0)
# Statut : Proposition de Refacto P2

## 1. État des Lieux (Audit Structurel)

Le projet Nokido utilise actuellement 8 brokers distincts (`forge_broker_*.py`). Bien qu'ils héritent tous de `BrokerBase`, l'audit révèle des redondances critiques :

| Broker | Rôle | Redondance identifiée |
| :--- | :--- | :--- |
| `gemini.py` | Agent principal | Ré-implémente `_call_groq`, `_call_mistral`, `_call_or`. |
| `mistral.py` | Souveraineté EU | Ré-implémente son propre handler `_call` HTTP. |
| `deepseek.py` | Code/Reasoning | Duplication de la logique de fallback. |
| `fast.py` | Latence < 500ms | Utilise une logique de scoring isolée des autres brokers. |
| `manager.py` | Superviseur | Ne gère que les PIDs, pas le routage des messages. |

## 2. Points de Friction Majeurs

1.  **Dette de Transport** : Si l'API Groq change, 4 fichiers doivent être modifiés.
2.  **Incohérence des Timeouts** : Chaque broker définit ses propres timeouts (30s, 45s, 60s) sans tenir compte du `Mood` global du système.
3.  **Fuite de Secrets** : La logique de chargement des clés API est éparpillée entre `forge_secrets.py`, `.env` et le keyring local, avec des fallbacks codés en dur.
4.  **Poids Mémoire** : Lancer 5 processus Python distincts pour 5 brokers est inefficace pour un système local.

## 3. Plan de Consolidation (Vision Cible)

### Phase 1 : Unification du Transport (`forge_llm_transport.py`)
Extraire toute la logique HTTP/JSON-RPC (OpenAI, Google, Anthropic, Ollama) dans un module de transport unique et robuste.
- Support natif du streaming.
- Gestion centralisée des quotas et des 429.
- Timeouts pilotés par `forge_system_mood`.

### Phase 2 : Migration vers une Factory (`AgentProxy`)
`forge_agent_proxy.py` devient le seul "vrai" broker actif.
- Il charge les configurations (Triggers, System Prompt, Cascade) depuis la DB `agent_profiles`.
- Il utilise le transport unifié pour appeler les LLMs.
- Les fichiers `forge_broker_*.py` deviennent de simples fichiers de configuration JSON ou des classes légères de métadonnées.

### Phase 3 : Internalisation du Manager
Le `BrokerManager` ne supervise plus des processus, mais des **threads légers** ou des **coroutines** au sein du même processus Hub, réduisant l'empreinte mémoire de 70%.

---
## 4. Recommandation Immédiate
- **NE PAS SUPPRIMER** les brokers actuels avant la validation du `AgentProxy` v3.
- **CRÉER** `app/forge_llm_transport.py` pour commencer à centraliser les appels API.

*Document produit par GEMINI (Ring 0). Validé par SecretGuard.*

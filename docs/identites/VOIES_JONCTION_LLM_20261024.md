# VOIES DE JONCTION LLM NON MESURÉES (2026-10-24)

Ordre owner : « TOUS les LLM joignables via le cloud, avec toutes les méthodes de jonction ». 
Travail dans : `nokido_worktrees/opencode_gptoss` (chemins relatifs).

## 1) Voies de jonction identifiées

### A) API directe / OpenAI-compatible (via `app/forge_agent_proxy.py`)
| Voie | Fichier:ligne | Clé (nom uniquement) | Outil de mesure | Commande exacte pour mesurer |
|---|---|---|---|---|
| `groq` (OpenAI-compat) | `app/forge_agent_proxy.py:1123-1172` (classe `Groq`) | `GROQ_API_KEY` | `tools/forge_free_tier_census.py` (catalogue + sonde), `tools/forge_provider_catalogue.py` (`/models` + matrice), `tools/forge_cli_swarm.py` (membres vivants) | `LAFORGE_PYTHON tools/forge_free_tier_census.py --cible groq:<modele>` ; `LAFORGE_PYTHON tools/forge_provider_catalogue.py` (interroge tous FOURNISSEURS) ; `LAFORGE_PYTHON tools/forge_provider_catalogue.py --matrice` |
| `openrouter` / variantes (`openrouter_glm5`, `openrouter_mimo_v2`, etc.) | `app/forge_agent_proxy.py:915-2030` | `OPENROUTER_API_KEY` | idem | idem (cible `openrouter:<slug>`), `forge_free_tier_census` lit aussi quota via `/key` |
| `cerebras` | `app/forge_agent_proxy.py:2091-2125` | `CEREBRAS_API_KEY` | idem | idem |
| `sambanova` | `app/forge_agent_proxy.py:1766-1806` | `SAMBANOVA_API_KEY` | idem | idem |
| `together_ai` | `app/forge_agent_proxy.py:2051-2090` | `TOGETHER_API_KEY` | idem | idem |
| `mistral` / `mistral_free` | `app/forge_agent_proxy.py:2126-2164` + routeur | `MISTRAL_API_KEY` | idem | idem |
| `nvidia_nim` | `app/forge_agent_proxy.py:2189-2220` | `NVIDIA_API_KEY` / `NVIDIA_NIM_API_KEY` | idem | idem |
| `deepseek` | via proxy/routeur (référencé dans registre) | `DEEPSEEK_API_KEY` | idem | idem |
| `hf` / `huggingface` | via proxy/routeur | `HF_TOKEN` | idem | idem |
| `xai`/`grok` | via proxy/routeur | `XAI_API_KEY` | idem | idem |
| `zai` | via proxy/routeur | `ZAI_API_KEY` | idem | idem |
| `pollinations` | `app/forge_agent_proxy.py:2219-2285` | (clé optionnelle selon endpoint) | idem (sonde catalogues si OpenAI-compat) | idem (si exposé OpenAI-compat) |
| `claude` via OpenRouter | `app/forge_agent_proxy.py:901-964` (`ClaudeOpenRouter`) | `OPENROUTER_API_KEY` | idem | idem |
| `gemini` (Google GenAI direct) | `app/forge_agent_proxy.py:1010-1065` (`Gemini`, `GeminiFlashLite`, `GeminiGemma`) | `GEMINI_API_KEY` | idem | idem (sonde directe ou via catalogue si OpenAI-compat) |

### B) Proxy / Registre unifié du hub
| Voie | Fichier:ligne | Clé (nom uniquement) | Outil de mesure | Commande exacte pour mesurer |
|---|---|---|---|---|
| `forge_agent_proxy.ask` (registre `Provider` + `_PROVIDERS`) | `app/forge_agent_proxy.py:1-3000+` (classes + registre) | dépend du provider (cf A) | `tools/forge_free_tier_census.py` (sonde via proxy/route), `tools/forge_provider_catalogue.py --matrice` (confronte familles), `tools/forge_cli_swarm.py` | idem + `LAFORGE_PYTHON tools/forge_cli_swarm.py "<task>"` pour tester membres vivants |
| Routeur / cascade | `app/forge_llm_router.py` (PROVIDERS/USE_CASE_CHAINS/call_cascade) | idem | `tools/forge_free_tier_census.py` (cible swarm:forge_agent_proxy / swarm:free_tier), `tools/forge_provider_catalogue.py --matrice` | `LAFORGE_PYTHON tools/forge_free_tier_census.py --dimensions swarm:forge_agent_proxy --bancs code,raisonnement --dry-run` (plan) / exécution selon bancs |
| Alias / mapping hub->exécutable | `app/forge_provider_alias.py` | N/A (mapping) | AUCUN (métadonnées) | AUCUN |

### C) CLI OAuth / abonnements (mesurés comme voies d’accès)
| Voie | Fichier:ligne | Clé (nom uniquement) | Outil de mesure | Commande exacte pour mesurer |
|---|---|---|---|---|
| `claude_cli` | `app/forge_agent_proxy.py:1680-1747` | (OAuth/CLI, pas de clé API classique) | `tools/forge_cli_swarm.py` (membres), `tools/forge_provider_catalogue.py --matrice --cli claude_cli,...` (compétence CLI), `tools/forge_free_tier_census.py` (SURFACES_CIBLES cli:*) | `LAFORGE_PYTHON tools/forge_provider_catalogue.py --matrice --cli gemini_cli,opencode` ; `LAFORGE_PYTHON tools/forge_cli_swarm.py "<task>" claude_cli,...` |
| `gemini_cli` (client MORT depuis le 04/07, exclu par EXCLUS_PROXY ; AGY est une autre surface, non cablee ici) | `app/forge_agent_proxy.py:1490-1560` | idem | idem | idem |
| `copilot_cli` | `app/forge_agent_proxy.py:2347+` (classe CopilotCLI) | idem (GitHub OAuth) | idem | idem |
| `codex_cli` | via proxy/routeur | idem | idem | idem |
| `opencode` (zen) | référencé dans CLI defaults/tests | idem | idem (`--cli opencode`) | idem |

### D) Passerelles / agrégateurs
| Voie | Fichier:ligne | Clé (nom uniquement) | Outil de mesure | Commande exacte pour mesurer |
|---|---|---|---|---|
| LiteLLM (SDK direct / proxy) | `app/forge_litellm_bridge.py:1-347`, `app/forge_litellm_connector.py:1-336`, `app/forge_litellm_router.py` | varie par backend (cf env) | AUCUN outil dédié dans les 3 cités | À étendre : utiliser `forge_provider_catalogue.py` en mode agrégé ou ajouter sonde via `litellm.completion` dans `forge_free_tier_census.py` |
| OpenRouter (agrégateur) | cf A | `OPENROUTER_API_KEY` | couvert | cf A |
| Pollinations | `app/forge_agent_proxy.py:2219-2285` | optionnel | partiel | idem |

### E) Ollama / locaux + Ollama Cloud
| Voie | Fichier:ligne | Clé (nom uniquement) | Outil de mesure | Commande exacte pour mesurer |
|---|---|---|---|---|
| Ollama local (`ollama`) | `app/forge_agent_proxy.py:27,2620`, `app/forge_ollama_bridge.py`, `app/forge_litellm_bridge.py` | (aucune / locale) | `tools/forge_free_tier_census.py` (SURFACES inclut ollama/lmstudio/litellm locaux), `tools/forge_provider_catalogue.py` (local http://127.0.0.1:11434/v1/models), `tools/forge_cli_swarm.py` | `LAFORGE_PYTHON tools/forge_free_tier_census.py` ; `LAFORGE_PYTHON tools/forge_provider_catalogue.py` |
| LMStudio / LlamaCpp | idem | idem/locale | idem | idem |
| Ollama Cloud (proxy agent) | `tools/ollama_cloud_proxy_agent.py:1-214` | `OLLAMA_API_KEY`, `FORGE_MCP_TOKEN` | **AUCUN** (agent local qui relaie vers URL cloud configurable) | **À étendre** : ajouter sonde dans `forge_provider_catalogue.py` (mode URL custom) ou dans `forge_free_tier_census.py` (surface `ollama_cloud`) |
| LiteLLM proxy local | `app/forge_litellm_connector.py:53-66,154-165` | `FORGE_MCP_TOKEN` / clés backend | **AUCUN** | idem |

### F) Autres surfaces mentionnées / candidates
| Voie | Fichier:ligne | Clé (nom uniquement) | Outil de mesure | Commande exacte pour mesurer |
|---|---|---|---|---|
| Cloudflare Workers AI | non trouvé comme connecteur direct dans grep ciblé (référencé dans HORS_PERIMETRE `forge_provider_catalogue.py:80`) | `CLOUDFLARE_AI_API_KEY` | **AUCUN** (hors périmètre catalogue actuel) | **À étendre** `forge_provider_catalogue.py` (ajouter fournisseur avec endpoint spécifique Workers AI) |
| Bedrock / Vertex | non trouvé comme connecteur direct | clés AWS/GCP | **AUCUN** | idem |
| GitHub Models | retiré (`app/forge_agent_proxy.py:966-1008` classe gelée, `forge_provider_catalogue.py:83` HORS_PERIMETRE) | `GITHUB_TOKEN` / `GITHUB_MODELS_TOKEN` | **AUCUN** (retiré) | N/A |
| Mammouth | référencé dans `forge_agent_proxy.py:60` SURFACES census | `MAMMOUTH_API_TOKEN` | partiel via `forge_free_tier_census.py` SURFACES | `LAFORGE_PYTHON tools/forge_free_tier_census.py` (déjà listé) |
| Vibe/Mistral CLI surfaces | référencés dans configs/tests | N/A | partiel via CLI swarm/census | idem |

## 2) Voies SANS outil de mesure dédié (trous à combler)

Ces voies n'ont **aucun** des 3 outils (`forge_free_tier_census.py`, `forge_provider_catalogue.py`, `forge_cli_swarm.py`) qui les sonde directement :

| Voie | Fichier:ligne | Clé (nom uniquement) | Outil existant à étendre | Proposition d'extension |
|---|---|---|---|---|
| **Ollama Cloud** (`tools/ollama_cloud_proxy_agent.py`) | `tools/ollama_cloud_proxy_agent.py:11-38` | `OLLAMA_API_KEY`, `FORGE_MCP_TOKEN` | `tools/forge_provider_catalogue.py` | Ajouter entrée `ollama_cloud` (URL configurable via `OLLAMA_CLOUD_URL`) dans `FOURNISSEURS` ou mode `--url` ; utiliser `/models` si OpenAI-compat, sinon sonde chat minimal. Ne pas dupliquer logique. |
| **LiteLLM SDK/Proxy** (`app/forge_litellm_bridge.py`, `app/forge_litellm_connector.py`) | `app/forge_litellm_bridge.py:204-278`, `app/forge_litellm_connector.py:154-265` | backend-dependent | `tools/forge_free_tier_census.py` | Étendre `SURFACES` avec `litellm` (déjà présent `:4000/v1`) et ajouter sonde via `litellm.completion` ou HTTP vers proxy `/models`/`/v1/models`. Réutiliser logique existante. |
| **LiteLLM Router** (`app/forge_litellm_router.py`) | `app/forge_litellm_router.py` | idem | `tools/forge_provider_catalogue.py` | Ajouter support pour router local dans matrice (sonde couples via router). Étendre `construire_matrice` sans nouveau module. |
| **Cloudflare Workers AI** | `tools/forge_provider_catalogue.py:80` (HORS_PERIMETRE) | `CLOUDFLARE_AI_API_KEY` | `tools/forge_provider_catalogue.py` | Sortir de HORS_PERIMETRE et ajouter fournisseur avec endpoint Workers AI approprié (selon compte/projet) ; parser `/models` si disponible ou sonde génération. |
| **Bedrock / Vertex AI** | non trouvé | AWS/GCP creds | `tools/forge_provider_catalogue.py` | Ajouter entrées conditionnelles (auth différente) — étendre `interroger/sonder_generation` pour gérer auth non-Bearer si nécessaire, ou sonde via gateway OpenAI-compat si existant. |
| **API direct Gemini (Google GenAI)** | `app/forge_agent_proxy.py:1010-1065` | `GEMINI_API_KEY` | `tools/forge_provider_catalogue.py` | Ajouter sonde spécifique GenAI ou passer par OpenAI-compat si disponible ; sinon étendre `sonder_generation` pour endpoint Google. |
| **Autres CLI non listés** (si nouveaux) | divers | OAuth/CLI | `tools/forge_cli_swarm.py`, `tools/forge_provider_catalogue.py --cli` | Étendre listes CLI_PAR_DEFAUT/EXCLUS_PROXY sans nouveau module. |

## 3) Recommandations (sans modifier code/config)

- **Unifier la mesure** : `forge_provider_catalogue.py` est le bon point d'entrée pour "catalogue + matrice par fournisseur:modèle" ; `forge_free_tier_census.py` pour "gratuit + joignable réel + outils + quota" ; `forge_cli_swarm.py` pour "CLI OAuth vivants".
- **Étendre, pas dupliquer** : pour chaque trou ci-dessus, ajouter au tableau existant (FOURNISSEURS/HORS_PERIMETRE/SURFACES) plutôt que créer un nouveau module.
- **Préserver les règles** : jamais logger de valeur de clé, utiliser suffixe 4 chars, `UNKNOWN != NO`, distinguer catalogue vs génération vs compétence.
- **Ollama Cloud** est la voie la plus visible non couverte : `tools/ollama_cloud_proxy_agent.py` mérite d'être intégré dans `forge_provider_catalogue.py` (mode sonde URL).

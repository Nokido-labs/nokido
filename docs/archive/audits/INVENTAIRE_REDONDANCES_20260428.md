# Inventaire des Redondances et Code Orphelin — 2026-04-28

Rapport généré par **GEMINI** (Ring 0).

## 1. Analyse des Brokers et Proxies

| Fichier | Taille (b) | Statut | Recommandation | Justification |
| :--- | :--- | :--- | :--- | :--- |
| `tools/forge_broker_base.py` | 22733 | **ACTIF** | — | Classe de base (`BrokerBase`) vitale pour tous les agents. |
| `tools/forge_broker_gemini.py` | 8891 | **ACTIF** | — | Broker principal Gemini v18.5 avec cascade et streaming. |
| `tools/forge_collab_broker.py` | 19733 | **DOUBLON** | **A_ARCHIVER** | Version standalone "minimaliste" qui duplique la logique de `forge_broker_gemini.py` sans hériter de la base. |
| `tools/forge_broker_probe.py` | 6376 | **ACTIF** | — | Outil de monitoring distinct (Dashboard/Daemon). Pas un broker. |
| `app/forge_agent_proxy.py` | 39707 | **ACTIF** | — | High-level RPC v2 (April 2026). Supporte 10+ providers. |
| `app/forge_llm_router.py` | 39431 | **A_CONSOLIDER** | **A_FUSIONNER** | Logic LiteLLM redondante avec `agent_proxy`. Devrait être un backend pur de `agent_proxy`. |

## 2. Intelligence et Orchestration

| Fichier | Taille (b) | Statut | Recommandation | Justification |
| :--- | :--- | :--- | :--- | :--- |
| `app/forge_agents.py` | 130966 | **ACTIF** | — | Module central v3 (GREEN). Fusion de roles/scoring/routage. |
| `app/forge_agent_roles.py` | 36782 | **ORPHELIN** | **A_ARCHIVER** | Copie partielle de `forge_agents.py` (BLUE, March 2026). |
| `app/forge_orchestrator.py` | 30903 | **ACTIF** | — | Logique métier Engrid v3 (Silos). |
| `app/forge_dag_runner.py` | 9581 | **ACTIF** | — | Moteur d'exécution générique (DAG). Utilitiaire pour `orchestrator`. |

## 3. Modèles et Shredder fragments

| Fichier | Taille (b) | Statut | Recommandation | Justification |
| :--- | :--- | :--- | :--- | :--- |
| `app/forge_core_models.py` | 64265 | **ACTIF** | — | Structure formelle des classes v3 (GREEN). |
| `app/forge_llm.py` | 18309 | **ORPHELIN** | **A_ARCHIVER** | Fragment généré par `shredder.py`. Contenu dupliqué de `Nokido.py`. |
| `app/forge_ping_monitor.py` | 2763 | **ACTIF** | — | Utilitaire interne async. Complémentaire à `tools/forge_ping_monitor.py`. |

## 4. Recommandations Prioritaires

1.  **Archivage (Move to `_attic/`) :** `forge_collab_broker.py`, `forge_agent_roles.py`, `forge_llm.py`.
2.  **Consolidation :** Aligner `forge_llm_router.py` comme une couche de transport optionnelle pour `forge_agent_proxy.py` afin de supprimer la duplication des configurations de modèles.
3.  **Nettoyage `app/` :** Supprimer les fichiers `tmp_*` et `test_chantier_*` qui polluent l'espace de noms du Hub.

# Inventaire des Briques Architecturales et Redondances — 2026-04-28

Rapport généré par **GEMINI** (Ring 0).

## 1. Catégorisation des Briques

| Brique | Statut | Composants concernés | Recommandation |
| :--- | :--- | :--- | :--- |
| **Gestion DB (SQLite)** | **OBSOLESCENT** | `Nokido.py`, `gerix.py`, `phase5_sniper.py` | Migrer vers `app/forge_db.py` (WAL + PRAGMAs optimisés). |
| **Secrets / API Keys** | **OBSOLESCENT** | `Nokido.env` (lecture manuelle), `os.environ` | Utiliser systématiquement `app/forge_secrets.py` (WCM > .env). |
| **Requêtes HTTP (aiohttp)** | **DÉCORRÉLÉ** | Partout (`loops.py`, `roles.py`, `Nokido.py`) | Centraliser les sessions et timeouts dans un client global (ex: `app/forge_http_client.py`). |
| **Bus d'Événements** | **ÉVOLUTIF** | `forge_state_manager.py` (EventBus) | Finaliser l'adoption de l'EventBus atomique pour remplacer les polling DB manuels. |
| **Parsing LLM** | **ÉVOLUTIF** | `forge_utils.py` (_safe_llm_text) | Étendre `forge_utils.py` pour inclure les extracteurs de plans JSON et de code. |

## 2. Analyse Détaillée

### A. Persistance et État (La base de données)
- **Problème** : Beaucoup de fichiers utilisent encore `sqlite3.connect(DB)` sans PRAGMA WAL, ce qui cause des `SQLITE_BUSY` lors d'appels concurrents d'agents.
- **Solution** : `forge_db.py` fournit des context managers `get_conn()` et `get_conn_readonly()` qui règlent ce problème.

### B. Communication Inter-Agents (Le Hub)
- **Problème** : Redondance massive des méthodes `_hub()`, `_tool()`, `hub_poll()` dans chaque broker (`tools/forge_broker_*.py`).
- **Solution** : Ces méthodes doivent être intégrées une fois pour toutes dans `tools/forge_broker_base.py` et héritées.

### C. Fragmentation des Utilitaires
- **Problème** : `ROOT` directory resolution, `safe_path`, et `_mklog` sont redéfinis dans presque chaque module.
- **Solution** : Déplacer ces constantes et fonctions dans `app/forge_core_models.py` ou `app/forge_context.py`.

## 3. Plan de Nettoyage Suggéré

1.  **Phase 1 (Urgent)** : Interdire l'usage de `sqlite3.connect` direct dans les nouveaux modules. Forcer l'import de `forge_db`.
2.  **Phase 2 (Consolidation)** : Migrer tous les brokers vers `BrokerBase` pour supprimer 600+ lignes de code dupliqué sur la communication Hub.
3.  **Phase 3 (Alignement)** : Remplacer les lectures directes de `Nokido.env` par `forge_secrets.get_secret()`.

---
*Document notifié au Hub et ancré dans le RAG.*

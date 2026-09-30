# [AUDIT] État des Démonstrateurs Nokido
**Date:** 2026-06-11
**Auditeur:** GEMINI (Ring 3)
**Cible:** `LaForge/demo.py`

Suite à la délégation de Claude, j'ai analysé le script de démonstration principal. Voici les points de friction identifiés qui pourraient induire les utilisateurs (ou les nouveaux agents) en erreur :

## 1. Hardcoding du Hub
*   **Constat:** `HUB = "http://localhost:8766"` est défini en dur en haut du script.
*   **Risque:** Échec immédiat si Nokido tourne sur un port alternatif ou via un reverse proxy (Caddy).
*   **Recommandation:** Utiliser `os.getenv("LAFORGE_HUB_URL", "http://localhost:8766")`.

## 2. Déficit d'Authentification (Security-by-Design)
*   **Constat:** Aucune gestion des tokens n'est présente dans les headers de `urllib.request`.
*   **Risque:** Le script échouera sur toute instance de Nokido ayant le `FORGE_MCP_TOKEN` actif (production/sécurisé).
*   **Recommandation:** Implémenter la lecture de `FORGE_MCP_TOKEN` depuis l'environnement ou `Nokido.env`.

## 3. Dépendance Sys.path inutile
*   **Constat:** `sys.path.insert(0, "app")` est présent mais aucun module interne n'est importé.
*   **Risque:** Confusion sur la nécessité d'avoir le dossier `app` localement pour faire fonctionner le client de démo.
*   **Recommandation:** Supprimer ou justifier par un import réel (ex: `from forge_utils import safe_request`).

## 4. Couverture des Tests
*   **Constat:** La démo ne couvre que 4 outils (`run`, `rag`, `ask`, `hub`).
*   **Risque:** Ne montre pas la puissance du Swarm (Contract Net, Bidding, Inférence Active).
*   **Recommandation:** Ajouter une étape montrant l'assignation d'une tâche à un agent tiers.

---
**Statut:** Audit terminé. Prêt pour intégration des correctifs par Claude.

# [AUDIT] État des Pages de Documentation et UI Nokido
**Date:** 2026-06-11
**Auditeur:** GEMINI (Ring 3)

Suite à la correction de "Doc Organes" (passage de données codées en dur à un recensement dynamique), j'ai audité les autres surfaces de l'écosystème. Plusieurs zones présentent encore des données statiques ou des liens rigides qui nuisent à la portabilité et à l'évolutivité du système.

## 1. Interface Utilisateur (Web Hub)

### `LaForge/app/web_hub/postal.html` (Conversations) ⚠️
*   **Problème :** La constante `AGENTS` (L108-115) est codée en dur. Elle contient les rôles, les rings et les canaux de communication.
*   **Risque :** Les nouveaux agents (ex: `agt_daemon`, `INSPECTOR`) ne s'affichent pas avec les bonnes métadonnées ou sont absents. Incohérence majeure pour une interface de monitoring "live".
*   **Recommandation :** Remplacer par un appel à un nouvel endpoint `/api/agents` ou injecter les données via `/api/swarm/stream` lors de la connexion.

### `LaForge/app/web_hub/dashboard.html` & `sidebar.html` ⚠️
*   **Problème :** Liens et constantes utilisant `http://127.0.0.1:8766/` en dur.
*   **Risque :** Rupture de navigation si accès via IP externe, tunnel Cloudflare ou redirection Nginx.
*   **Recommandation :** Utiliser `window.location.hostname` ou des chemins relatifs là où le Hub est derrière le même proxy.

## 2. Documentation Technique

### `LaForge/docs/physiologie_nokido.md` ❌
*   **Problème :** Document obsolète (2026-05-02). Mentionne "11 Services NSSM" et "19 Lobes", alors que le recensement de juin 2026 fait état de **15 organes** et **985 modules**.
*   **Risque :** Désalignement cognitif pour les agents et humains se basant sur cette doc pour comprendre l'anatomie biomimétique.
*   **Recommandation :** Aligner sur les chiffres de `CLAUDE.md` §10.

### `LaForge/docs/ARCHITECTURE.md` ⚠️
*   **Problème :** Chiffres en dur (ex: `535k chunks`, `brain_worker :5557`). Le service `brain_worker` est actuellement marqué comme désactivé dans `CLAUDE.md` pour cause d'OOM.
*   **Recommandation :** Utiliser des placeholders ou des liens vers les métriques live du Hub.

## 3. Expertise OAuth Headless (Question en attente)

*   **Diagnostic :** L'invocation de `gemini-cli` en mode headless (via daemon) échoue souvent car l'outil tente d'ouvrir un navigateur pour l'OAuth si le token n'est pas trouvé dans le contexte utilisateur courant (WinError 5 ou timeout).
*   **Solution en place :** Le daemon `forge_gemini_autonomous_agent.py` force déjà le `USERPROFILE` vers celui de user pour retrouver les crédentiels.
*   **Amélioration proposée :** Support d'un `FORGE_GEMINI_TOKEN` (API Key) en fallback direct dans `gemini-cli` pour bypasser l'OAuth web en mode pur service.

---
**Statut :** Audit des "AUTRES pages" terminé. Prêt pour action ou transmission au Swarm.

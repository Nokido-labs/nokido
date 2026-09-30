# 🧠 ARCHITECTURE : NOKIDO CORTEX HYBRIDE (V15)

> 🧭 **IMPLÉMENTÉ (réparé 2026-08-21).** `app/forge_hybrid_cortex.py` est câblé : squelette AST réel (`_generate_skeleton`), triage déterministe local/cloud (`_triage`), kill-switch de streaming (`stream_prism`). Auparavant stubs (`# TODO Ollama`, squelette « mock » ligne-à-ligne), finis ce jour — test `tests/nr/test_hybrid_cortex_nr.py`.
*Document de Design | Date : 16 Juin 2026*

## 1. VISION : DISSOCIATION INTENTION / ACTION
Nokido V15 transforme le Cloud en un **Cortex Préfrontal** (stratégie) pur, tandis que le Ryzen 8700G local devient le **Système Nerveux Somatique** (exécution).

### 🌈 Le "Prisme de Streaming" (Split-Stream)
Le Hub FastAPI n'est plus un simple passe-plat, mais un séparateur optique pour les flux SSE (Server-Sent Events) :
1.  **Fork 1 (Interface)** : Les tokens sont envoyés au CLI/UI pour affichage temps-réel.
2.  **Fork 2 (Shadow Stream)** : Les mêmes tokens sont publiés sur le bus NATS/Deno local.
3.  **Bénéfice** : Les agents locaux peuvent "lire dans les pensées" du Cloud. Si une intention dangereuse est détectée dans le stream *avant* la fin de la génération, le superviseur local peut couper la connexion.

### 🔄 Le Cycle de Vie d'une Requête (Cloud-Edge)
1. **INPUT** : L'utilisateur envoie une requête complexe au Hub (:8766).
2. **PREFLIGHT (Local)** : 
   - **Triage (Ollama)** : "Est-ce une tâche locale ou nécessite-t-elle un raisonnement Cloud ?"
   - **AST Compression** : Si Cloud, on ne lui envoie pas le code, mais sa structure (signatures + types).
3. **CORTEX (Cloud)** : Claude/Gemini reçoit le squelette et génère une **Intention (JSON)**.
4. **POSTFLIGHT (Local Interceptor)** : 
   - Le Hub intercepte le JSON d'action.
   - Il répond "Accepted" au Cloud immédiatement (fermeture de la connexion/quota).
   - Il transforme l'intention en actions réelles via `tree-sitter` et le bus local.

---

## 2. COMPOSANTS TECHNIQUES

### A. `app/forge_hybrid_cortex.py` (Le Cerveau)
- `PreflightManager` : Intègre un client Ollama léger pour la classification.
- `ASTCompressor` : Utilise `get_file_skeleton` pour réduire l'usage de tokens de 80%.
- `IntentDecoupler` : Mappe les outils Cloud (`write_file`) vers des mutations locales sécurisées.

### B. `tools/nokido_hub.py` (L'Intégration)
- Injection des hooks dans `_tool_call` et `ask`.
- Gestion des états asynchrones pour les actions déportées.

---

## 3. AVANTAGES
- **Économie de Quota** : -70% de tokens envoyés (AST au lieu de Full Code).
- **Zéro-Latence UI** : L'agent Cloud "répond" instantanément dès que l'intention est formulée.
- **Souveraineté Totale** : Le Cloud n'a jamais accès au contenu complet des fichiers, seulement à leur interface.

---

## 4. PROCHAINE ÉTAPE : INITIALISATION
Lancer la création de `app/forge_hybrid_cortex.py`.

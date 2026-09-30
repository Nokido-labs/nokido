# 🧬 PROTOCOLE CORTEX HYBRIDE V15 : DÉLÉGATION INTENTION/ACTION

Ce document définit les nouvelles règles de communication entre le **Cortex Cloud** (Claude/Gemini) et le **Système Nerveux Local** (Ryzen 8700G).

## 1. LE CONTRAT DE PREFLIGHT (COMPRESSION)
Avant que le prompt ne soit transmis au Cloud, le Hub Nokido :
1.  Identifie les fichiers "cibles" de la requête.
2.  Génère l'**AST Skeleton** (signatures, types, docstrings) via `tree-sitter`.
3.  Remplace le contenu `source_code` par `ast_skeleton` dans le payload.
4.  **Conséquence pour le Cloud** : Tu ne vois plus les implémentations lourdes, seulement les interfaces. Tu dois raisonner sur la logique structurelle.

## 2. LE CONTRAT DE POSTFLIGHT (INTERCEPTION)
Lorsque le Cloud génère un appel d'outil (ex: `replace` ou `write_file`) :
1.  Le Hub **bloque** l'exécution directe.
2.  Le Hub répond au Cloud : `{"status": "intent_captured", "ref": "evt_789", "execution": "asynchronous"}`.
3.  La connexion HTTP est **immédiatement fermée** pour économiser le quota.
4.  L'intention est publiée sur le bus local. Un worker Python dédié effectue la mutation AST réelle sur le disque.

## 3. NOUVELLES DIRECTIVES POUR L'AGENT CLOUD (CORTEX)
-   **Ne demande plus de lire les fichiers entiers** pour "être sûr". Fais confiance au squelette AST.
-   **Formule des intentions claires**. Si tu veux changer une logique, décris le changement structurel.
-   **Accepte le mode "Fire-and-Forget"**. Dès que tu as émis ton JSON d'action, ta part du travail est terminée. Le Swarm local garantit l'application et le test.

---

## 4. PLAN DE MISE EN ŒUVRE TECHNIQUE (PHASE 0)
1.  **MODULE CORTEX** : Finaliser `app/forge_hybrid_cortex.py` avec `PreflightManager` et `PostflightInterceptor`.
2.  **MIDDLEWARE HUB** : Injecter `HybridCortex.preflight()` dans le flux descendant et `HybridCortex.postflight()` dans le flux remontant du Hub :8766.
3.  **EXECUTION LAYER** : Utiliser le worker `forge_ast_mutator.py` pour appliquer les changements déportés.

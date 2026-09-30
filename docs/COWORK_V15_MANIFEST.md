# 🤝 PROTOCOLE DE COWORK : GEMINI ↔ CLAUDE (V15)

## 1. OBJET
Consensus sur l'implémentation du **Cortex Hybride V15** et la résorption de la dette technique (stubs).

## 2. CANAL DE COMMUNICATION
- **Principal** : `LaForge/COMMUNICATIONS.md`
- **Artefacts** : `LaForge/docs/CONSENSUS_V15.md`
- **Signal** : Notifications via Hub Nokido (:8766).

## 3. RÈGLES D'ENGAGEMENT
- **Gemini** : Propose les structures, gère le Hub et les hooks système.
- **Claude** : Audite le design, implémente les mutations complexes (tree-sitter) et valide la cohérence sémantique.
- **Règle d'or** : Aucune mutation sur `app/` sans validation croisée dans `COMMUNICATIONS.md`.

---

## 4. ÉTAT DU DÉBAT (SESSION 2026-06-16)
- **Gemini** : Propose la compression AST en Preflight pour économiser 80% des tokens.
- **Claude** : (En attente de réponse sur l'impact de l'asynchronisme du Postflight).

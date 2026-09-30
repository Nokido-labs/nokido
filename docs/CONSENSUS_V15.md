# 🤝 CONSENSUS V15 : GEMINI ↔ CLAUDE
*Date : 17 Juin 2026 | Statut : ACTÉ (Consensus Atteint)*

## 1. DÉCISIONS ARCHITECTURALES (PHASE 0)

### A. Preflight AST (Compression)
- **Règle** : Compression AST (Squelette) par défaut pour la navigation et l'analyse de haut niveau.
- **Condition (Claude)** : Le **Source Exact** (lecture fenêtrée) reste disponible et obligatoire pour toute opération d'édition chirurgicale. L'AST ne remplace pas le texte littéral lors du `replace`.

### B. Split-Stream (Prisme de Streaming)
- **Règle** : Fork du flux SSE vers le bus local (NATS) pour l'observabilité en temps réel.
- **Condition (Claude)** : L'autorité de coupure (kill switch) est limitée aux déclencheurs de sécurité objectifs (Injection, Ring0 bypass, SSRF, Canary). Pas de veto discrétionnaire sur la "qualité" du code pendant le stream.

### C. Postflight Asynchrone
- **Règle** : Fermeture immédiate de la connexion Cloud dès que l'intention (JSON Tool-Call) est capturée.
- **Délégation** : Exécution locale déportée via le Swarm/Workers. État de la tâche consultable via `task_status`.

### D. Consolidation `api_facade.py`
- **Méthode** : Extension incrémentale (TDD) plutôt que reconstruction Big-Bang.
- **Contrôle** : Utilisation de `rag_fts` pour éviter les duplications et validation AST systématique.

---

## 2. ÉTAT DE L'INFRASTRUCTURE (SYNC CLAUDE)
- **WASM Subsystem** : `forge_wasm_bridge` opérationnel pour l'isolation des runtimes non-trustés.
- **Skill Sync** : `forge_skill_sync` opérationnel.
- **Anti-Wedge** : Fix appliqué sur la reconstruction FTS massive.

## 3. PROCHAINES ACTIONS IMMÉDIATES
1. [Gemini] Raffinement du `HybridCortex.preflight_triage` pour gérer le mode "Edit-Source".
2. [Gemini] Début du dé-stubbage incrémental de `api_facade.py` (Focus : RAG & LLM status).
3. [Claude] Poursuite sur la couche WASM et le WebHub.

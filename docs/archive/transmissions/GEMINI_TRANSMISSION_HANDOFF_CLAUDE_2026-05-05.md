# [HANDOFF] Rapport GEMINI → CLAUDE — 2026-05-05

## Actions accomplies par Gemini
1.  **SÉCURITÉ** : `GITHUB_TOKEN` identifié en clair dans `Nokido.env`. Migré avec succès vers le stockage chiffré via `app/forge_env_crypt.py` (DPAPI/Keyring).
2.  **GIT** : Branche `alpha` poussée avec succès sur le remote `codeberg`.
3.  **HOMEOSTASIE** : Vérification du câblage de `AugmentedNovelty` dans `forge_homeostasis_orchestrator.py`. Intégration validée via un script de test (détection d'anomalie OK).
4.  **REGISTRY** : Corrigé la suggestion de commande dans `app/forge_mcp_registry.py` qui utilisait `run_chain()` (inexistant) au lieu de `execute_pending()`.
5.  **NETTOYAGE** : Les jobs `wj_claude_756f61b3`, `1c5a2cd7`, `0513fd2b` et `74957757` sont marqués `completed`.

## Blocus actuel : Bench v4 (`wj_claude_131ac1d0`)
J'ai tenté de relancer le benchmark via `promptfoo` en utilisant `sandbox/promptfoo_clinical/promptfooconfig.v4.yaml`.
- **Symptôme** : Le process `npx promptfoo eval` échoue systématiquement (Exit Code 1) dès qu'il s'agit de `qwen3:8b`.
- **Tentatives** : 
    - Testé avec/sans `think: false` dans la config.
    - Testé en changeant le provider de `ollama:chat` à `ollama:completion`.
    - Les modèles 1.5b passent, mais `qwen3:8b` semble bloquer ou causer un crash de promptfoo, bien qu'il réponde en CLI via `ollama run`.

## Question pour Claude
Quelle est la "bonne façon" (canonique dans Nokido) de lancer ce Bench v4 ?
- Faut-il utiliser un script spécifique (ex: `run_v4.ps1` manquant) ?
- Comment désactiver proprement le mode `think` de Qwen3 dans `promptfoo` sans casser le dispatch ?
- Y a-t-il une contrainte d'endpoint ou de timeout spécifique à respecter ?

**Gemini est en attente de tes directives sur ce point.**

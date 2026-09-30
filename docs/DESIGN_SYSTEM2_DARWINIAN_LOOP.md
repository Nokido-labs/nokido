# DESIGN DOC: Architecture Multi-Transient et Boucle Darwinienne (System 2 / LLM-MCTS)

## 1. Vision (La Noosphère Logicielle)
Nokido évolue d'un système réactif (System 1) vers un système délibératif (System 2). L'objectif est d'utiliser une flotte de modèles locaux légers pour générer de multiples chemins de réflexion (exploration), et un modèle Cloud dense (ou un Oracle local) pour évaluer et consolider la meilleure solution (exploitation).

## 2. Anatomie d'un "Transient"
Un transient n'est pas un simple texte, c'est une "cellule souche cognitive" générée en RAM :
- **Générateurs (Périphérie) :** LLMs locaux via CLI déchargés sur iGPU (Llama-3, Qwen).
- **Évaluateur (Cortex Préfrontal) :** Claude 3.5 / GPT-4o ou un vérificateur formel local.
- **Homogénéité :** Encapsulation stricte via le protocole MCP.
- **Vascularisation :** Transport des contextes massifs sans fragmentation via interface loopback optimisée (MTU 9000 / Jumbo Frames).

## 3. Le Processus Autopoïétique (Cristallisation)
Une fois validée par la fonction de fitness (le Juge), la pensée subit un split vectoriel :
- **4096d (Sémantique) :** Philosophie, architecture.
- **1024d (Structurel) :** Code source, fonctions.
- **FTS / BM25 (Déclaratif) :** Cold storage, UUIDs, stack traces exactes.

## 4. Remplacement des I/O Disque par WASM
L'utilisation de `C:/tmp` pour évaluer les transients (ex: tester un script Python généré) est un anti-pattern qui génère de la latence NTFS.
**Axe d'amélioration :** Le "Test-Time Compute" doit s'exécuter en in-memory. L'évaluation du code généré par les transients doit être encapsulée dans une sandbox WASM (WASI) ou via l'organe `oracle_python_repl` pour une sécurité Zero-Trust et une latence milliseconde.

## 5. Algorithme Cible : LLM-MCTS
Inspiration directe des architectures DeepMind (AlphaProof, mctx) et communautaires (LightZero). L'objectif est de coder un `forge_mcts_engine.py` utilisant la formule UCB1 pour équilibrer l'exploration de nouvelles idées darwiniennes et l'exploitation des déductions solides.

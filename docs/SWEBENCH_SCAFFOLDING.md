# Plan de scaffolding SWE-bench — combler le "Scaffolding Gap"

Analyse Scale AI : un modèle frontier plafonne ~45 % sur SWE-bench Pro en
environnement standard, 59-70 % avec orchestration avancée. L'écart = le
**scaffolding** (orchestration), pas la capacité brute.

Nokido a les **briques** (NPU XDNA1, modèles ollama locaux, modules graph,
swarm, test-fix loop, warpgrep v1). Manque : **l'orchestration**. Ce doc =
le plan pour la câbler. Sert Verified ET Pro.

**GATE** : tout ceci s'exécute APRÈS le chiffre de la run de vérif (Stages
0/3/4). Si la run régresse → bisecter d'abord. Sinon → exécuter dans l'ordre.

---

## 1. ✅ FAIT — warpgrep câblé dans le runner

`_find_relevant_files` : `warpgrep_locate` en localiseur PRIMAIRE, TF.IDF
en fallback, force_files (Stage 0) pré-pendu. `forge_swebench_modal.py`
embarque `forge_warpgrep.py` dans l'image. Smoke : separable.py rang #1.
→ actif dès le PROCHAIN `modal run` (l'image se rebuild avec le nouveau code).

## 2. Stage 2 — skeleton pruning pour le Coder — effort S/M

`_coder_context` envoie encore le fichier ENTIER (cap 30k). → envoyer
`_skeleton_file` (corps masqués par `...`) + `_zoom_functions` (code complet
des seules fonctions du sous-graphe / keywords). -50-70 % de prompt, le
modèle <70B reste focus. Briques déjà présentes dans le runner.

## 3. Search-subagent (méthode Scale #1) — effort M

Le Coder principal (modèle lourd) ne cherche JAMAIS. Un subagent léger le
fait : warpgrep (déterministe) sort les candidats → un petit modèle LOCAL
(`ollama qwen2.5-coder:7b` — gratuit, zéro API) trie, élimine les faux
positifs, ne renvoie QUE les spans utiles → le Coder reçoit du contexte
chirurgical. Nouvelle fonction `_search_subagent()` ; remplace/augmente
`_swarm_explore`. NB : le NPU XDNA1 fait l'ONNX/embeddings (rerank), pas le
LLM ollama — mais les deux sont locaux et gratuits (le point tient).

## 4. WarpGrep v2 — call-graph cross-fichier (méthode Scale #2) — effort L

Le gros morceau. Table de symboles (`{module: {func/classe: (file,line)}}`)
+ graphe d'appels avec résolution des imports → arêtes cross-fichier.
`callers_of` / `callees_of` ≤2 sauts. Sert : (a) injecter les voisins ≤2
sauts dans le contexte Coder, (b) piloter le Stage 3b multi-fichiers par le
GRAPHE et non plus une heuristique LLM (« change la signature de foo dans
utils.py → injecte les 4 fichiers qui l'appellent »). Réutilise
`forge_graph_universal.CodeASTSource` (mono-fichier → étendre cross-fichier)
+ `forge_graph_ppr`. Le manquant réel = la résolution des imports.

## 5. Tests de génération in-Docker (méthode Scale #3, nuance) — effort M/L

`_apply_and_test` tourne pytest en LOCAL (~75-85 % de fidélité). Pro-grade =
exécuter dans le Docker par-instance (l'env exact du harness). L'infra DooD
existe (scoring) → l'étendre au temps de génération. Priorité basse : le
local marche déjà ; gain = fidélité.

---

## Ordre & rationale

1-2 = quick wins (intègre warpgrep + resserre le contexte). 3 = le saut de
propreté du contexte. 4 = le saut multi-fichiers / anti-régression cachée.
5 = polissage de fidélité.

Méthode #3 (sandbox + self-correction TDD) = **déjà fait** côté Nokido —
test-fix loop + gates Stage 4. Seul le in-Docker (item 5) manque.

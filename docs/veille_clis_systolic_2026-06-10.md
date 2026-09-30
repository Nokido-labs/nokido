# Veille profonde — CLI agents + tableaux systoliques (2026-06-10)

> Souveraine : 6 repos `git clone --depth 1` → dump → RAG (`domain=sdk_gitingest`,
> ~2833 chunks, FTS BM25 immédiat ; embeddings dense via `forge_embed_auto_trigger`
> en continu → recherche sémantique sous peu). SearXNG était down → chemin clone direct
> (`tools/forge_veille_clone_ingest.py`). Grounded : README SCALE-Sim lu + métriques
> d'ingestion mesurées + connaissance CLI de la session. Ce qui n'est pas vérifié au
> code est marqué `[infér]`.

## A. Tableaux systoliques (angle inférence locale NPU / XDNA / grille de calcul)

| Repo | Fichiers | Chunks | Rôle |
|---|---|---|---|
| **SCALE-Sim** (scalesim-project) | 75 | 681 | Simulateur perf — la référence |
| **tinytinyTPU** (Alanma23) | 158 | 1019 | TPU éducatif end-to-end, testé Python |
| **SysArray-nMigen** (ecqin) | 7 | 17 | RTL : Amaranth/nMigen → Verilog MAC |
| **SystolicArrayDemo** (antonpaquin) | 2 | 14 | Démo dataflow minimaliste |

**SCALE-Sim v3.0.0** (2025-08-13) — simulateur d'accélérateurs à tableau systolique pour
couches DNN (Conv, FC, GEMM/Attention). Entrées : fichier **config** (`architecture_presets`
= params HW du tableau) + **topology** (format M,N,K GEMM, switch `-i gemm`). Sorties :
**cycle-accurate** SRAM/DRAM traces séparées Input/Filter/Output, `BANDWIDTH_REPORT.csv`,
`DETAILED_ACCESS_REPORT.csv`. v3 ajoute : **multi-core** (plusieurs tensor cores),
**Ramulator** (modèle DRAM détaillé), **sparsity**, **Accelergy** (énergie).
→ **Usage Nokido** : modéliser comment BGE-M3 (embed) / qwen (inférence) tourneraient sur
**XDNA Gen1 / Radeon 780M** — identifier les goulots SRAM/DRAM, choisir le dataflow
(weight- vs output-stationary), AVANT de retenter l'accel NPU (cf [[incident_bsod_2026-05-24_directml_brainworker]] : DirectML iGPU = BSOD ; [[feedback_npu_xdna1_limits]] : XDNA1 = ops légères only). SCALE-Sim donne le chiffrage théorique sans crasher la machine.

**tinytinyTPU** = pipeline complet (FIFO → MAC → activation) d'un systolic 2×2, **validé par
scripts Python** end-to-end → meilleure référence pour comprendre le flux entier + patterns
de testbench. (1019 chunks = le plus gros corpus ingéré.)

**SystolicArrayDemo** = 2 fichiers Python, dataflow pur (poids/activations qui "glissent" dans
la grille 2D). → base conceptuelle la plus propre pour la **logique d'orchestration de nœuds
en grille** `[infér]` : analogie directe avec le role-clustering Nokido (workers = PE, cf
[[hardware_topologies_distributed]] "VRAM pas poolable → N workers indép").

**SysArray-nMigen** = génération Verilog synthétisable (MAC INT8/FP16) + testbench numpy
cycle-accurate. → utile seulement si Nokido vise un jour une cible **FPGA** réelle.

## B. CLI agents (angle sync multi-CLI — cf Phase 1 livrée ce jour)

| CLI | Repo | Fichiers | Chunks | OSS ? |
|---|---|---|---|---|
| **Gemini CLI** | google-gemini/gemini-cli | 126 | 1075 | ✅ OSS complet |
| **Copilot CLI** | github/copilot-cli | 3 | 27 | ❌ public mince (closed-source) |
| **Claude Code** | — | — | — | ❌ non-OSS (docs seulement) |

**Gemini CLI** — source complète ingérée (1075 chunks). Implémente MCP + `--experimental-acp`
(Agent Client Protocol). Nokido avait déjà son connecteur (`forge_gemini_mcp_connector.py`,
traduit MCP→FunctionDeclaration) + l'orchestration validée 2026-04-24 (23 tools). Le code
gemini-cli est désormais **étudiable dans le RAG** pour : son impl MCP/ACP exacte, son schéma
extensions/settings → modèle pour la sync multi-CLI (Phase 1 : broadcast `to=ALL` + présence).

**Copilot CLI** — repo public = **3 fichiers seulement** (README/license/changelog). Le binaire
est **closed-source** → pas de deep-watch du code. Intel = le **changelog** (v1.0.61 :
modèle **Claude Fable 5** RÉEL, auto-load MCP `.github/mcp.json`, `/agents`, `/every` `/after`
cron). Câblé au hub ce jour (`.github/mcp.json` + `_INJECT_AGENTS += COPILOT`).

**Claude Code** — pas de repo public clonable. Veille = docs + comportement observé (hooks
SessionStart/PostToolUse/Stop, sub-agents, MCP). Déjà cartographié en interne
(`tools/hub_lifecycle_hooks.py`, `claude_session_start.py`).

## Synthèse pour Nokido
1. **NPU/inférence** : SCALE-Sim = l'outil pour CHIFFRER avant de coder l'accel matérielle
   (évite les BSOD empiriques). Dataflow weight/output-stationary à benchmarker pour BGE-M3/qwen.
2. **Grille = swarm** : la topologie PE-en-grille (SystolicArrayDemo/tinytinyTPU) éclaire
   l'orchestration de workers Nokido (role-clustering). `[infér]` à creuser.
3. **Sync CLI** : gemini-cli (OSS) = la seule source code-level pour s'aligner ; copilot/claude
   = boîtes noires → s'appuyer sur changelog + protocole hub (broadcast Phase 1).
4. **Tout est dans le RAG** : `rag_fts MATCH '<terme>'` ou `rag search` (dès embeddings prêts)
   sur ces 6 repos — l'orchestrateur peut router vers cette intel.

Régén : `LAFORGE_PYTHON tools/forge_veille_clone_ingest.py [noms…]` (clones dans `C:/tmp/nokido_veille`).

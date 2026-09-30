---
type: guide
title: 13 — Roadmap matérielle
status: draft
resource: repo://docs/wiki/13-Hardware-Roadmap.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 13 — Roadmap matérielle

<!-- revu-le: 2026-09-17 -->
> Mise à jour : 2026-09-17

> 🌐 [English](13-Hardware-Roadmap.md) · **Français**

Nokido conçu pour **suivre le silicium**, pas s'enfermer dans un paradigme. Page technique compagnon de [MANIFESTO.md §6](../../MANIFESTO.md#6-évolution-matérielle--roadmap-par-puce).

## 🎯 Vue globale

| Phase | Horizon | Hardware cible | Modules impactés |
|---|---|---|---|
| Stable | aujourd'hui | APU x86-64 + iGPU + light NPU | tout existant |
| A | 6-12 mois | NPU 40+ TOPS (Intel Lunar Lake, Hailo-10) | `forge_accelerator_router` (à créer) |
| B | 12-24 mois | Neuromorphique (Akida, Loihi 2, GrAI) | `forge_spike_router`, `forge_active_inference_agent` |
| C | 24-48 mois | Analogique CIM / RRAM / photonique | swap backend `brain_worker` |
| D | 48+ mois | Grilles analogiques continues | "modèle pré-entraîné" obsolète — full continual |

## ⚙️ Aujourd'hui — APU consumer

Plateforme testée : **AMD Ryzen 7 8700G + Radeon 780M iGPU**.

Benchmarks mesurés :
- HumanEval pass@1 : **87,8 %** (mistral-small-latest, free tier).
- BFCL v4 : **90-96 %** (simple/multiple/parallel).
- SWE-bench : 10/50 mixed sample.

Composants actifs :
- **CPU x86-64** : LLM CPU-only (Ollama, llama.cpp). Charge principale.
- **iGPU Radeon 780M** : ONNX BGE-M3 via DirectML/Vulkan. ~10 embeddings/s, 1024D. ETA stable ~13h pour 380k chunks.
- **NPU XDNA1** : testé empiriquement ops-light only. **Pas** suitable BGE-M3 batch ni LLM inference. Réservé petits classifiers ONNX (routing, filters rapides). Memory : `npu_xdna1_limits`.

## 🔌 Phase A — NPU edge accelerators (6-12 mois)

Adoption quand runtime open-source ship :

### Intel Lunar Lake / Meteor Lake NPU
- 45 TOPS INT8.
- OpenVINO runtime, bien supporté Python.
- **Cible** : offload cross-encoder reranker (CPU actuel). Gain attendu : 5-10× throughput RAG queries.

### Hailo-8 / Hailo-10
- 26 TOPS (Hailo-8, M.2) / 40 TOPS (Hailo-10, M.2).
- 2-2.5 W TDP. Drop-in PCIe.
- HailoRT SDK expose ONNX. Compatible avec brain_worker Nokido via swap backend.
- **Cible** : service dédié `forge_lnn_monitor` (télémétrie continue).

### Coral Edge TPU
- 4 TOPS (USB / M.2). Cheap, partout.
- TFLite quantized only — 1-bit BitNet fits parfait (validation 2026 H2).
- **Cible** : fallback portable pour clients low-resource.

### Changement logiciel

Nouveau module `app/forge_accelerator_router.py` (planifié) :
1. Détecte accelerators dispo au boot.
2. Route inférence ONNX par type tâche au meilleur backend : `DirectML > Vulkan > OpenVINO > HailoRT > EdgeTPU > CPU`.
3. Surface endpoint `/api/accelerators` pour monitoring.

## 🦋 Phase B — Neuromorphique (12-24 mois)

Les puces neuromorphiques calculent par **spikes** (pilotées par l'événement, pas par
l'horloge). Elles sont algorithmiquement proches du cervelet SNN déjà présent dans Nokido
et de l'inférence active (`app/forge_active_inference_agent.py`).

**Où vit réellement le substrat spiking.** Mesure du 2026-08-28 — cette page nommait
auparavant `forge_spike_router.py` comme « le cervelet SNN utilisant snntorch », ce qui
est **faux** et envoyait le lecteur vers un module qui n'a aucune couche spiking :

| module | spiking ? | preuve |
|---|---|---|
| `app/forge_snn_core.py` | **oui — le vrai substrat** | importe `snntorch` + `torch`, couches LIF |
| `app/forge_snn_monitor.py` | oui | importe `snntorch` ; encode la télémétrie RAM/CPU/GPU en spikes |
| `app/forge_snn_router.py` | oui | `SNNRouter`, bâti sur `forge_snn_core` |
| `app/forge_spike_router.py` | **non** | `torch` + `numpy` avec un `_SurrogateSpike` maison ; **n'importe pas `snntorch`**. C'est un routeur en forme d'événements (`CTFSpikeRouter`), pas un réseau spiking. |

⚠️ **Écart d'exécution — une dégradation silencieuse, pas un plantage.** `snntorch` était
installé sous `miniforge3` (base) mais **pas sous `miniforge3/envs/laforge_py314`**,
l'interpréteur des jobs détachés (`run_job`). Rien n'échouait : les deux modules
retombaient sur un repli, et c'est précisément le piège — un repli correct masque le fait
que le mode voulu n'a jamais tourné. Mesure du 2026-08-28 :

| module | avec `snntorch` | sans (jobs) |
|---|---|---|
| `forge_snn_core` | backend `snntorch` (Leaky + fast_sigmoid) | backend **`builtin-lif`** — un vrai LIF quand même, écrit à la main en torch pur |
| `forge_snn_monitor` | chemin LIF spiking | **comparaison à seuil statique**, `available()` rend `False`, `enabled=False` |

Les deux publient le backend qu'ils ont pris (`forge_snn_core.available()` rend
`{"torch": …, "snntorch": …}`, et signale `illisible_garde_sandbox` plutôt que `False`
quand le garde du bac à sable bloque la sonde) : la dégradation est **déclarée** — la lire
avant d'attribuer un résultat « au SNN ».

**Ce n'est pas théorique.** Le substrat est allumé (`sandbox/snn.wantedd` est présent,
`forge_resource_manager` le lit) et a émis **598 événements marqués `snn`** dans
`sandbox/lifecycle_actions.jsonl` depuis le 2026-08-04 — recomptés le 2026-08-30, le
dernier à `15:31:18 UTC`, cinq minutes avant l'écriture de cette ligne (le journal porte
7 090 lignes, 7 063 JSON valides, 27 illisibles). Tous les émetteurs relevés tournent sous
`laforge_py314` — donc **jusqu'au 2026-08-30 la production n'avait tourné qu'en repli**,
jamais sur le chemin `snntorch` voulu.

Preuve d'exécution du substrat, rejouée le 2026-08-30 :

```
forge_snn_core.selftest() -> backend='snntorch', acc 0.848 -> 1.0,
                             spikes_last_pass=72875, learned=True
```

⚠️ **Ne pas confondre les deux modules.** Le neuromorphique *fonctionne* — c'est
`forge_snn_core`. `forge_spike_router`, lui, n'a aucune couche spiking : ses imports
mesurés à l'AST sont `torch`, `numpy`, `dataclasses`, `forge_npu_embedder`… et **pas
`snntorch`**. Les deux affirmations sont vraies en même temps parce qu'elles ne portent
pas sur le même fichier.

**Corrigé le 2026-08-28** : `snntorch` installé dans `laforge_py314` (action owner — sous
le compte du bac à sable, `pip` retombe sur une installation utilisateur et meurt sur
`C:\Users\Default\Python`, WinError 5).

✅ **Live depuis le 2026-08-30** (la réserve « pas encore actif » de la version anglaise
est levée). Le sampler tourne *dans le hub*, et `_HAS_SNNTORCH` est capturé à l'import :
il fallait donc un redémarrage. Mesuré après celui de 17:08 — le hub tourne bien sous
`miniforge3/envs/laforge_py314/python.exe`, et sous cet interpréteur exact :

```
forge_snn_core.available()    -> {'torch': True, 'snntorch': True, 'torch_etat': 'present'}
forge_snn_monitor.available() -> True
```

Prouvé par l'usage, pas par un drapeau : du code installé n'est pas du code chargé.

Deux notes pour qui voudrait auditer ceci :

- Les tirs forment un **journal JSONL** (`sandbox/lifecycle_actions.jsonl`), pas une table
  SQL. Chercher une table nommée `spike`/`snn` ne rend rien et se lit comme « le substrat
  n'a jamais tourné » — une absence fabriquée. De même, le moniteur n'a pas de processus
  propre : il est *importé dans* le hub, donc chercher `snn` dans les lignes de commande
  ne rend rien non plus.
- Les horodatages du journal sont en **UTC** (`+00:00`). Les comparer à un minuit local
  fait passer un tir d'il y a trente minutes pour un tir de la veille.

### Intel Loihi 2
- Recherche. 1M neurones, 120 ops/s par neurone.
- Framework Lava (Python). Cible Nokido : porter `forge_spike_router` et la boucle d'inférence active vers Lava.

### IBM NorthPole
- Production. 256 cores, ~26B ops/s, **pas de DRAM externe**.
- ResNet-50 : 25 ms à 74 W (vs H100 à 700 W).
- **Cible** : embedder `brain_worker`. Retrieval RAG sub-ms.

### BrainChip Akida
- Production. M.2.
- **Continual learning on-chip non-supervisé** — s'aligne avec `forge_continual_backprop.py`.
- **Cible** : `forge_inspector` + sentinels TDR (monitoring always-on).

### GrAI Matter Labs GrAI-Core
- Processing événementiel.
- **Cible** : bus event Deno (`proxy_deno/core/nervous_system.ts`) — match parfait substrat.

### Préparation logicielle

`forge_snn_core` → service autonome (**planifié ; rien de livré**). À noter qu'**aucun
module `forge_spike_router` n'existe** : ce nom ne survit que comme entrée d'alias
dans `forge_wiki_align` (`"forge_spike_router": "forge_spike_router"`) et comme
commentaire dans `forge_feature_checklist` — une rustine posée sur l'ancienne formulation
de cette page, pas une première étape déjà franchie.

1. Extraire le cervelet SNN hors du module Python, en service autonome (HTTP ou ZMQ).
2. Abstraire le backend : `PyTorch CPU/CUDA → Lava-Loihi → Akida MetaTF`.
3. API stable ; le changement de backend devient un simple drapeau de configuration.

## 🌡️ Phase C — Analogique & photonique (24-48 mois)

Le **goulot von Neumann** (CPU/RAM séparés, transfert électrique constant) responsable de ~97% du gaspillage énergétique LLM matmul. Trois voies bypass :

### Compute-in-memory analogique
- **Mythic AI M1076** : matmul analogique, 25 TOPS pour 3 W. 8-bit effectif.
- **IBM Hermes** : matmul ReRAM in-memory, 50-100× efficacité.
- **Cible** : reranker + classifier fast path. Précision réduite acceptable pour inner loop `forge_scorecard` + `forge_dt_router`.

### RRAM neuro-vector compute
- **NeuRRAM** (UC San Diego, 2023) : 256 KB cellules ReRAM, recall associatif natif.
- **Cible** : couche **retrieval dense RAG**. `FAISS IndexFlatIP` = associative recall, match parfait. Watt-seconde au lieu joule-seconde par query.

### Photonique
- **Lightmatter Envise**, **Lightelligence PACE** : matmul à vitesse lumière. Profil thermique passif.
- 10 000× efficacité théorique sur matmul pur.
- **Cible** : couche embedding BGE-M3 (~3 GFLOP par query actuellement).

### Préparation logicielle

Choix de conception Nokido : **la frontière d'abstraction est le service Rust
`brain_worker`** (`go_services/brain_worker/`). Le code Python ne voit jamais
le silicium. Changer de matériel est un changement de binaire de service, pas une
réécriture Python.

⚠️ **État mesuré le 2026-08-28** : le service existe (`Cargo.toml`, `src/main.rs`,
installeur NSSM) mais ne livre **qu'un seul `main.rs` et zéro `backend_*.rs`**. Le point
de bascule est **déclaré, pas construit** — un adaptateur de backend n'a pour l'instant
aucune couture où se brancher.

## 🌐 Phase D — Grilles neuronales continues (48+ mois)

Au-delà accelerators-as-coprocessors, **grilles analogiques** (Rain AI, Mythic gen-3, IBM Analog AI) émergeront comme **substrats** — cortex synthétique sur PCIe. À ce stade :
- Concept "modèle pré-entraîné" devient obsolète.
- La grille **apprend continuellement** du signal qui la traverse.
- Nokido devient l'**interface** entre humain et substrat neuronal personnel.

Nokido prête pour ce monde car :
- AMI + Active Inference + Continual Backprop conçus pour **online learning**, pas batch training.
- Hub abstract substrat depuis surface client.
- Couches RAG / membrane / firewall substrate-agnostic.

## ⚡ Argument énergétique

Voir [MANIFESTO §6.0](../../MANIFESTO.md#60-pourquoi-le-matériel-est-la-vraie-question--largument-énergétique). Résumé :
- Cerveau humain : ~500 B param équivalent, 20 W.
- H100 GPU : ~80 B param GPT-4-class inference, 700 W.
- Gap : **30 000×**.

Stack neuromorphique / analogique / photonique mesurée aujourd'hui ferme ce gap par **100× à 10 000×**. Le 3-300× restant est ingénierie. Le travail algo (AMI, continual learning, computation spike-based) est mostly done.

## 🤝 Contribuer support accelerator

Si tu as un accelerator non-supporté :
1. Ouvre issue GitHub avec modèle puce + API runtime.
2. Implémenter backend adapter dans `go_services/brain_worker/src/backend_<vendor>.rs` ou `app/forge_<vendor>_runtime.py`.
3. Update `forge_accelerator_router.py` pour détection.
4. Ajoute benchmark dans `tools/forge_bench_accelerator.py`.

PRs welcome : AMD ROCm tuning, Apple CoreML adapter, Hailo SDK integration, Lava-Loihi port `forge_spike_router`, NeuRRAM emulator.

## 📊 Méthodologie benchmark

Quand on dit "100× plus efficace" :
- Même tâche (BGE-M3 inference, ResNet-50, llama-3.3-70b inference).
- Même cible qualité (BLEU, accuracy, recall@K).
- Mesuré à wall power sur load représentatif.
- Normalisé à inférences/joule.

Scripts (quand intégré) : `tools/forge_bench_<chip>.py`. Run via `pytest -m bench`.

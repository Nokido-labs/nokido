---
type: guide
title: 13 — Hardware roadmap
status: draft
resource: repo://docs/wiki/13-Hardware-Roadmap.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 13 — Hardware roadmap

<!-- revu-le: 2026-09-17 -->
> Updated: 2026-09-17

Nokido is designed to **follow the silicon**, not lock into a paradigm.
This page is the technical companion to [MANIFESTO.md §6](../../MANIFESTO.md#6-évolution-matérielle--roadmap-par-puce).

## 🎯 The big picture

| Phase | Horizon | Target hardware | Modules impacted |
|---|---|---|---|
| Stable | today | x86-64 APU + iGPU + light NPU | all existing |
| A | 6–12 months | 40+ TOPS NPU (Intel Lunar Lake, Hailo-10) | `forge_accelerator_router` (to create) |
| B | 12–24 months | Neuromorphic (Akida, Loihi 2, GrAI) | `forge_snn_core`, `forge_active_inference_agent` |
| C | 24–48 months | Analog CIM / RRAM / photonic | `brain_worker` backend swap |
| D | 48+ months | Continuous analog grids | "model pre-train" obsolete — full continual learning |

## ⚙️ Today — APU consumer

Tested platform : **AMD Ryzen 7 8700G + Radeon 780M iGPU**.

Measured benchmarks (cf [README §Benchmarks](../../README.md#-benchmarks)) :

- HumanEval pass@1 : **87.8 %** (mistral-small-latest, free tier).
- BFCL v4 : **90–96 %** (simple/multiple/parallel).
- SWE-bench : 10/50 mixed sample.

Components active :

- **CPU x86-64** : LLM CPU-only inference (Ollama, llama.cpp). Heaviest
  charge.
- **iGPU Radeon 780M** : ONNX BGE-M3 via DirectML or Vulkan. ~10
  embeddings/s, 1024D. ETA stable ~13h for 380k chunks.
- **NPU XDNA1** : tested ops-light only. **Not** suitable for BGE-M3
  batch or LLM inference. Reserved for small ONNX classifiers (routing,
  rapid filters). Memory : `npu_xdna1_limits`.

## 🔌 Phase A — Edge NPU accelerators (6-12 months)

Adoption when an open-source runtime ships :

### Intel Lunar Lake / Meteor Lake NPU

- 45 TOPS INT8 (Lunar Lake, late 2024).
- OpenVINO runtime, well-supported in Python.
- **Target use** : offload the cross-encoder reranker (currently CPU).
  Expected gain : 5-10× throughput on RAG queries.

### Hailo-8 / Hailo-10

- 26 TOPS (Hailo-8, M.2) / 40 TOPS (Hailo-10, M.2).
- 2-2.5 W TDP. Drop-in PCIe acceleration.
- HailoRT SDK exposes ONNX. Compatible with Nokido `brain_worker` via a
  backend swap.
- **Target use** : dedicated service for `forge_lnn_monitor` (continuous
  telemetry).

### Coral Edge TPU

- 4 TOPS (USB / M.2). Cheap, available everywhere.
- TFLite quantized models only — 1-bit BitNet will fit nicely (in
  validation 2026 H2).
- **Target use** : portable fallback for low-resource clients.

### Software change

A new module `app/forge_accelerator_router.py` (planned, not yet
implemented) will :

1. Detect available accelerators at boot.
2. Route ONNX inference per task type to the best backend :
   `DirectML > Vulkan > OpenVINO > HailoRT > EdgeTPU > CPU`.
3. Surface a `/api/accelerators` endpoint for monitoring.

## 🦋 Phase B — Neuromorphic (12-24 months)

Neuromorphic chips compute via **spikes** (event-driven, not clock-driven).
They are algorithmically close to Nokido's existing SNN cervelet and to Active
Inference (`app/forge_active_inference_agent.py`).

**Where the spiking substrate actually lives.** Measured 2026-08-28 — this page
previously named `forge_spike_router.py` as "the SNN cervelet using snntorch",
which is wrong and sent readers to a module that has no spiking layer at all :

| module | spiking? | evidence |
|---|---|---|
| `app/forge_snn_core.py` | **yes — the real substrate** | imports `snntorch` + `torch`, LIF layers |
| `app/forge_snn_monitor.py` | yes | imports `snntorch`; encodes RAM/CPU/GPU telemetry into spikes |
| `app/forge_snn_router.py` | yes | `SNNRouter`, built on `forge_snn_core` |
| `app/forge_spike_router.py` | **no** | `torch` + `numpy` with a hand-rolled `_SurrogateSpike`; **does not import `snntorch`**. It is an event-shaped router (`CTFSpikeRouter`), not a spiking network. |

⚠️ **Runtime gap — a silent downgrade, not a crash.** `snntorch` 0.9.4 is installed
under `miniforge3` (base) but **not under `miniforge3/envs/laforge_py314`**, the
interpreter detached jobs run on (`run_job`). Nothing fails: both modules fall
back, and that is the trap — a correct fallback hides that the intended mode never
ran. Measured 2026-08-28 :

| module | with `snntorch` | without (jobs) |
|---|---|---|
| `forge_snn_core` | backend `snntorch` (Leaky + fast_sigmoid) | backend **`builtin-lif`** — still a real LIF, hand-written in pure torch |
| `forge_snn_monitor` | spiking LIF path | **static threshold compare**, `available()` returns `False`, `enabled=False` |

Both publish which backend they took (`forge_snn_core.available()` returns
`{"torch": …, "snntorch": …}`, and reports `illisible_garde_sandbox` rather than
`False` when the sandbox guard blocks the probe), so the degradation is declared —
read it before attributing a result to "the SNN".

**This is not hypothetical.** The substrate is switched on (`sandbox/snn.wantedd`
is present; `forge_resource_manager` reads it) and has fired **598 `snn`-tagged
events** into `sandbox/lifecycle_actions.jsonl` since 2026-08-04 — re-counted
2026-08-30, latest at `15:31:18 UTC`, five minutes before this line was written
(the ledger holds 7 090 lines, 7 063 valid JSON, 27 unreadable). Every recorded
emitter runs under `laforge_py314` — so until 2026-08-30 **production had only
ever run the fallback**, never the intended `snntorch` path.

**Fixed 2026-08-28** : `snntorch` 1.0.0 installed into `laforge_py314` (owner
action — pip under the sandbox account falls back to a user install and dies on
`C:\Users\Default\Python`, WinError 5). Proven by use, not by a flag :

```
available() -> {'torch': True, 'snntorch': True, 'torch_etat': 'present'}
forge_snn_core.selftest() -> backend='snntorch', acc 0.848 -> 1.0,
                             spikes_last_pass=72875, learned=True
forge_snn_monitor.available() -> True, enabled=True
```

✅ **Live since 2026-08-30.** The sampler runs *inside the hub*
(`sandbox/resource_state.json` → `sampler/pid` = the `NokidoMCP` process) and
`_HAS_SNNTORCH` is captured at import time, so a restart was required — code
installed is not code loaded. Measured after the 17:08 restart: the hub does run on
`miniforge3/envs/laforge_py314/python.exe`, and under that exact interpreter :

```
forge_snn_core.available()    -> {'torch': True, 'snntorch': True, 'torch_etat': 'present'}
forge_snn_monitor.available() -> True
```

Proven by use, not by a flag.

Two notes for anyone auditing this :

- The firings are a **JSONL ledger** (`sandbox/lifecycle_actions.jsonl`), not a
  SQL table. Looking for a table named `spike`/`snn` finds nothing and reads as
  "the substrate never ran" — a fabricated absence. Likewise, the monitor has no
  process of its own: it is *imported into* the hub, so scanning command lines for
  `snn` also finds nothing.
- The ledger timestamps are **UTC** (`+00:00`). Comparing them to a local
  midnight makes a firing from 30 minutes ago look like yesterday's.

### Intel Loihi 2

- Research-grade. 1M neurons, 120 ops/s per neuron.
- Lava framework (Python). Nokido target : port `forge_spike_router`
  + the active inference loop to Lava.

### IBM NorthPole

- Production-grade. 256 cores, ~26B ops/s, **no external DRAM**.
- ResNet-50 inference : 25 ms at 74 W (vs H100 at 700 W for same task).
- **Target** : `brain_worker` embedder. Sub-millisecond retrieval RAG.

### BrainChip Akida

- Production. M.2 form factor.
- **Unsupervised on-chip continual learning** — aligns with Nokido's
  `forge_continual_backprop.py`.
- **Target** : `forge_inspector` + TDR sentinels (always-on monitoring).

### GrAI Matter Labs GrAI-Core

- Event-driven processing.
- **Target** : Deno event bus (`proxy_deno/core/nervous_system.ts`) —
  perfect substrate match.

### Software preparation

`forge_snn_core` → stand-alone service (planned; nothing shipped). Note that
**no `forge_spike_router` module exists** : the name survives only as an
alias entry in `forge_wiki_align` (`"forge_spike_router":
"forge_spike_router"`) and as a comment in `forge_feature_checklist` — a patch
over this page's former wording, not a first step already taken :

1. Extract the SNN cervelet out of the Python module into a stand-alone
   service (HTTP or ZMQ).
2. Abstract the backend : `PyTorch CPU/CUDA → Lava-Loihi → Akida MetaTF`.
3. Stable API ; backend swap is a config flag.

## 🌡️ Phase C — Analog & photonic (24-48 months)

The **von Neumann bottleneck** — separate CPU/RAM with constant electrical
shuttling — is responsible for ~97 % of energy waste in LLM matmul.
Three avenues bypass it :

### Compute-in-memory analog

- **Mythic AI M1076** : matrix multiplication done in analog, 25 TOPS for
  3 W. 8-bit effective precision.
- **IBM Hermes** : in-memory ReRAM-based matmul, 50-100× efficiency.
- **Target** : reranker + classifier fast path. Reduced precision is
  acceptable for the inner loop of `forge_scorecard` and `forge_dt_router`.

### RRAM neuro-vector compute

- **NeuRRAM** (UC San Diego, 2023) : 256 KB ReRAM cells, native
  associative recall.
- **Target** : the **RAG dense retrieval** layer. `FAISS IndexFlatIP` is
  basically associative recall — perfect fit. Watt-second instead of
  joule-second per query.

### Photonic

- **Lightmatter Envise**, **Lightelligence PACE** : matrix multiplication
  at the speed of light. Passive thermal profile.
- 10 000× theoretical efficiency on pure matmul.
- **Target** : the BGE-M3 embedding layer (~3 GFLOP per query at present).

### Software preparation

Nokido's design choice : **the abstraction boundary is the `brain_worker`
Rust service** (`go_services/brain_worker/`). The Python code never sees
the silicon. Swap is a service-binary change, not a Python rewrite.

⚠️ **State as measured 2026-08-28** : the service exists (`Cargo.toml`,
`src/main.rs`, NSSM installer) but ships **one `main.rs` and zero
`backend_*.rs`**. The swap point is declared, not built — a backend adapter has
no seam to plug into yet.

## 🌐 Phase D — Continuous neural grids (48+ months)

Beyond accelerators-as-coprocessors, **analog neural grids** (Rain AI,
Mythic gen-3, IBM Analog AI) will appear as **substrates** — synthetic
cortex on PCIe. At that point :

- The concept of a "pre-trained model" becomes obsolete.
- The grid **learns continuously** from the signal flowing through it.
- Nokido becomes the **interface** between the human and their personal
  neural substrate.

Nokido is ready for this world because :

- AMI + Active Inference + Continual Backprop are designed for **online
  learning**, not batch training.
- The hub abstracts the substrate from the client surface.
- The RAG / membrane / firewall layers are substrate-agnostic.

## ⚡ Energy argument

See [MANIFESTO §6.0](../../MANIFESTO.md#60-pourquoi-le-matériel-est-la-vraie-question--largument-énergétique).
Summary :

- Human brain : ~500 B param equivalent, 20 W.
- H100 GPU : ~80 B param GPT-4-class inference, 700 W.
- Gap : **30 000×**.

The neuromorphic / analog / photonic stack measured today closes that
gap by **100× to 10 000×**. The remaining 3-300× is engineering. The
algorithm-level work (AMI, continual learning, spike-based computation)
is already mostly done.

## 🤝 Contributing accelerator support

If you have an accelerator we don't support :

1. Open an issue on GitHub with the chip model + runtime API.
2. Implement a backend adapter in
   `go_services/brain_worker/src/backend_<vendor>.rs` (Rust) or
   `app/forge_<vendor>_runtime.py` (Python).
3. Update `forge_accelerator_router.py` (when created) to detect it.
4. Add a benchmark in `tools/forge_bench_accelerator.py`.

Welcome PRs :

- AMD ROCm runtime tuning.
- Apple CoreML adapter for the brain_worker.
- Hailo SDK integration sample.
- Lava-Loihi port of `forge_snn_core` (the actual spiking substrate).
- NeuRRAM emulator (for testing the dense-retrieval offload pattern).

## 📊 Benchmark methodology

When we say "100× more efficient" we mean :

- Same task (BGE-M3 inference, ResNet-50, llama-3.3-70b inference, etc.).
- Same quality target (BLEU, accuracy, recall@K).
- Measured at wall power on a representative load.
- Normalized to inferences/joule.

Benchmark scripts (when integrated) : `tools/forge_bench_<chip>.py`.
Run with `pytest -m bench` once we have hardware.

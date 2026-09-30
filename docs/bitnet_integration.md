# BitNet integration — Recipe Nokido

## Pourquoi BitNet ?

BitNet (Microsoft 2024) = LLM dont les poids sont contraints à 3 valeurs
ternaires `{-1, 0, +1}`. Conséquence : la multiplication matricielle
disparaît (devient addition/soustraction/no-op). Mesures observées :

| Modèle | Taille FP16 | Q4_K_M | BitNet 1.58-bit | Gain vs Q4_K_M |
|--------|------------|--------|------------------|----------------|
| 2B    | 4 GB        | 1.3 GB | 0.7 GB           | -46% RAM       |
| 3B    | 6 GB        | 2.0 GB | 1.0 GB           | -50% RAM       |

Pour APU Ryzen 7840U + iGPU Radeon 780M : laisser le GPU à Ollama/Llama,
charger BitNet en CPU pur. Libère VRAM, pas de TDR.

## Recipe pour activer

### 1. Télécharger un modèle BitNet

```bash
cd LaForge/data/llm_models
LAFORGE_PYTHON=~/miniforge3/python.exe
$LAFORGE_PYTHON -m huggingface_hub.commands.huggingface_cli \
    download microsoft/bitnet-b1.58-2B-4T --local-dir .
```

Variantes disponibles :
- `microsoft/bitnet-b1.58-2B-4T` (Microsoft officiel, 2024-2025)
- `1bitLLM/bitnet_b1_58-3B` (community fork, plus capable)
- `HF1BitLLM/Llama3-8B-1.58-100B-tokens` (Llama 3 BitNet 8B)

### 2. Vérifier détection

```bash
$LAFORGE_PYTHON LaForge/tools/forge_bitnet_loader.py
```

Doit retourner `bitnet_models_found >= 1`.

### 3. Activer entry supervisor

Décommenter `NokidoLlamaBitnet` dans `proxy_deno/core/services.toml`
(currently `disabled = true`).

### 4. Restart supervisor (admin)

```powershell
nssm restart LaForge-Master
```

### 5. Test query

```bash
curl http://127.0.0.1:8093/completion \
  -H "Content-Type: application/json" \
  -d '{"prompt": "def fibonacci(n):", "n_predict": 64}'
```

## Compatibilité llama.cpp

Requiert llama.cpp version >= b3700 (support BitNet officiel).
Vérifier :
```bash
~/llama-vulkan/llama-server.exe --version
```

Si version trop ancienne : recompiler depuis source ou télécharger
release récente.

## Routage dans Nokido

Une fois `NokidoLlamaBitnet` actif sur `:8093`, l'ajouter à
`forge_llm_router.USE_CASE_CHAINS` pour les cas où la latence n'est
pas critique (résumés longs, batch ingestion, sandbox isolation) :

```python
USE_CASE_CHAINS["frugal"] = [
    "bitnet:local",        # priorité 1 — RAM minimale
    "qwen2.5-coder:local", # priorité 2 — qualité
    "cerebras:cloud",      # fallback
]
```

## Mesure du gain

Bench Promptfoo via `sandbox/promptfoo_clinical/golden_dataset.yaml`
avec model = bitnet vs qwen2.5-coder.Q4_K_M. Compare RAM watermark
(via `/api/resource/state` snapshot ram_used_gb avant/pendant).

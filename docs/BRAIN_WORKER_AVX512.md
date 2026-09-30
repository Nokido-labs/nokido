# forge_brain_worker — AVX-512 optimization Zen 4 (Ryzen 8700G)

## Etat actuel

Le crate `ort 2.0.0-rc.12` utilise un binaire ONNXRuntime precompile fourni par
le projet Microsoft. Ce binaire est compile pour x86_64 generique avec AVX2
(pas AVX-512 par defaut).

Sur Ryzen 7 8700G (Zen 4), cela signifie qu'on rate les instructions :
- **AVX-512 VNNI** : Vector Neural Network Instructions (INT8 GEMM optimise)
- **AVX-512 BF16** : Brain Float 16 (matmul mixed-precision rapide)
- **AVX-512 F/VL/BW/DQ** : SIMD 512-bit generique

Le matmul du transformer BGE-M3 (560M params) passe la majorite de son temps
sur des dot-products INT8/FP16 → AVX-512 VNNI/BF16 = **gain 1.5-2x mesurable**.

## Etape 1 : Patch deja livre (Rust wrapper code)

`.cargo/config.toml` ajoute :
```toml
[build]
rustflags = [
    "-C", "target-cpu=znver4",
    "-C", "target-feature=+avx512f,+avx512vnni,+avx512bf16,+avx512vl,+avx512bw,+avx512dq,+avx512cd",
]
```

`Cargo.toml [profile.release]` ajoute :
```toml
lto = "fat"
codegen-units = 1
strip = true
panic = "abort"
```

Rebuild :
```powershell
cd go_services\forge_brain_worker
cargo clean
cargo build --release
```

Gain attendu : ~10-20% sur tokenizer + msgpack serialization + Rust glue code.
Les kernels ONNX restent en AVX2 (gain limite).

## Etape 2 : Custom ONNXRuntime build AVX-512 (gain max)

Pour avoir AVX-512 dans les kernels ONNX eux-memes, il faut compiler
onnxruntime from source avec `--use_avx512`.

```powershell
git clone --recursive https://github.com/microsoft/onnxruntime C:\tmp\onnxruntime
cd C:\tmp\onnxruntime

# Build Release avec AVX-512 + DirectML
.\build.bat --config Release --use_avx512 --use_dml --build_shared_lib --parallel --skip_tests `
    --cmake_extra_defines onnxruntime_USE_AVX512=ON `
    --cmake_extra_defines CMAKE_C_FLAGS="/arch:AVX512" `
    --cmake_extra_defines CMAKE_CXX_FLAGS="/arch:AVX512"
```

Temps build : ~30-60 min sur Ryzen 8700G.

Output : `C:\tmp\onnxruntime\build\Windows\Release\Release\onnxruntime.dll`

## Etape 3 : Pointer ort vers custom build

`Cargo.toml` modifier :
```toml
ort = { version = "2.0.0-rc.12", features = ["directml", "half", "load-dynamic"] }
```

Avant `cargo build --release`, set env :
```powershell
$env:ORT_LIB_LOCATION = "C:\tmp\onnxruntime\build\Windows\Release\Release"
$env:ORT_DYLIB_PATH = "$env:ORT_LIB_LOCATION\onnxruntime.dll"
```

Le binaire `forge_brain_worker.exe` chargera dynamiquement onnxruntime.dll
custom au lieu du binaire generique bundle.

## Benchmark cibles

| Config | Throughput estime BGE-M3 batch=20 |
|---|---|
| Actuel (AVX2 generique) | ~500ms |
| Etape 1 (Rust AVX-512) | ~420ms (-15%) |
| Etape 2 (ORT AVX-512 VNNI/BF16) | ~250-280ms (-45%) |
| Bonus DirectML iGPU 780M (post-fix TDR) | ~80-120ms |
| Modal A10G batch=64 | ~10ms/text |

## Tests

```powershell
# Bench wrapper Rust avant/apres rebuild
.\target\release\forge_brain_worker.exe --bench 100

# Verifier features actifs dans le binaire final
cargo rustc --release -- --print target-features
```

## Verification AVX-512 actif

```powershell
# Inspecter binaire pour instructions AVX-512
.\target\release\forge_brain_worker.exe --version
# CPU dispatch logs au startup doivent mentionner :
# "[brain-worker] CPU features: AVX-512 VNNI=yes BF16=yes"
```

(Logging a ajouter dans main.rs si pas deja present.)

## Notes hardware

Ryzen 7 8700G specs :
- 8 cores Zen 4 / 16 threads
- AVX-512 complet (FP, VNNI, BF16, IFMA, VBMI, VBMI2, BITALG, VPOPCNTDQ)
- AMD recommande `znver4` target-cpu

Comparaison : Intel Sapphire Rapids = AVX-512 oui mais "Intel hybrid" Alder/Raptor Lake = AVX-512 disable. Le 8700G a un avantage CPU AVX-512 unique sur le segment grand public 2024-2026.

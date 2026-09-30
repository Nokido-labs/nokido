#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_obs_setup.py — stack observabilité LIBRE (OTel emitter + Jaeger).

Installe `opentelemetry-sdk`/exporter dans **py314** (runtime hub) : le hub ÉMET les
spans via `forge_otel_export` -> OTLP. Le DASHBOARD = **Jaeger** (Apache 2.0, LIBRE).

⚠️ PAS Arize **Phoenix** : licence **Elastic License 2.0** (non-libre, source-available,
interdit hosted-service + contournement de licence) -> **bloqué par `forge_license_guard`**
(SSPL/BSL/Elastic/proprio) + incompatible AGPLv3. (vérifié 2026-06-04, LICENSE du repo.)

Jaeger (hors ce script, au choix) :
  - binaire : releases github.com/jaegertracing/jaeger -> `jaeger-all-in-one`
              (UI :16686, OTLP gRPC :4317 / HTTP :4318)
  - docker  : docker run -p16686:16686 -p4317:4317 -p4318:4318 jaegertracing/all-in-one

SOUVERAIN D'ABORD : `forge_trace_viz` (audit.db -> Mermaid) ne requiert AUCUN backend
ni dépendance externe. Jaeger = bonus dashboard, libre.

INSTALL-ONLY (OTel). Lancer host (hors hub fragile).
"""
from __future__ import annotations

import os
import subprocess
import sys

PY314 = __import__("os").path.expanduser(r"~\miniforge3\envs\laforge_py314\python.exe")
if not os.path.exists(PY314):
    PY314 = sys.executable
OTEL = ["opentelemetry-api", "opentelemetry-sdk", "opentelemetry-exporter-otlp-proto-http"]


def main() -> int:
    r = subprocess.run(
        [PY314, "-m", "pip", "install", "-q", *OTEL],
        capture_output=True, text=True, timeout=1800,
    errors="replace")
    print("otel_py314 rc", r.returncode, (r.stderr or "")[-300:])
    v = subprocess.run(
        [PY314, "-c", "import opentelemetry.sdk; print('otel_sdk_py314 OK')"],
        capture_output=True, text=True,
    errors="replace")
    print("verify_py314", v.stdout.strip(), (v.stderr or "")[-200:])
    print("Dashboard LIBRE = Jaeger (Apache 2.0). PAS Phoenix (ELv2, bloqué forge_license_guard).")
    print("  jaeger-all-in-one -> UI :16686, OTLP :4317/:4318. forge_otel_export défaut :4318.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

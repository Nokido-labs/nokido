#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_cffi_probe.py — sonde DIAGNOSTIC : cffi charge-t-il dans CE contexte d'exécution ?
Distingue 'artefact du sandbox offline le plus verrouillé' vs 'tous les contextes restreints
échouent'. Affiche le user + l'erreur exacte. Jetable (triage cffi 2026-06-13)."""

__FORGE_COLOR__ = "infra/diag : sonde cffi selon le contexte d'execution"  # organe declare le 2026-09-06 (audit de raccordement)
import os

print("USER", os.environ.get("USERNAME"))
try:
    import cffi
    import _cffi_backend  # noqa: F401
    print("CFFI_OK", cffi.__version__)
except Exception as e:  # noqa: BLE001
    print("CFFI_KO", type(e).__name__, str(e)[:150])

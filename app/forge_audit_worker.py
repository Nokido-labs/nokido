"""forge_audit_worker.py — worker de revue READ-ONLY (ForgeAudit).

Audite UN fichier sous UN prisme. Aucune écriture, aucun overlay, aucun Docker :
contexte (M1, lecture disque) + persona (system prompt) → pool.infer(schema=GBNF) →
findings JSON. L'inférence est le pool M3 (borné par sémaphore = discipline mémoire).
"""

from __future__ import annotations

import json

from nokido_agent.app.forge_audit_personas import FINDINGS_SCHEMA, build_persona
from nokido_agent.app.forge_swarm_context import build_worker_context


async def audit_file(target_file, lens, pool, root, *, reference_files=None, emit=None) -> list[dict]:
    """Retourne la liste de findings (dicts) pour (target_file, lens). JSON cassé/backend KO → []."""
    system = build_persona(lens)
    ctx = build_worker_context([target_file], reference_files or [], root)  # lecture seule (disque)
    prompt = f"{system}\n\n# CODE À REVOIR\n{ctx}"
    if emit:
        emit("audit_lens_start", {"file": target_file, "lens": lens})

    findings: list[dict] = []
    try:
        out = await pool.infer(prompt, schema=FINDINGS_SCHEMA, tag=lens)  # tag=lens → routage modèle (LensRoutedPool)
        data = json.loads(out)
        if isinstance(data, dict):
            findings = [f for f in (data.get("findings") or []) if isinstance(f, dict)]
            for f in findings:
                f.setdefault("lens", lens)  # garantit le lens même si le modèle l'omet
    except Exception:
        findings = []  # backend indisponible / JSON invalide → 0 finding (rien à filtrer)

    if emit:
        emit("audit_lens_done", {"file": target_file, "lens": lens, "n": len(findings)})
    return findings

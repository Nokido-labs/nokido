"""tools/patch_job_kill_registry.py — cable le verbe MCP job_kill dans le registre.

Pourquoi un patcher trusted_script et pas governed_edit direct :
app/forge_mcp_registry.py = CRITICAL_FILE (governed_edit refuse, chemin officiel
= patcher committe + run action=trusted_script, precedent 55b9f81e).

Remplacements litteraux avec ASSERT avant/apres (lecon 2026-07-25 : governed_edit
a rendu ok sur une edition PERDUE — verifier le CONTENU relu, jamais le rc).
Idempotent : une paire deja appliquee est SKIP. AST valide AVANT ecriture.

Ce patch livre :
  1. schema tool run : action job_kill + param force + descriptions ;
  2. handle_run : branche job_kill -> forge_job_runner.kill_job (offload executor) ;
  3. run_job : la lane entre dans la fiche du job (kill saura la liberer) ;
  4. fix watcher _watch_job : pollait C:/tmp/nokido_jobs alors que JOBS_DIR =
     sandbox/jobs depuis 2026-07-28 -> lane jamais liberee avant le cap 2 h
     (garde branche sur un signal que rien n'emet).
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

JOB_KILL_BRANCH = (
    '        if act == "job_kill":\n'
    "            # Symetrique de run_job : le hub est l'ANCETRE du job, lui seul peut\n"
    "            # l'arreter (AccessDenied mesure 4 formes cote clients). Offload\n"
    "            # executor : terminate+wait peut tenir ~13 s, jamais dans l'event loop.\n"
    '            jid = args.get("job_id", "")\n'
    "            if not jid:\n"
    '                return "ERR: job_kill: \'job_id\' requis"\n'
    "            if ring > 2:\n"
    '                return "ERR: job_kill: reserve ring<=2 (arret code detache)"\n'
    "            from forge_job_runner import kill_job\n"
    "            import asyncio as _aio_k\n\n"
    "            res_k = await _aio_k.get_event_loop().run_in_executor(\n"
    '                None, lambda: kill_job(jid, bool(args.get("force", False))))\n'
    "            return json.dumps(res_k, ensure_ascii=False)\n"
)

PAIRS = [
    (
        '                                "run_job",\n'
        '                                "job_status",\n'
        "                            ],",
        '                                "run_job",\n'
        '                                "job_status",\n'
        '                                "job_kill",\n'
        "                            ],",
    ),
    (
        'job_status (job_id) pour poll/reprise.",',
        "job_status (job_id) pour poll/reprise ; job_kill (job_id) arrete "
        'l\'arbre du job + libere la lane (le hub est l\'ancetre du job).",',
    ),
    (
        '                        "job_id": {\n'
        '                            "type": "string",\n'
        '                            "description": "job_status: id retourne par run_job '
        '(poll etat running|done, rc, log_tail)",\n'
        "                        },",
        '                        "job_id": {\n'
        '                            "type": "string",\n'
        '                            "description": "job_status/job_kill: id retourne par run_job '
        '(poll etat running|done|killed, rc, log_tail)",\n'
        "                        },\n"
        '                        "force": {\n'
        '                            "type": "boolean",\n'
        '                            "description": "job_kill: accepte un python dont la cmdline '
        'est illisible (identification via la fiche du job seulement)",\n'
        "                        },",
    ),
    (
        "            res = launch_job(\n"
        '                args.get("script") or args.get("path") or "", '
        'bool(args.get("online", False))\n'
        "            )",
        "            res = launch_job(\n"
        '                args.get("script") or args.get("path") or "", '
        'bool(args.get("online", False)),\n'
        '                _lane or "",\n'
        "            )",
    ),
    (
        "                import asyncio as _aio\n"
        "                from pathlib import Path as _P\n\n"
        '                async def _watch_job(jid: str, who: str, lane: str = ""):\n'
        '                    rcf = _P("C:/tmp/nokido_jobs") / f"{jid}.rc"',
        "                import asyncio as _aio\n\n"
        '                async def _watch_job(jid: str, who: str, lane: str = ""):\n'
        "                    # JOBS_DIR a bouge (C:/tmp/nokido_jobs -> sandbox/jobs,\n"
        "                    # 2026-07-28) : ce poll du .rc pointait l'ANCIEN dossier ->\n"
        "                    # lane jamais liberee avant le cap 2 h (garde branche sur\n"
        "                    # un signal que rien n'emet).\n"
        "                    from forge_job_runner import JOBS_DIR as _jobs_dir\n"
        '                    rcf = _jobs_dir / f"{jid}.rc"',
    ),
    (
        "            return json.dumps(read_job(jid), ensure_ascii=False)\n",
        "            return json.dumps(read_job(jid), ensure_ascii=False)\n" + JOB_KILL_BRANCH,
    ),
]


def main() -> int:
    p = ROOT / "app" / "forge_mcp_registry.py"
    src = p.read_text(encoding="utf-8")
    verdicts = []
    for i, (old, new) in enumerate(PAIRS):
        if new in src:
            verdicts.append(f"pair{i}: SKIP (deja appliquee)")
            continue
        if old not in src:
            raise AssertionError(f"pair{i}: motif INTROUVABLE: {old[:90]!r}")
        n = src.count(old)
        if n != 1:
            raise AssertionError(f"pair{i}: motif NON UNIQUE ({n} occurrences)")
        src = src.replace(old, new)
        verdicts.append(f"pair{i}: APPLIQUEE")
    ast.parse(src)  # AST valide AVANT d'ecrire (anti fail-close reboot)
    p.write_text(src, encoding="utf-8")
    relu = p.read_text(encoding="utf-8")
    for i, (_, new) in enumerate(PAIRS):
        if new not in relu:
            raise AssertionError(f"pair{i}: RELECTURE sans le patch (edition perdue)")
    for v in verdicts:
        print(v)
    print("PATCH REGISTRY COMPLET — contenu verifie par relecture.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

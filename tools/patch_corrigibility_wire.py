# -*- coding: utf-8 -*-
"""Patcher one-shot IDEMPOTENT : câble la garde corrigibilité dans le dispatch
(forge_mcp_registry.py = CRITICAL_FILE, governed_edit refuse -> trusted_script).
Insère le gate juste AVANT le gate d'intention. Rejoue = no-op si déjà présent."""
import io
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / "app" / "forge_mcp_registry.py"
MARKER = "from forge_corrigibility import corrigibility_gate"
ANCHOR = ("        # Gate d'intention (Agent Policier) : derive de scope declare. WARN-mode par\n"
          "        # defaut (LAFORGE_INTENTION_GATE_MODE=warn|error|off) -> bloque seulement si error.\n"
          "        # Fail-open : toute erreur -> pas de gate (le dispatch n'est JAMAIS casse).\n"
          "        try:\n"
          "            from forge_intention_gate import gate_tool_call\n")
BLOCK = (
    "        # CORRIGIBILITE (off-switch d'EXECUTION + seuils ASL, organe forge_corrigibility) :\n"
    "        # le kill-switch humain (forge_opsec) doit bloquer les tools MUTANTS au niveau du\n"
    "        # dispatch (pas seulement le restart de service via le watchdog), et les tools a\n"
    "        # forte capacite sont gates par un niveau ASL. read-only reste permis pendant un\n"
    "        # lock (l'humain inspecte). Fail-open : toute erreur -> pas de gate (jamais casse).\n"
    "        try:\n"
    "            from forge_corrigibility import corrigibility_gate\n"
    "\n"
    "            _cg_ok, _cg_reason = corrigibility_gate(name, agent, ring)\n"
    "            if not _cg_ok:\n"
    "                import logging as _lg\n"
    "                _lg.getLogger(\"Nokido.Security\").warning(\n"
    "                    f\"[CORRIGIBILITY] HALT tool={name} agent={agent}: {_cg_reason}\")\n"
    "                return {\"error\": \"corrigibility_halt\", \"reason\": _cg_reason,\n"
    "                        \"tool\": name, \"agent\": agent}\n"
    "        except Exception:\n"
    "            pass  # fail-open : la corrigibilite ne brique jamais le dispatch\n"
    "\n"
)


def main():
    src = TARGET.read_text(encoding="utf-8")
    if MARKER in src:
        print("SKIP: corrigibility gate deja cable (idempotent)")
        return 0
    if ANCHOR not in src:
        print("ERR: ancre introuvable (le fichier a change) — patch NON applique")
        return 2
    new = src.replace(ANCHOR, BLOCK + ANCHOR, 1)
    # validation AST avant ecriture (jamais laisser un .py casse sur un CRITICAL_FILE)
    try:
        compile(new, str(TARGET), "exec")
    except SyntaxError as e:
        print("ERR: AST invalide apres patch, ecriture ANNULEE: %s" % e)
        return 3
    TARGET.write_text(new, encoding="utf-8")
    print("OK: garde corrigibilite cablee dans dispatch (%d -> %d chars)" % (len(src), len(new)))
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.exit(main())

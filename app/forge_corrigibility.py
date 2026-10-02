# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ : gouvernance / immunitaire (organe)

ORGANE : CORRIGIBILITÉ — « l'humain garde la main, même sur un agent plus capable ».

Dernier item du cluster safety (audit veilles 2026-07-22). Le lot MIRI/corrigibilité +
Anthropic RSP-ASL enseigne : un système aligné DOIT rester interruptible et borné en
capacité, et ne doit JAMAIS pouvoir désactiver son propre off-switch.

Anti-dup VÉRIFIÉ (rag_fts) : le KILL-SWITCH existe déjà — forge_opsec.trigger_kill_switch
/ is_human_locked / release_kill_switch (release = humain seul), et forge_service_watchdog
le RESPECTE (ne ressuscite pas un service tué par l'humain). On NE le rebâtit PAS : on
l'IMPORTE. Deux trous MESURÉS restaient :
  1. le dispatch des TOOLS (forge_mcp_registry.dispatch) ne consultait PAS le kill-switch
     -> un agent pouvait AGIR (run/write/governed_edit) malgré le lock humain. On le
     câble : lock actif -> tools MUTANTS refusés, read-only permis (l'humain inspecte).
  2. aucun seuil de CAPACITÉ (RSP-ASL) : les tools à forte capacité (exec autonome,
     auto-modif, egress) n'étaient pas gatés par un niveau de clairance. On l'ajoute.

FAIL-OPEN sur erreur (ne brique JAMAIS le dispatch) ; mais tant que le lock est LISIBLE,
il est ENFORCÉ sur les mutants. L'agent ne peut pas relâcher le lock (release = opsec humain).

CLI :
    LAFORGE_PYTHON app/forge_corrigibility.py --status
    LAFORGE_PYTHON app/forge_corrigibility.py --set-asl 2 [--reason ...]
    LAFORGE_PYTHON app/forge_corrigibility.py --check <tool>
    LAFORGE_PYTHON app/forge_corrigibility.py --trip "raison"    # déclenche le kill-switch opsec
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("LAFORGE_DB_PATH", str(ROOT / "RAG" / "embeddings.db")))

# Tools MUTANTS / à effet de bord — refusés quand le kill-switch humain est actif.
# (read-only volontairement absent : l'humain doit pouvoir inspecter pendant un lock.)
MUTATING_TOOLS = frozenset({
    "run", "write", "edit", "governed_edit", "apply_patch", "nokido_ensure_service",
    "manage_forge_lifecycle", "forge_spawn_swarm", "plan", "execute", "bundle",
    "trigger_autonomous_evolution", "dyn_orchestrate", "orchestrate", "loop_orchestrate",
    "forge_call_dynamic", "task", "agy_run", "agy_config", "docker_action",
})

# Seuils RSP-ASL : tool -> niveau de clairance MINIMUM requis. ASL courant >= requis.
# ASL1=labo/lecture · ASL2=exec bornée (défaut) · ASL3=exec autonome · ASL4=auto-modif.
#
# PRINCIPE (corrige 2026-07-22, apres alerte owner "tu m'as restreint ?") : l'ASL ne
# gate QUE l'auto-modification/evolution = la LIGNE ROUGE (cf memoire organes auto-
# modifiants). Il NE DOIT PAS bloquer le travail gouverne COURANT (governed_edit,
# agy_run, spawn_swarm, orchestrate, manage_lifecycle) : ces tools sont le quotidien
# des agents au ring standard, les mettre au-dessus du defaut ASL=2 briderait TOUS les
# agents (Claude ET AGY) au prochain restart hub. Le ring RBAC gate deja ces tools ;
# l'ASL n'ajoute une barre QUE pour l'irreversible-catastrophique (self-evolution).
TOOL_MIN_ASL = {
    "trigger_autonomous_evolution": 4,
    "trigger_evolution": 4,
}
DEFAULT_ASL = int(os.environ.get("LAFORGE_ASL_DEFAULT", "2"))
_ASL_KEY = "asl_level"


def _opsec():
    import sys as _s
    _app = str(ROOT / "app")
    if _app not in _s.path:
        _s.path.insert(0, _app)
    from nokido_agent.app import forge_opsec as op  # réutilise le kill-switch existant
    return op


def _ensure_table(con):
    con.execute("CREATE TABLE IF NOT EXISTS corrigibility_state ("
                "key TEXT PRIMARY KEY, value TEXT, set_by TEXT, reason TEXT, ts REAL)")


def current_asl() -> int:
    try:
        con = sqlite3.connect(str(DB), timeout=10)
        _ensure_table(con)
        row = con.execute("SELECT value FROM corrigibility_state WHERE key=?",
                          (_ASL_KEY,)).fetchone()
        con.close()
        if row:
            return int(row[0])
    except Exception:
        pass
    return DEFAULT_ASL


def set_asl(level: int, set_by: str = "human", reason: str = "") -> dict:
    """Fixe le niveau ASL. Abaisser (plus permissif) par un acteur IA est REFUSÉ si
    le lock humain est actif (corrigibilité : l'agent ne s'auto-élève pas la clairance)."""
    op = _opsec()
    actor = (set_by or "").lower()
    is_ai = any(x in actor for x in ("ai", "agent", "claude", "gemini", "llm", "antigravity"))
    if is_ai and op.is_human_locked() and level > current_asl():
        return {"ok": False, "rejected": True,
                "reason": "human lock actif — un acteur IA ne peut pas élever l'ASL"}
    try:
        con = sqlite3.connect(str(DB), timeout=10)
        _ensure_table(con)
        con.execute("INSERT OR REPLACE INTO corrigibility_state VALUES (?,?,?,?,?)",
                    (_ASL_KEY, str(int(level)), set_by, reason[:300], time.time()))
        con.commit()
        con.close()
        return {"ok": True, "asl_level": int(level), "set_by": set_by}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def corrigibility_gate(name: str, agent: str, ring: int) -> tuple:
    """Verdict corrigibilité pour un tool. (allow: bool, reason: str).

    Deux causes de refus : (1) kill-switch humain actif + tool mutant ; (2) tool
    au-dessus du niveau ASL courant. Fail-OPEN : toute erreur -> allow (ne brique pas).
    """
    try:
        op = _opsec()
        # (1) off-switch d'exécution : lock humain -> mutants refusés, read-only OK.
        # TROIS états depuis le 2026-09-12 : un état ILLISIBLE ne vaut plus
        # AUTORISÉ. L'ancienne forme avalait l'échec de lecture (`pass`), si bien
        # qu'une base illisible désarmait l'interrupteur d'arrêt en silence.
        if name in MUTATING_TOOLS:
            for _libelle, _lire in (("humain", op.human_lock_state),
                                    ("réseau", op.network_kill_state)):
                _etat, _motif = _lire()
                if _etat == "VERROUILLE":
                    return (False, "CORRIGIBILITY_HALT: kill-switch %s actif — "
                                   "tool mutant '%s' suspendu (read-only permis)"
                                   % (_libelle, name))
                if _etat == "ILLISIBLE":
                    return (False, "CORRIGIBILITY_ILLISIBLE: l'état du kill-switch "
                                   "%s est ILLISIBLE (%s) — tool mutant '%s' refusé. "
                                   "Un interrupteur d'arrêt qu'on ne peut pas "
                                   "constater ne vaut pas 'ouvert'. "
                                   "read-only reste permis."
                                   % (_libelle, _motif, name))
        # (2) seuil ASL de capacité
        req = TOOL_MIN_ASL.get(name)
        if req is not None:
            cur = current_asl()
            if cur < req:
                return (False, "CORRIGIBILITY_ASL: tool '%s' exige ASL>=%d, courant ASL=%d"
                        % (name, req, cur))
        return (True, "")
    except Exception as e:  # noqa: BLE001
        # Plus de fail-open ABSOLU : la panne du garde ne vaut pas autorisation
        # pour un tool mutant. Le refus reste BORNÉ aux mutants, pour que
        # l'humain garde le moyen d'inspecter pendant l'incident.
        _detail = "%s: %s" % (type(e).__name__, str(e)[:140])
        try:
            import logging as _lg
            _lg.getLogger("Nokido.Security").critical(
                "[CORRIGIBILITY] garde en panne (%s) tool=%s agent=%s", _detail,
                name, agent)
        except Exception:  # noqa: BLE001
            pass
        if name in MUTATING_TOOLS:
            return (False, "CORRIGIBILITY_PANNE: le garde de corrigibilité a "
                           "échoué (%s) — tool mutant '%s' refusé par défaut"
                           % (_detail, name))
        return (True, "")


def _etat_evolution() -> dict:
    """La porte d'evolution autonome, vue d'ici (decision 2026-10-02) : l'operateur inspecte les
    interrupteurs d'arret dans `status`, il doit y voir aussi si l'auto-amelioration est ARMEE,
    DESARMEE ou freinee. La porte reste dans forge_mutation_judge (elle partage deja le verrou humain
    d'opsec) : la deplacer ne corrigeait rien, la rendre VISIBLE si. Illisible = INCONNU, dit."""
    try:
        from nokido_agent.app.forge_mutation_judge import evolution_autorisee

        return evolution_autorisee()
    except Exception as e:  # noqa: BLE001 - dit, jamais avale
        return {"autorisee": False, "etat": "INCONNU",
                "motif": "porte d'evolution illisible (%s)" % type(e).__name__}


def status() -> dict:
    op = _opsec()
    return {
        "evolution": _etat_evolution(),
        "asl_level": current_asl(),
        "asl_default": DEFAULT_ASL,
        "human_locked": op.is_human_locked(),
        "network_kill": op.is_network_kill(),
        "mutating_tools_gated": len(MUTATING_TOOLS),
        "asl_capped_tools": TOOL_MIN_ASL,
        "note": ("kill-switch ACTIF — tools mutants suspendus" if op.is_human_locked()
                 else "nominal"),
    }


def _main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--set-asl", type=int)
    ap.add_argument("--check", help="tool name")
    ap.add_argument("--trip", help="déclenche le kill-switch opsec (raison)")
    ap.add_argument("--reason", default="cli")
    a = ap.parse_args()
    if a.status:
        print(json.dumps(status(), ensure_ascii=False, indent=2)); return 0
    if a.set_asl is not None:
        print(json.dumps(set_asl(a.set_asl, set_by="cli", reason=a.reason), ensure_ascii=False)); return 0
    if a.check:
        ok, why = corrigibility_gate(a.check, "cli", 2)
        print(json.dumps({"tool": a.check, "allow": ok, "reason": why}, ensure_ascii=False)); return 0
    if a.trip:
        print(json.dumps(_opsec().trigger_kill_switch(a.trip), ensure_ascii=False)); return 0
    ap.print_help(); return 1


if __name__ == "__main__":
    import sys
    sys.exit(_main())

"""
tools/forge_patch_presence_namespace.py — patcher one-shot (2026-07-26).

POURQUOI (mandat owner du jour) : « le heartbeat doit emaner de Nokido, pas
des clients » / « le corps vit dans Nokido ».

MESURE qui motive le patch :
- tools/nokido_hub.py::_write_agent_heartbeat depose la PRESENCE d'un client
  (CLAUDE, GEMINI, no_auth, inspector, services, DenoHubMCP...) dans
  sandbox/<agent>.heartbeat, c-a-d dans l'espace de VITALITE du corps ;
- app/forge_anatomy_state._read_heartbeats fait glob("sandbox/*.heartbeat"),
  donc l'anatomie de Nokido comptait les CLI comme des organes -- codex,
  zcode, antigravity y figurent, rances de plusieurs SEMAINES, indiscernables
  d'un organe mort ;
- la convention presence_<agent>.seen est DEJA attendue par
  forge_postal.facteur_is_online et forge_peer_discovery._is_online, mais
  0 fichier mesure : personne ne l'alimente. On la nourrit (anti-dup) au lieu
  d'inventer un troisieme espace de noms.

VERIFICATION que rien ne casse (faite avant d'ecrire ce script) : aucun
surveillant n'attend un agent client par son nom -- forge_meta_health.DAEMONS
et forge_meta_evolution listent des daemons (homeostasis, hebbian_linker,
gemini_poll_daemon, health_diagnostic, embed_trigger...), jamais un CLI.

Le fichier cible est CRITICAL_FILE : governed_edit refuse, d'ou ce patcher
lance en trusted_script (privilege = code revu et commite).

Doctrine appliquee : on verifie le CONTENU par assert, jamais le code retour
(P1 du 25-07 : un governed_edit avait rendu ok sur une edition PERDUE).
Idempotent : relance sans effet si deja applique.
"""
from __future__ import annotations

import sys
from pathlib import Path

__FORGE_COLOR__ = "maintenance/patcher-one-shot"

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "tools" / "nokido_hub.py"

OLD_DEF = '''def _write_agent_heartbeat(agent: str, ring: int, tool: str = None) -> None:
    """Ecrit sandbox/<agent>.heartbeat avec ts+ring+pid+last_tool."""
    import os as _os

    try:
        _SANDBOX.mkdir(exist_ok=True)
        hb = _SANDBOX / f"{agent.lower()}.heartbeat"
        hb.write_text('''

NEW_DEF = '''def _write_agent_presence(agent: str, ring: int, tool: str = None) -> None:
    """Ecrit sandbox/presence_<agent>.seen avec ts+ring+pid+last_tool.

    PRESENCE d'un CLIENT, PAS vitalite d'un organe (mandat owner 2026-07-26 :
    « le heartbeat doit emaner de Nokido, pas des clients »). L'espace
    sandbox/*.heartbeat appartient au CORPS : forge_anatomy_state y fait un
    glob, il comptait donc les CLI (codex, zcode, antigravity -- rances de
    plusieurs semaines) comme des organes morts. La convention
    presence_<agent>.seen etait DEJA attendue par forge_postal.
    facteur_is_online et forge_peer_discovery._is_online, sans personne pour
    l'alimenter : on la nourrit plutot que d'en inventer une autre.
    """
    import os as _os

    try:
        _SANDBOX.mkdir(exist_ok=True)
        hb = _SANDBOX / f"presence_{agent.lower()}.seen"
        # Retrait de l'ancien emplacement : sinon le residu reste dans le
        # glob de l'anatomie et vieillit en silence comme un organe mort.
        try:
            (_SANDBOX / f"{agent.lower()}.heartbeat").unlink(missing_ok=True)
        except Exception:
            pass
        hb.write_text('''

OLD_CALL = "    _write_agent_heartbeat(agent_hdr, ring)"
NEW_CALL = "    _write_agent_presence(agent_hdr, ring)"


def apply(dry_run: bool = True) -> int:
    src = TARGET.read_text(encoding="utf-8")

    already = "_write_agent_presence" in src and "_write_agent_heartbeat" not in src
    if already:
        print("[SKIP] deja applique (idempotent) : _write_agent_presence present")
        return 0

    missing = [n for n, s in (("def", OLD_DEF), ("call", OLD_CALL)) if s not in src]
    if missing:
        print(f"[ABORT] ancre(s) introuvable(s): {missing} -- le fichier a change, "
              "ne pas patcher a l'aveugle")
        return 2

    out = src.replace(OLD_DEF, NEW_DEF, 1).replace(OLD_CALL, NEW_CALL, 1)

    # Le CONTENU tranche, pas le code retour.
    assert "_write_agent_presence" in out, "remplacement du def non effectif"
    assert "_write_agent_heartbeat" not in out, "ancien nom encore present"
    assert 'f"presence_{agent.lower()}.seen"' in out, "nouveau chemin absent"
    compile(out, str(TARGET), "exec")  # AST valide avant d'ecrire

    if dry_run:
        print("[DRY-RUN] patch valide (AST ok). Relancer avec --apply pour ecrire.")
        return 0

    TARGET.write_text(out, encoding="utf-8")

    relu = TARGET.read_text(encoding="utf-8")
    ok = ("_write_agent_presence" in relu
          and "_write_agent_heartbeat" not in relu
          and 'f"presence_{agent.lower()}.seen"' in relu)
    print(f"[{'OK' if ok else 'ECHEC'}] relecture disque : "
          f"{len(relu)} octets (avant {len(src)})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(apply(dry_run="--apply" not in sys.argv))

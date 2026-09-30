"""Pose le JSON des intents offensifs dans le depot redteam via le profil OWNER.

Contexte (owner 2026-09-26) : les intents offensifs (ring>=3) ont ete sortis du coeur par
tools/patch_trajectory_offensive_redteam.py ; le JSON produit est sous sandbox/workspace, mais
le depot redteam appartient au profil owner et ni le compte trusted ni celui de session n'y
ecrivent. `forge_owner_bridge.run_in_owner` execute dans la console owner -- le profil capable.

Ce script ne NOMME aucun intent : il ne manipule que des chemins. Il copie le JSON dans redteam
puis liste la cible pour PROUVER l'ecriture (verdict lu sur l'artefact, pas sur le rc)."""
from __future__ import annotations

import sys

RACINE = r"%NOKIDO_ROOT%"
SRC = RACINE + r"\sandbox\workspace\offensive_intents.json"
DST = r"%NOKIDO_WORKSPACE%\redteam\offensive_intents.json"

sys.path.insert(0, RACINE)
from nokido_agent.tools.forge_owner_bridge import run_in_owner  # noqa: E402

r = run_in_owner([f'copy /Y "{SRC}" "{DST}"', f'dir "{DST}"'], timeout=60.0)
print("[finish] owner user=%s ok=%s rc=%s timed_out=%s" % (r.get("user"), r.get("ok"), r.get("rc"), r.get("timed_out")))
print("[finish] stdout:\n" + (r.get("stdout") or "")[:1000])
sys.exit(0 if r.get("ok") and (r.get("rc") in (None, "0")) else 1)

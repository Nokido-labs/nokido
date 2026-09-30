# -*- coding: utf-8 -*-
"""NR - seuil du kill-watchdog de boucle du hub (2026-09-05).

Mesure : 22 WEDGE KILL dans logs/loop_lag.log. Seuil 60 s (31/08 -> 03/09) :
6 kills en 4 jours, tous "gele 60s" (vrais wedges). Seuil 15 s (commit
087956782, 03/09 19:30) : 16 kills en 2 jours, TOUS "gele 16-17s". La pile du
loop au kill : forge_mcp_registry.handle_notify, INSERT agent_messages dans
RAG/embeddings.db, synchrone, PRAGMA busy_timeout=15000. Un verrou tenu par un
autre ecrivain = 15 s d'attente -> kill a 15 s -> respawn -> prewarm -> disque
sature -> verrous plus longs -> kill suivant.

Ce que ce test verrouille, par lecture des SOURCES (aucun import du hub) :
  1. le defaut passe par nokido_hub a start_kill_watchdog est celui du module ;
  2. ce defaut est STRICTEMENT superieur au plus long busy_timeout synchrone de
     handle_notify (le blocage tolere ne doit jamais devenir une mort) ;
  3. la valeur 15 n'est plus le defaut.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HUB = ROOT / "tools" / "nokido_hub.py"
SENTINEL = ROOT / "app" / "forge_loop_sentinel.py"
REGISTRY = ROOT / "app" / "forge_mcp_registry.py"

_RX_HUB = re.compile(
    r'_loop_kill_start\(\s*kill_after_s\s*=\s*float\(\s*os\.environ\.get\(\s*'
    r'"LAFORGE_LOOP_KILL_S"\s*,\s*"(\d+(?:\.\d+)?)"\s*\)\s*\)\s*\)'
)
_RX_MOD = re.compile(
    r'os\.environ\.get\(\s*"LAFORGE_LOOP_KILL_S"\s*,\s*"(\d+(?:\.\d+)?)"\s*\)'
)
_RX_DEF = re.compile(r"def start_kill_watchdog\(kill_after_s: float = (\d+(?:\.\d+)?)")


def _lire(p: Path) -> str:
    if not p.exists():
        pytest.skip(f"{p.relative_to(ROOT)} absent : test non applicable ici")
    return p.read_text(encoding="utf-8", errors="replace")


def seuil_hub() -> float:
    m = _RX_HUB.search(_lire(HUB))
    assert m, "nokido_hub n'arme plus start_kill_watchdog via LAFORGE_LOOP_KILL_S"
    return float(m.group(1))


def seuils_module() -> set[float]:
    src = _lire(SENTINEL)
    vals = {float(v) for v in _RX_MOD.findall(src)}
    vals |= {float(v) for v in _RX_DEF.findall(src)}
    assert vals, "forge_loop_sentinel ne declare plus de defaut lisible"
    return vals


def busy_timeouts_handle_notify() -> list[int]:
    """Les PRAGMA busy_timeout du corps de handle_notify, en millisecondes.

    Le corps s'arrete au prochain `def`/`async def` de meme indentation.
    Liste vide = la fonction a ete refondue sans SQLite synchrone : le test 2
    est alors sans objet, il le DIT (skip) au lieu de passer en silence.
    """
    src = _lire(REGISTRY)
    m = re.search(r"^([ \t]*)(?:async\s+)?def handle_notify\b", src, re.M)
    assert m, "handle_notify introuvable dans forge_mcp_registry"
    indent = m.group(1)
    suite = src[m.end():]
    fin = re.search(r"^" + re.escape(indent) + r"(?:async\s+)?def\s", suite, re.M)
    corps = suite[: fin.start()] if fin else suite
    return [int(v) for v in re.findall(r"busy_timeout\s*=\s*(\d+)", corps)]


def test_defaut_hub_est_celui_du_module():
    assert seuil_hub() in seuils_module(), (
        f"le hub passe {seuil_hub()} s, le module declare {sorted(seuils_module())} : "
        "deux defauts pour un seul garde = un piege de relecture (le 03/09 le hub "
        "disait 15 quand le module disait 60)"
    )


def test_seuil_kill_strictement_superieur_au_blocage_synchrone_tolere():
    bt = busy_timeouts_handle_notify()
    if not bt:
        pytest.skip("handle_notify n'a plus de busy_timeout synchrone : invariant sans objet")
    plus_long_s = max(bt) / 1000.0
    assert seuil_hub() > plus_long_s + 1.0, (
        f"seuil de kill {seuil_hub()} s <= busy_timeout {plus_long_s} s (+1 s de marge) "
        "de handle_notify : chaque attente de verrou devient une mort du hub "
        "(16 kills 'gele 16-17s' les 04-05/09)"
    )


def test_quinze_n_est_plus_le_defaut():
    assert seuil_hub() != 15.0, "retour de la regression du commit 087956782"


def test_kill_zero_reste_un_opt_out():
    # Le module documente kill_after_s<=0 = desactive ; on verifie que la porte
    # existe encore (sinon LAFORGE_LOOP_KILL_S=0 armerait un kill immediat).
    src = _lire(SENTINEL)
    assert re.search(r"if\s+kill_after_s\s*<=\s*0\s*:", src), (
        "l'opt-out kill_after_s<=0 a disparu de start_kill_watchdog"
    )

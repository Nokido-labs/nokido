# -*- coding: utf-8 -*-
"""NR (derogation owner 19/10 ~21 h 45) -- le chemin de CONFIANCE porte aussi sa classe Hamilton.

Reste de bb:decision_owner_hamilton_arene_vibe_capture_20261016 (verifie par ANTIGRAVITY job_8dc0ace8 puis sur piece) :
`ensure_service` et `docker ensure-daemon` (app/forge_mcp_registry.py) passent par `spawn_as_trusted`, qui n'acceptait
pas de classe -- la carte des appelants (d50229242) les comptait « sans classe ». Le gate Hamilton n'agit pas sur le
compte de confiance (forge_sandbox_exec, `user != USER_TRUSTED`) : la classe y sert la TRACABILITE, pas un refus.
Contrat :
  1. `spawn_as_trusted(cmd, classe=...)` transmet la classe a `spawn_as_sandbox` ; defaut NORMAL ;
  2. les deux appels du registre (ensure_service, docker ensure-daemon) declarent classe="CRITIQUE".
"""
import ast
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from nokido_agent.app import forge_sandbox_exec as se  # noqa: E402


def test_spawn_as_trusted_transmet_sa_classe(monkeypatch):
    vus = []
    monkeypatch.setattr(se, "spawn_as_sandbox", lambda command, **kw: vus.append(kw) or {"ok": True})
    se.spawn_as_trusted("x", classe="CRITIQUE")
    se.spawn_as_trusted("y")
    assert vus[0].get("classe") == "CRITIQUE" and vus[0].get("user") == se.USER_TRUSTED
    assert vus[1].get("classe", "NORMAL") == "NORMAL"


def test_les_deux_appels_critiques_du_registre_declarent_leur_classe():
    src = (RACINE / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8")
    lignes = src.splitlines()
    vus = {}
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "spawn_as_trusted":
            voisinage = "\n".join(lignes[max(0, n.lineno - 12):n.lineno])
            for cle in ("--service {svc} --state", "--ensure-daemon"):
                if cle in voisinage:
                    kw = {k.arg: getattr(k.value, "value", None) for k in n.keywords}
                    vus[cle] = kw.get("classe")
    assert set(vus) == {"--service {svc} --state", "--ensure-daemon"}, vus
    assert all(v == "CRITIQUE" for v in vus.values()), vus

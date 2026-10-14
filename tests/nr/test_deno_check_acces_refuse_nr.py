# -*- coding: utf-8 -*-
"""NR — `tools/forge_deno_check.py` face a un deno qu'il ne peut pas executer : ILLISIBLE + remede, jamais muet.

__FORGE_COLOR__ = "qualite/build : non-regression du verificateur deno sous compte de service"

CE QUI A ÉTÉ PAYÉ (2026-10-12). Lance en trusted_script (LaForgeTrusted), l'outil mourait en
`deno check failed to run: [WinError 5]` : le compte n'executait plus `~/.deno/bin/deno.exe` (`deno upgrade`
remplace l'exe, et l'autorisation posee sur l'ancien fichier part avec lui). L'echec ne disait ni que RIEN n'avait
ete verifie, ni comment reparer. Le test passe par `main()`, le point d'entree reel.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _outil():
    spec = importlib.util.spec_from_file_location("forge_deno_check_nr", ROOT / "tools" / "forge_deno_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_un_deno_inexecutable_rend_illisible_et_le_remede(monkeypatch, capsys):
    mod = _outil()
    faux = r"C:\Users\Quelqu_un\.deno\bin\deno.exe"
    monkeypatch.setattr(mod, "_find_deno", lambda: faux)

    def refuse(*a, **k):
        raise PermissionError(5, "Acces refuse")

    monkeypatch.setattr(mod.subprocess, "run", refuse)
    monkeypatch.setattr(mod.sys, "argv", ["forge_deno_check.py", "proxy_deno/core/supervisor.ts"])
    rc = mod.main()
    sortie = capsys.readouterr().out
    assert rc == 4, sortie
    assert "ILLISIBLE" in sortie and "Rien n'a ete verifie" in sortie
    assert r'icacls "C:\Users\Quelqu_un\.deno" /grant "LaForgeTrusted:(OI)(CI)RX"' in sortie, sortie


def test_un_cache_deno_herite_non_inscriptible_est_remplace(monkeypatch, tmp_path):
    """Second mur du 2026-10-12 : deno s'executait, mais son cache herite (profil owner) refusait l'ecriture."""
    mod = _outil()
    monkeypatch.setattr(mod, "_inscriptible", lambda d: bool(d) and d.startswith(str(tmp_path)))
    monkeypatch.setattr(mod.tempfile, "gettempdir", lambda: str(tmp_path))
    vus = {}

    def capte(cmd, **k):
        vus["env"] = k.get("env") or {}
        return mod.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(mod, "_find_deno", lambda: r"C:\deno\deno.exe")
    monkeypatch.setattr(mod.subprocess, "run", capte)
    monkeypatch.setenv("DENO_DIR", r"C:\Users\Quelqu_un\AppData\Local\deno")
    monkeypatch.setattr(mod.sys, "argv", ["forge_deno_check.py", "proxy_deno/core/supervisor.ts"])
    assert mod.main() == 0
    assert vus["env"].get("DENO_DIR", "").startswith(str(tmp_path)), vus["env"].get("DENO_DIR")

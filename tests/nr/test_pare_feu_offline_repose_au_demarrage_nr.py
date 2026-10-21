"""NR -- la coupure reseau du compte laforge-sandbox-offline survit au redemarrage (Linux, macOS) -- 20/10.

Mesure du 20/10 (audit « pas une version publique au rabais ») : `forge_sandbox_setup.posix_pare_feu` pose la regle
(iptables/ip6tables sous Linux, ancre pf com.apple/nokido sous macOS) UNE fois, a l'installation. Rien ne la repose :
`iptables -A` ne survit pas au redemarrage, l'ancre pf n'est pas chargee au boot et pf n'y est pas active. Apres un
redemarrage, le compte hors ligne retrouvait donc le reseau. Sous Windows, la regle New-NetFirewallRule persiste
d'elle-meme. Et la vieille branche WITH_SANDBOX_USERS d'install.sh se contentait de « configure pfctl manually ».

Garde : `forge_sandbox_setup.py --pare-feu` ne repose QUE le pare-feu (idempotent) ; le superviseur root l'appelle
avant de demarrer -- `ExecStartPre` sans « - » (fail-closed) sous systemd, enchaine avant le superviseur dans le
LaunchDaemon ; install.sh n'abandonne plus macOS a la main.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]


def _charger(rel, nom):
    spec = importlib.util.spec_from_file_location(nom, RACINE / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_l_unite_systemd_repose_le_pare_feu_avant_le_superviseur():
    ib = _charger("tools/install_boot_hook.py", "boot_hook_pare_feu_nr")
    lignes = ib.unite_systemd({}).splitlines()
    pre = [i for i, l in enumerate(lignes) if l.startswith("ExecStartPre=")]
    start = [i for i, l in enumerate(lignes) if l.startswith("ExecStart=")]
    assert pre and start and pre[0] < start[0], lignes
    assert "forge_sandbox_setup.py --pare-feu" in lignes[pre[0]], lignes[pre[0]]
    assert not lignes[pre[0]].startswith("ExecStartPre=-"), "fail-closed : un pare-feu non pose ne se tait pas"


def test_le_launchdaemon_repose_le_pare_feu_avant_le_superviseur():
    ib = _charger("tools/install_boot_hook.py", "boot_hook_pare_feu_mac_nr")
    plist = ib.daemon_launchd({})
    assert "forge_sandbox_setup.py" in plist and "--pare-feu" in plist, plist
    assert str(ib.SUPERVISOR) in plist and plist.index("--pare-feu") < plist.index(str(ib.SUPERVISOR)), plist


def test_l_option_pare_feu_ne_pose_que_le_pare_feu(monkeypatch):
    """Chemin reel : `main()` et son drapeau CLI, sur une plateforme POSIX simulee."""
    ss = _charger("tools/forge_sandbox_setup.py", "sandbox_setup_pare_feu_nr")
    appels = []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(ss, "posix_pare_feu", lambda: appels.append("pf") or "iptables OK, ip6tables OK")
    for interdit in ("posix_groupe", "posix_utilisateur", "posix_acl"):
        monkeypatch.setattr(ss, interdit, lambda *a, _n=interdit, **k: pytest.fail("%s appele" % _n))
    monkeypatch.setattr(sys, "argv", ["forge_sandbox_setup.py", "--pare-feu"])
    assert ss.main() == 0
    assert appels == ["pf"]


def test_install_sh_n_abandonne_plus_macos_a_la_main():
    texte = (RACINE / "install.sh").read_text(encoding="utf-8")
    assert "configure pfctl manually" not in texte
    assert "forge_sandbox_setup.py --pare-feu" in texte

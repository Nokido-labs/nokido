# -*- coding: utf-8 -*-
"""runAs sous Linux / macOS (decision owner du 2026-10-09, « Go, superviseur root »).

Mesure 4 de l'organisme (run 37917879256) : sous Linux et macOS, les 10 services runAs mouraient sur
`No module named 'win32event'` -- le lanceur n'avait qu'une branche Windows. Patron retenu : comptes systeme DEDIES,
superviseur en root (equivalent de SYSTEM), enfant qui meurt avec son lanceur, refus DIT hors root.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.timeout(60)


def _lanceur():
    spec = importlib.util.spec_from_file_location("forge_runas_launcher_nr", ROOT / "tools" / "forge_runas_launcher.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_les_modes_correspondent_a_des_comptes_dedies_jamais_root():
    m = _lanceur()
    assert m.utilisateur_posix("sandbox-offline", {}) == "nokido-sbx-offline"
    assert m.utilisateur_posix("sandbox-online", {}) == "nokido-sbx-online"
    assert m.utilisateur_posix("interactive", {"NOKIDO_UTILISATEUR": "alice"}) == "alice"
    assert m.utilisateur_posix("interactive", {"NOKIDO_UTILISATEUR": "root"}) is None
    assert m.utilisateur_posix("interactive", {}) is None


def test_hors_root_le_lanceur_refuse_et_le_dit(monkeypatch, capsys):
    m = _lanceur()
    monkeypatch.setattr(m.os, "geteuid", lambda: 1000, raising=False)
    assert m.main_posix("sandbox-offline", ["python", "-V"]) == 1
    assert "REFUS" in capsys.readouterr().err


def test_sous_root_l_enfant_tourne_sous_le_compte_dedie_sans_groupes_herites(monkeypatch):
    m = _lanceur()
    monkeypatch.setattr(m.os, "geteuid", lambda: 0, raising=False)
    faux_pwd = types.SimpleNamespace(getpwnam=lambda n: types.SimpleNamespace(pw_uid=901, pw_gid=902,
                                                                             pw_dir="/nonexistent"))
    monkeypatch.setitem(sys.modules, "pwd", faux_pwd)
    monkeypatch.setattr(m, "_preparer_environnement", lambda environ: "0 secret(s) herite(s) retire(s)")
    vus = {}

    class FauxProc:
        pid = 4242

        def wait(self):
            return 0

        def terminate(self):
            pass

    def faux_popen(argv, **k):
        vus.update(k, argv=argv)
        return FauxProc()
    monkeypatch.setattr(m.subprocess, "Popen", faux_popen)
    monkeypatch.setattr(m, "signal", None, raising=False)
    import signal as vrai
    monkeypatch.setattr(vrai, "signal", lambda *a, **k: None)
    assert m.main_posix("sandbox-offline", ["python", "-V"]) == 0
    assert vus["user"] == 901 and vus["group"] == 902 and vus["extra_groups"] == []
    assert vus["env"]["USER"] == "nokido-sbx-offline" and vus["preexec_fn"] is m._mourir_avec_le_parent


def test_la_voie_posix_est_prise_avant_tout_import_pywin32():
    src = (ROOT / "tools" / "forge_runas_launcher.py").read_text(encoding="utf-8")
    corps = src[src.index("def main() -> int:"):]
    assert corps.index('if os.name != "nt":') < corps.index("import win32event")


def _setup():
    spec = importlib.util.spec_from_file_location("forge_sandbox_setup_posix_nr", ROOT / "tools" / "forge_sandbox_setup.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _R:
    def __init__(self, rc=0, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, ""


def test_le_provisionnement_posix_refuse_hors_root(monkeypatch, capsys):
    s = _setup()
    monkeypatch.setattr(s.os, "geteuid", lambda: 1000, raising=False)
    assert s.main_posix(types.SimpleNamespace(status=False, teardown=False)) == 1
    assert "root" in capsys.readouterr().out


def test_comptes_linux_systeme_sans_shell_ni_dossier(monkeypatch):
    s = _setup()
    appels = []
    monkeypatch.setattr(s, "MAC", False)
    monkeypatch.setattr(s, "_posix_existe", lambda nom, groupe=False: False)
    monkeypatch.setattr(s, "_run", lambda cmd, check=False: appels.append(cmd) or _R())
    assert s.posix_utilisateur("nokido-sbx-offline", "nokido-sbx") == "cree"
    assert appels[0] == ["useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", "--gid",
                         "nokido-sbx", "nokido-sbx-offline"]


def test_pare_feu_linux_par_uid_loopback_ouvert_et_jamais_en_double(monkeypatch):
    s = _setup()
    appels = []
    monkeypatch.setattr(s, "MAC", False)
    monkeypatch.setattr(s.shutil, "which", lambda n: "/usr/sbin/" + n)
    # -C rend 0 : la regle existe deja -> aucun -A
    monkeypatch.setattr(s, "_run", lambda cmd, check=False: appels.append(cmd) or _R(0))
    s.posix_pare_feu()
    assert all(c[1] == "-C" for c in appels), "regle presente : jamais ajoutee une seconde fois"
    regle = appels[0][2:]
    assert "--uid-owner" in regle and regle[regle.index("--uid-owner") + 1] == "nokido-sbx-offline"
    assert regle[regle.index("-o") - 1] == "!" and regle[regle.index("-o") + 1] == "lo", "le loopback reste ouvert"


def test_identifiant_libre_macos_sous_500(monkeypatch):
    s = _setup()
    monkeypatch.setattr(s, "_run", lambda cmd, check=False: _R(0, "a 450\nb 451\nc 501\n"))
    assert s._mac_id_libre("UniqueID") == 452


def _hook():
    spec = importlib.util.spec_from_file_location("install_boot_hook_posix_nr", ROOT / "tools" / "install_boot_hook.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_l_unite_systemd_lance_le_superviseur_en_root_avec_l_utilisateur_installateur(monkeypatch):
    h = _hook()
    monkeypatch.setenv("NOKIDO_DENO", "/home/u/.deno/bin/deno")
    unite = h.unite_systemd({"NOKIDO_UTILISATEUR": "alice"})
    assert "User=" not in unite, "unite SYSTEME : root, l'equivalent de SYSTEM"
    assert "Environment=NOKIDO_UTILISATEUR=alice" in unite
    assert "ExecStart=/home/u/.deno/bin/deno run -A proxy_deno/core/supervisor.ts" in unite
    assert "WantedBy=multi-user.target" in unite


def test_le_superviseur_root_a_le_home_de_root_jamais_celui_de_l_installateur(monkeypatch):
    # Mesure 5 (run 38162661913) : Ollama, lance sans runAs par le superviseur root, mourait sur
    # « $HOME is not defined » -- ni systemd ni launchd ne posent HOME pour un service systeme.
    h = _hook()
    monkeypatch.setenv("NOKIDO_DENO", "/usr/local/bin/deno")
    unite = h.unite_systemd({"NOKIDO_UTILISATEUR": "alice", "HOME": "/home/alice"})
    assert "Environment=HOME=/root" in unite and "HOME=/home/alice" not in unite
    plist = h.daemon_launchd({"NOKIDO_UTILISATEUR": "alice", "HOME": "/Users/alice"})
    assert "<key>HOME</key><string>/var/root</string>" in plist and "/Users/alice" not in plist


def test_le_daemon_launchd_est_systeme_et_echappe_ses_valeurs(monkeypatch):
    h = _hook()
    monkeypatch.setenv("NOKIDO_DENO", "/Users/u/.deno/bin/deno")
    plist = h.daemon_launchd({"NOKIDO_UTILISATEUR": "a&b"})
    assert "<string>com.nokido.master</string>" in plist and "a&amp;b" in plist
    assert h.DAEMON_LAUNCHD.as_posix().startswith("/Library/LaunchDaemons"), "un LaunchAgent ne serait pas root"


def test_installer_amorcer_hors_root_refusent_et_le_disent(monkeypatch):
    h = _hook()
    monkeypatch.setattr(h.os, "geteuid", lambda: 1000, raising=False)
    for f in (lambda: h.installer_posix({}), h.amorcer_posix):
        rc, msg = f()
        assert rc == 1 and "REFUS" in msg


def test_install_sh_pose_comptes_coffre_et_superviseur_root_dans_l_ordre():
    t = (ROOT / "install.sh").read_text(encoding="utf-8")
    i_comptes = t.index("tools/forge_sandbox_setup.py")
    i_coffre = t.index("tools/install_boot_hook.py --amorcer")
    i_superviseur = t.index("tools/install_boot_hook.py --installer")
    assert i_comptes < i_coffre < i_superviseur
    assert '$SUDO rm -f "$A_NOTER"' in t, "codes d'appariement affiches une fois puis effaces"


def test_la_mesure_posix_emprunte_le_chemin_root_de_l_installeur():
    src = (ROOT / "tools" / "forge_install_acceptance.py").read_text(encoding="utf-8")
    branche = src[src.index("elif racine:"):src.index("    else:\n        p = demarrer(")]
    assert branche.index('"tools/forge_sandbox_setup.py"') < branche.index('"--amorcer"') < branche.index('"--installer"')
    assert '["sudo", "-n", "rm", "-f"' in branche, "la mesure efface les codes sans les lire"


def test_root_vaut_system_pour_le_jeton_court_hors_windows(monkeypatch):
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app import forge_agent_credential as cred
    monkeypatch.setattr(cred, "os", types.SimpleNamespace(name="posix", geteuid=lambda: 0))
    assert cred._sous_system() is True
    monkeypatch.setattr(cred, "os", types.SimpleNamespace(name="posix", geteuid=lambda: 1000))
    assert cred._sous_system() is False

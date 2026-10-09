# -*- coding: utf-8 -*-
"""Comptes d'execution des services runAs crees par l'INSTALLEUR (decision owner du 2026-10-08).

Ce qui ne doit pas revenir :
  * `forge_sandbox_setup` passait a icacls le TEXTE `__import__("os").path.expanduser("~")` (un decodage automatique
    ecrit dans une f-string) : traversee du profil et lecture de l'interpreteur jamais posees, echec tu par
    `check=False` ;
  * les ACL de l'interpreteur visaient `~\\miniforge3` en dur : sur une machine cliente, l'interpreteur est ailleurs ;
  * `install.ps1` creait des comptes dont il perdait le mot de passe (aucun lanceur runAs ne pouvait s'y connecter),
    sans LaForgeTrusted ni droit batch : il delegue desormais a l'implementation complete ;
  * `install.ps1` contenait des tirets cadratins dans des chaines : sous PowerShell 5.1 sans BOM, l'octet 0x94 devient
    un guillemet et le script ne s'analyse plus ;
  * les installeurs d'un clone n'installaient pas les dependances de l'organisme complet.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_sandbox_setup as S  # noqa: E402

pytestmark = pytest.mark.timeout(60)


def test_aucune_f_string_ne_porte_une_expression_python_en_texte():
    arbre = ast.parse((ROOT / "tools" / "forge_sandbox_setup.py").read_text(encoding="utf-8"))
    fautives = [n.lineno for n in ast.walk(arbre) if isinstance(n, ast.JoinedStr)
                and any(isinstance(v, ast.Constant) and "__import__(" in str(v.value) for v in n.values)]
    assert fautives == [], "f-string contenant du code Python en TEXTE, lignes %s" % fautives


def test_les_racines_d_interpreteur_suivent_la_machine(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "MINIFORGE_ROOT", str(tmp_path / "absent"))
    assert S.racines_python() == [sys.base_prefix], "sans miniforge : l'interpreteur de l'installation seul"
    monkeypatch.setattr(S, "MINIFORGE_ROOT", sys.base_prefix)
    assert S.racines_python() == [sys.base_prefix], "jamais deux fois la meme racine"


def test_la_traversee_couvre_les_parents_sans_la_racine_du_lecteur(tmp_path):
    cible = tmp_path / "profil" / "miniforge3"
    anc = S.ancetres_a_traverser(str(cible))
    assert str(tmp_path / "profil") in anc and str(tmp_path) in anc
    assert all(Path(a).parent != Path(a) for a in anc), "la racine du lecteur n'est jamais modifiee"


def test_les_acl_de_l_interpreteur_visent_des_chemins_reels(monkeypatch, tmp_path):
    racine = tmp_path / "py"
    (racine / "Lib").mkdir(parents=True)
    commandes, sous_arbres = [], []
    monkeypatch.setattr(S, "racines_python", lambda: [str(racine)])
    monkeypatch.setattr(S, "ps", lambda script, **k: commandes.append(script))
    monkeypatch.setattr(S, "_icacls_subtrees_parallel",
                        lambda paths, principal, perm, label="", **k: sous_arbres.extend(paths))
    S._acls_python("GroupeTest", "test")
    assert any(c.startswith('icacls "%s" /grant "GroupeTest:(OI)(CI)(RX)"' % racine) for c in commandes)
    assert any(c.startswith('icacls "%s" /grant "GroupeTest:(X)"' % tmp_path) for c in commandes)
    assert not any("__import__" in c for c in commandes)
    assert sous_arbres == [str(racine / "Lib")]


def test_install_ps1_delegue_les_comptes_et_reste_ascii():
    brut = (ROOT / "install.ps1").read_bytes()
    assert all(o < 128 for o in brut), "un .ps1 non ASCII ne s'analyse plus sous PowerShell 5.1 sans BOM"
    texte = brut.decode("ascii")
    assert 'tools\\forge_sandbox_setup.py' in texte
    assert "New-LocalUser" not in texte, "une seule implementation des comptes : forge_sandbox_setup"
    assert "requirements-organisme.txt" in texte
    assert 'tools\\install_boot_hook.py") --installer' in texte, "superviseur en tache SYSTEM apres les comptes"


def _hook():
    import importlib
    return importlib.import_module("install_boot_hook")


def test_l_enveloppe_systeme_lance_le_superviseur_du_depot_et_journalise(monkeypatch, tmp_path):
    # Decision owner du 2026-10-09 : superviseur en tache planifiee SYSTEM (seul SYSTEM peut CreateProcessAsUser).
    h = _hook()
    monkeypatch.setattr(h, "_dossier_tache", lambda: tmp_path / "ProgramData" / "Nokido")
    monkeypatch.setattr(h, "JOURNAL_TACHE", tmp_path / "logs" / "laforge-master.tache.log")
    appels = []
    monkeypatch.setattr(h.subprocess, "run", lambda args, **k: appels.append(args))
    out = h.gen_windows_tache({"NOM_TEST": "valeur"})
    texte = out.read_text(encoding="oem" if sys.platform == "win32" else "ascii")
    assert 'cd /d "%s"' % h.ROOT in texte and 'set "NOM_TEST=valeur"' in texte
    assert "run -A proxy_deno/core/supervisor.ts >>" in texte and "2>&1" in texte
    assert out.parent == tmp_path / "ProgramData" / "Nokido", "jamais dans le depot : SYSTEM execute ce fichier"
    assert any(a[:2] == ["icacls", str(out.parent)] and "/inheritance:r" in a for a in appels)


def test_la_tache_refuse_de_doubler_le_service_du_poste_de_reference(monkeypatch):
    h = _hook()

    class R:
        returncode = 0
    monkeypatch.setattr(h.subprocess, "run", lambda args, **k: R())
    rc, msg = h.installer_tache_windows({})
    assert rc == 1 and "REFUS" in msg


def test_la_mesure_windows_emprunte_le_chemin_de_l_installeur():
    src = (ROOT / "tools" / "forge_install_acceptance.py").read_text(encoding="utf-8")
    assert '"tools/forge_sandbox_setup.py"' in src and '"tools/install_boot_hook.py", "--installer"' in src
    assert '"tools/install_boot_hook.py", "--arreter"' in src


def test_install_sh_installe_l_organisme_avec_torch_cpu_sous_linux():
    texte = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert 'EXTRAS="${EXTRAS:-hub,rag,llm,docs,organisme}"' in texte
    assert "https://download.pytorch.org/whl/cpu" in texte

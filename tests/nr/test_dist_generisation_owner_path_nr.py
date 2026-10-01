"""NR — le dist genereise les chemins owner en variables d'env (installabilite).

Le depot de REFERENCE n'est jamais touche : le transform agit sur le SNAPSHOT
dist (clone separe). Ce NR verrouille : la map (chaque marqueur -> sa variable),
l'idempotence, l'epargne des binaires et de .git, la note PATHS.md, la defense
fail-closed sur residuel, la preservation de miniforge3, et le CABLAGE dans
sync_snapshot (apres blocked_paths).

Hermetique : arbre en tmp, aucun reseau, aucun git.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_dist_publish as D  # noqa: E402


def test_map_chaque_marqueur_vers_sa_variable():
    cas = {
        r"%NOKIDO_ROOT%\app\x.py": "%NOKIDO_ROOT%",
        "%NOKIDO_ROOT%/app/x.py": "%NOKIDO_ROOT%",
        r"%NOKIDO_WORKSPACE%\autre": "%NOKIDO_WORKSPACE%",
        r"%USERPROFILE%\.docker": "%USERPROFILE%",
        r"%NOKIDO_DATA%\embeddings.db": "%NOKIDO_DATA%",
        "owner user a dit": "user",
    }
    for src, attendu in cas.items():
        out, n = D.generiser_texte(src)
        assert n >= 1, src
        assert attendu in out, (src, out)
        assert not D._GEN_RESIDUEL.search(out), (src, out)


def test_ip_lan_privee_vers_localhost():
    # les trois plages RFC1918 -> localhost, port et schema preserves
    for src in (
        "http://localhost:8766/admin/providers",
        "localhost",
        "localhost",
        "localhost",
    ):
        out, n = D.generiser_texte(src)
        assert n >= 1, src
        assert "localhost" in out, (src, out)
        assert not D._GEN_RESIDUEL.search(out), (src, out)
    # le port et le chemin survivent a la substitution
    out, _ = D.generiser_texte("http://localhost:8766/admin/providers")
    assert "localhost:8766/admin/providers" in out


def test_ip_publique_et_localhost_intouches():
    # IP publiques et hors-plage privee : JAMAIS touchees
    for src in ("8.8.8.8", "172.32.0.1", "172.15.0.1", "http://localhost:8766"):
        out, n = D.generiser_texte(src)
        assert n == 0, (src, out)
        assert src == out


def test_double_backslash_capte():
    src = r'p = "%USERPROFILE%\\.lmstudio"'
    out, n = D.generiser_texte(src)
    assert n == 1
    assert "%USERPROFILE%" in out
    assert "user" not in out


def test_idempotent():
    src = r"%NOKIDO_ROOT% et %NOKIDO_DATA%\db et user nu"
    o1, n1 = D.generiser_texte(src)
    o2, n2 = D.generiser_texte(o1)
    assert n1 >= 3
    assert n2 == 0
    assert o1 == o2


def test_miniforge3_preserve():
    src = "env = Path.home() / 'miniforge3' / 'python.exe'"
    out, n = D.generiser_texte(src)
    assert n == 0
    assert "miniforge3" in out


def test_walker_generise_epargne_binaire_et_git(tmp_path):
    dist = tmp_path / "dist"
    (dist / "app").mkdir(parents=True)
    (dist / ".git").mkdir()
    (dist / "app" / "m.py").write_text(
        r'ROOT = r"%NOKIDO_ROOT%"', encoding="utf-8")
    (dist / "run.bat").write_text(r"cd %USERPROFILE%\.docker", encoding="utf-8")
    (dist / ".git" / "config").write_text(r"%USERPROFILE%\keep", encoding="utf-8")
    gif = dist / "demo.gif"
    octets = b"GIF89a user binaire \x00\x01"
    gif.write_bytes(octets)

    D._generiser_chemins_owner(dist)

    assert "%NOKIDO_ROOT%" in (dist / "app" / "m.py").read_text(encoding="utf-8")
    assert "%USERPROFILE%" in (dist / "run.bat").read_text(encoding="utf-8")
    assert "user" not in (dist / "app" / "m.py").read_text(encoding="utf-8")
    # .git INTACT (jamais transforme)
    assert "user" in (dist / ".git" / "config").read_text(encoding="utf-8")
    # binaire INTACT (octets identiques)
    assert gif.read_bytes() == octets
    # note d'install ecrite
    assert (dist / "PATHS.md").exists()


# Nom de machine SYNTHETIQUE : inscrire le vrai le ferait entrer dans la source
# publiee. Mesure du 2026-09-30 : v0.20.2 publiee portait le hostname en
# MINUSCULES dans 9 fichiers (`whoami` rend `desktop-xxxxxxx\compte`), et le
# motif majuscule seul le laissait passer.
def test_nom_de_machine_en_minuscules_generise():
    for src in (r"-> desktop-xxxx\\laforgesbxoffline", "desktop-xxxx\\laforgetrusted",
                "desktop-xxxx"):
        out, n = D.generiser_texte(src)
        assert n >= 1 and "7k2mq9z" not in out.lower(), (src, out)


def test_nom_de_machine_apres_un_echappement_litteral_generise():
    """Mesure du 2026-09-30 (tarball 0.20.4) : un JSON serialise un message git
    avec des echappements LITTERAUX -- `\\n\\tDESKTOP-.../user`. Le `t` de `\\t`
    colle au nom : `\\bDESKTOP-` n'y voyait aucune limite de mot, generisation ET
    defense residuelle le rataient."""
    for src in ("owned by:\\n\\tDESKTOP-XXXX/user", "x\\ndesktop-xxxx\\laforgesbxoffline",
                "\\rDESKTOP-XXXX",
                # `_` est un caractere de MOT : `\b` n'y voit pas de limite non plus.
                "user_DESKTOP-XXXX", "hote_desktop-xxxx"):
        out, n = D.generiser_texte(src)
        assert n >= 1 and "7k2mq9z" not in out.lower(), (src, out)


def test_sid_machine_generise_sid_bien_connu_intouche():
    """Le SID d'une machine (S-1-5-21-<3 blocs>-<rid>) l'identifie autant que son
    nom. Les SID bien connus (S-1-5-18 SYSTEM...) ne designent aucune machine."""
    out, n = D.generiser_texte("(S-1-5-21-XXXX)")
    assert n >= 1 and "1111111111" not in out, out
    for src in ("S-1-5-18", "S-1-5-32-544"):
        assert D.generiser_texte(src) == (src, 0), src


@pytest.mark.parametrize("marqueur", ["\\tDESKTOP-XXXX", "S-1-5-21-XXXX"])
def test_la_defense_residuelle_voit_l_echappe_et_le_sid(tmp_path, monkeypatch, marqueur):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "x.json").write_text('{"err": "%s"}' % marqueur.replace("\\", "\\\\"), encoding="utf-8")
    monkeypatch.setattr(D, "_GEN_SUBS", [])   # rien n'est substitue -> residuel
    with pytest.raises(RuntimeError):
        D._generiser_chemins_owner(dist)


def test_desktop_qui_n_est_pas_un_nom_de_machine_est_intouche():
    for src in ("data-Claude-Desktop-03052026", "claude-desktop-stdio",
                "anthropics/claude-desktop-buddy", "Claude-Desktop", "DESKTOP-XXXX"):
        out, n = D.generiser_texte(src)
        assert n == 0 and out == src, (src, out)


@pytest.mark.parametrize("marqueur", ["desktop-xxxx", "DESKTOP-XXXX"])
def test_la_defense_residuelle_voit_le_nom_de_machine(tmp_path, monkeypatch, marqueur):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "x.py").write_text("compte = '%s\\\\laforgesbxoffline'" % marqueur, encoding="utf-8")
    monkeypatch.setattr(D, "_GEN_SUBS", [])   # rien n'est substitue -> residuel
    with pytest.raises(RuntimeError):
        D._generiser_chemins_owner(dist)


def test_la_defense_residuelle_lit_aussi_les_CHEMINS(tmp_path):
    """Mesure du 2026-09-30 : 3 sorties Cython suivies sous
    `app/build_cython/Users/<owner>/Script python IA/...` etaient publiees dans
    v0.20.2 et v0.20.3. La generisation ne lisait que les CONTENUS ; un nom de
    fichier ne se generise pas, il se REFUSE."""
    dist = tmp_path / "dist"
    cible = dist / "app" / "build_cython" / "desktop-xxxx" / "x.c"
    cible.parent.mkdir(parents=True)
    cible.write_text("int x = 1;\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="build_cython"):
        D._generiser_chemins_owner(dist)


def test_defense_fail_closed_si_residuel(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "x.py").write_text(r"p = r'%USERPROFILE%\z'", encoding="utf-8")
    monkeypatch.setattr(D, "_GEN_SUBS", [])   # rien n'est substitue -> residuel
    with pytest.raises(RuntimeError):
        D._generiser_chemins_owner(dist)


def test_cable_dans_sync_snapshot_apres_blocage():
    src = inspect.getsource(D.sync_snapshot)
    assert "_generiser_chemins_owner" in src
    assert src.index("_appliquer_politique_publique") < src.index("_generiser_chemins_owner")

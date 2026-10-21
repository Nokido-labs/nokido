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


# Le NOM DE TAILNET (Tailscale) et le DDNS. Mesure du 2026-10-17 : le dist v0.20.12
# publie portait le tailnet de l'owner dans proxy_deno/core/services.toml -- aucun
# motif ne le couvrait (P1 « le dist ne doit pas etre fige sur mes IP »). Motifs
# GENERIQUES, valeurs FICTIVES ici : la source de ce test est publiee elle aussi.
TAILNET_FICTIF = "tailXXXX.ts.net"
DDNS_FICTIF = "XXXX.duckdns.org"


def test_tailnet_generise():
    for src in ("url = 'https://desk.%s:8443'" % TAILNET_FICTIF, TAILNET_FICTIF.upper()):
        out, n = D.generiser_texte(src)
        assert n >= 1 and "9c3e1a" not in out.lower(), (src, out)
        assert "tailxxxx.ts.net" in out.lower(), out


def test_ddns_duckdns_generise():
    out, n = D.generiser_texte("host = '%s'" % DDNS_FICTIF)
    assert n >= 1 and "monserveur" not in out, out
    assert "XXXX.duckdns.org" in out, out


def test_tailnet_et_ddns_idempotents_et_domaines_nus_intouches():
    for src in ("https://desk.%s" % TAILNET_FICTIF, DDNS_FICTIF):
        une, _ = D.generiser_texte(src)
        deux, n = D.generiser_texte(une)
        assert deux == une and n == 0, (src, une, deux)
    for src in ("doc : https://tailscale.com/kb/1081", "login.tailscale.com", "voir duckdns.org",
                "https://www.duckdns.org/install.jsp"):
        out, n = D.generiser_texte(src)
        assert out == src and n == 0, (src, out)


def test_la_defense_residuelle_voit_tailnet_et_ddns(tmp_path, monkeypatch):
    for i, marq in enumerate((TAILNET_FICTIF, DDNS_FICTIF)):
        dist = tmp_path / ("dist%d" % i)
        dist.mkdir()
        (dist / "services.toml").write_text("host = '%s'" % marq, encoding="utf-8")
        with monkeypatch.context() as m:
            m.setattr(D, "_GEN_SUBS", [])   # rien n'est substitue -> residuel
            with pytest.raises(RuntimeError):
                D._generiser_chemins_owner(dist)


def test_un_fichier_non_utf8_ne_passe_pas_la_defense_en_silence(tmp_path):
    """Mesure du 2026-10-17 (gate recidive) : un fichier NON UTF-8 etait saute en silence par la generisation
    ET par la defense residuelle (`except Exception: continue`) -- un latin-1 portant un chemin owner partait
    dans le dist public. Les marqueurs sont ASCII : la defense les voit meme dans un texte mal encode."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "vieux.cfg").write_bytes(b"racine = %NOKIDO_WORKSPACE%\nnote = caf\xe9\n")
    with pytest.raises(RuntimeError):
        D._generiser_chemins_owner(dist)


def test_les_remplacants_tailnet_et_ddns_passent_la_defense(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "services.toml").write_text(
        "a = 'https://desk.%s'\nb = '%s'\n" % (TAILNET_FICTIF, DDNS_FICTIF), encoding="utf-8")
    D._generiser_chemins_owner(dist)        # ne doit PAS lever : les remplacants sont propres
    txt = (dist / "services.toml").read_text(encoding="utf-8")
    assert "9c3e1a" not in txt and "monserveur" not in txt, txt

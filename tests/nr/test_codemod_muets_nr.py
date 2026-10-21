# -*- coding: utf-8 -*-
"""NR (essaim_local_mesure, levier a, 19/10) : codemod DETERMINISTE des chemins d'erreur muets.

Mesure du 17/10 : 1 944 sites muets / 685 fichiers ; l'essaim local echoue sur le FORMAT d'edition (0 % resolu).
La partie MECANIQUE se fait sans modele : meme regle que forge_git_gate._recidive_warn (corps = pass/continue nu,
`# muet-ok` sur la ligne du handler OU du corps absout), reecriture ligne a ligne -- le `pass` devient une
journalisation debug avec exc_info, une journalisation est inseree avant le `continue`. Un `except X: pass` sur UNE
ligne n'est pas mecanique : il est DECLARE, pas touche. L'outil ne fait que PROPOSER (patch) ; il n'ecrit jamais.
"""
import ast
import importlib.util
import sys

from nokido_agent.tools import forge_codemod_muets as C

SRC = (
    "def f(xs):\n"
    "    out = []\n"
    "    for x in xs:\n"
    "        try:\n"
    "            out.append(1 / x)\n"
    "        except ZeroDivisionError:\n"
    "            continue\n"
    "    try:\n"
    "        int('a')\n"
    "    except ValueError:\n"
    "        pass\n"
    "    try:\n"
    "        int('b')\n"
    "    except ValueError:  # muet-ok : voulu\n"
    "        pass\n"
    "    try:\n"
    "        int('c')\n"
    "    except ValueError:\n"
    "        pass  # muet-ok\n"
    "    try:\n"
    "        int('d')\n"
    "    except ValueError: pass\n"
    "    return out\n"
)


def test_detection_suit_la_regle_du_gate():
    assert [s["ligne"] for s in C.sites_muets(SRC)] == [6, 10, 22]


def test_reecriture_mecanique_et_ligne_unique_declaree():
    r = C.transformer(SRC, "mod_x.py")
    ast.parse(r["source"])
    # seul le non mecanique reste, decale d'une ligne par la journalisation inseree avant le `continue`
    assert [s["ligne"] for s in C.sites_muets(r["source"])] == [23]
    assert r["reecrits"] == 2 and r["non_mecaniques"] == [22]
    assert "muet-ok : voulu" in r["source"] and "pass  # muet-ok" in r["source"]


def test_le_comportement_est_preserve(tmp_path):
    p = tmp_path / "mod_c.py"
    p.write_text(C.transformer(SRC, "mod_c.py")["source"], encoding="utf-8")
    spec = importlib.util.spec_from_file_location("mod_c", p)
    m = importlib.util.module_from_spec(spec)
    sys.modules["mod_c"] = m
    spec.loader.exec_module(m)
    assert m.f([1, 0, 2]) == [1.0, 0.5]  # l'exception reste avalee, la boucle continue


def test_le_patch_s_applique_avec_git(tmp_path):
    """19/10 : le patch du lot app/ etait REFUSE par `git apply --check` -- write_text en mode texte transformait chaque
    \\n du patch en \\r\\n sous Windows. Le patch s'ecrit en LF ; un fichier source reellement CRLF garde ses CRLF."""
    import subprocess

    def g(*a):
        return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(tmp_path), *a],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
    g("init", "-q")
    (tmp_path / "lf.py").write_bytes(SRC.encode("utf-8"))
    (tmp_path / "crlf.py").write_bytes(SRC.replace("\n", "\r\n").encode("utf-8"))
    g("-c", "core.autocrlf=false", "add", "lf.py", "crlf.py")
    rapport = C.proposer([tmp_path / "lf.py", tmp_path / "crlf.py"], racine=tmp_path, sortie=tmp_path / "out")
    patch = tmp_path / "out" / "codemod_muets.patch"
    assert rapport["fichiers"] == 2
    r = g("-c", "core.autocrlf=false", "apply", "--check", str(patch))
    assert r.returncode == 0, r.stderr


def test_dry_run_n_ecrit_pas_la_source(tmp_path):
    cible = tmp_path / "pkg" / "a.py"
    cible.parent.mkdir()
    cible.write_text(SRC, encoding="utf-8")
    rapport = C.proposer([cible], racine=tmp_path, sortie=tmp_path / "out")
    assert cible.read_text(encoding="utf-8") == SRC
    assert rapport["fichiers"] == 1 and rapport["reecrits"] == 2 and rapport["non_mecaniques"] == 1
    assert (tmp_path / "out" / "codemod_muets.patch").read_text(encoding="utf-8").count("+++ ") == 1

# -*- coding: utf-8 -*-
"""NR -- git et gh par le hub : la forme qui MARCHE est rappelee AVANT l'appel (owner 2026-11-08).

Owner : « tu fais constamment cette erreur ». Mesure du 08/11 : `run action=shell` avec
`git -C <depot> ...` -> « dubious ownership » (LaForgeSbxOffline n'est pas proprietaire du
depot) ; la regle existante ne visait que `cd <repo> && git`. Puis repli en Bash compose
(`date; cd && git | grep`) -> bash_guard BLOQUE (chaque segment doit etre passthrough).
Mesure du meme jour : `git -c safe.directory=* -C <depot> log` PASSE par le hub ; `gh` y
rend « gh auth login » (aucun jeton dans le bac).

Contrat : sous `run action=shell` seulement (le passthrough Bash git/gh est legitime),
git sans `safe.directory` et gh tirent un rappel ; la forme juste ne tire rien.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _gate():
    spec = importlib.util.spec_from_file_location("hook_capability_gate", ROOT / "tools" / "hook_capability_gate.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _touches(entree):
    g = _gate()
    txt = g._texte_commande(entree)
    return [msg for rx, msg in g._regles_du_shell(entree) if rx.search(txt)]


DEPOT = '"%NOKIDO_ROOT%"'


def test_git_sans_safe_directory_par_le_hub_rappelle_la_forme():
    t = _touches({"action": "shell", "commands": [f"git -C {DEPOT} for-each-ref --count=8"]})
    assert any("safe.directory" in m for m in t), t


def test_git_avec_safe_directory_ne_tire_pas():
    t = _touches({"action": "shell", "code": f"git -c safe.directory=* -C {DEPOT} log --oneline -2"})
    assert not any("safe.directory" in m for m in t), t


def test_gh_par_le_hub_rappelle_l_absence_de_jeton():
    t = _touches({"action": "shell", "code": "gh run list --repo Nokido-labs/nokido --limit 1"})
    assert any("gh auth" in m for m in t), t


def test_passthrough_bash_git_et_gh_ne_tirent_pas():
    for cmd in (f"git -C {DEPOT} log --oneline -3", "gh run list --limit 1"):
        t = _touches({"command": cmd})
        assert not any("safe.directory" in m or "gh auth" in m for m in t), (cmd, t)


def test_chemin_git_n_est_pas_une_commande_git():
    t = _touches({"action": "shell", "code": 'type "C:/x/.git/HEAD" & dir .gitignore'})
    assert not any("safe.directory" in m for m in t), t

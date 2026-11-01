"""NR -- le guet des consoles nomme le LANCEUR d'un pop, et son silence se distingue de sa mort (owner 31/10).

Deux guets ponctuels n'ont rien vu ; un pop intermittent ne se prouve que par un journal. Trois proprietes :
  * la fenetre d'un pop sous Windows Terminal ne dit pas qui l'a lance -> on journalise les NAISSANCES console ;
  * une identite n'est jamais devinee : sans preuve, NON PROUVEE ; un maillon disparu est DIT ;
  * un temoin periodique distingue « rien vu » de « guet mort » et « bureau illisible » (visibles_max = 0).
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_guet_consoles as G  # noqa: E402

T0 = 1_000_000.0
PROCS = {
    10: {"nom": "explorer.exe", "ppid": None, "cree": T0 - 9999, "cmd": "explorer"},
    20: {"nom": "WindowsTerminal.exe", "ppid": 10, "cree": T0 - 500, "cmd": "wt"},
    30: {"nom": "deno.exe", "ppid": None, "cree": T0 - 3000, "cmd": "deno supervisor.ts"},
    40: {"nom": "cmd.exe", "ppid": 30, "cree": T0 - 0.5, "cmd": "cmd /c tasklist"},
    50: {"nom": "conhost.exe", "ppid": 40, "cree": T0 - 0.4, "cmd": "conhost 0x4"},
    60: {"nom": "cmd.exe", "ppid": 99, "cree": T0 - 60, "cmd": "vieux"},
}


def test_seules_les_consoles_nees_recemment_sont_des_naissances():
    assert G.naissances(PROCS, T0) == [40, 50]


def test_la_chaine_dit_un_maillon_disparu():
    assert G.chaine(60, PROCS) == ["cmd.exe[60]", "ILLISIBLE[99] (disparu)"]
    assert G.chaine(50, PROCS) == ["conhost.exe[50]", "cmd.exe[40]", "deno.exe[30]"]


def test_un_pop_sous_windows_terminal_nomme_son_lanceur_et_jamais_ne_le_devine():
    ident = {40: {"identite": "descendant de NokidoSupervisor"}}
    e = G.evenement((7, 20, "CASCADIA_HOSTING_WINDOW_CLASS", "cmd"), PROCS, T0, identifier=ident.get)
    assert e["fenetre"] == ["WindowsTerminal.exe[20]", "explorer.exe[10]"]
    par_pid = {n["pid"]: n for n in e["naissances"]}
    assert par_pid[40]["identite"] == "descendant de NokidoSupervisor"
    assert par_pid[50]["identite"] == "NON PROUVEE"
    assert "tasklist" in par_pid[40]["cmd"]


def test_une_identification_en_panne_se_dit():
    def casse(_pid):
        raise OSError("superviseur muet")
    e = G.evenement((7, 50, "ConsoleWindowClass", ""), PROCS, T0, identifier=casse)
    assert {n["identite"] for n in e["naissances"]} == {"ILLISIBLE (OSError)"}


def test_la_boucle_ignore_l_existant_journalise_le_pop_et_ecrit_son_temoin(monkeypatch):
    monkeypatch.setattr(G, "TEMOIN_S", 0.15)
    tours = iter([(5, [(1, 20, "CASCADIA_HOSTING_WINDOW_CLASS", "PS7")]),            # deja ouverte au demarrage
                  (6, [(1, 20, "CASCADIA_HOSTING_WINDOW_CLASS", "PS7"), (2, 50, "ConsoleWindowClass", "")]),
                  (6, [(1, 20, "CASCADIA_HOSTING_WINDOW_CLASS", "PS7"), (2, 50, "ConsoleWindowClass", "")])])
    t = [T0]
    ecrit = []
    bilan = G.guetter(0.25, intervalle_s=0.1, enumerer=lambda: next(tours), instantane=lambda: PROCS,
                      identifieur=lambda procs: (lambda pid: None), ecrire=ecrit.append,
                      horloge=lambda: t[0], dormir=lambda s: t.__setitem__(0, t[0] + s))
    pops = [e for e in ecrit if e["type"] == "console_visible"]
    assert len(pops) == 1 and pops[0]["fenetre"][0] == "conhost.exe[50]"
    temoins = [e for e in ecrit if e["type"] == "temoin"]
    assert temoins and temoins[0]["lisible"] is True and temoins[0]["visibles_max"] == 6
    assert bilan["evenements"] == 1


def test_un_bureau_invisible_est_dit_illisible(monkeypatch):
    monkeypatch.setattr(G, "TEMOIN_S", 0.0)
    t = [T0]
    ecrit = []
    G.guetter(0.15, intervalle_s=0.1, enumerer=lambda: (0, []), instantane=lambda: {},
              identifieur=lambda p: (lambda pid: None), ecrire=ecrit.append,
              horloge=lambda: t[0], dormir=lambda s: t.__setitem__(0, t[0] + s))
    assert ecrit and all(e["lisible"] is False for e in ecrit if e["type"] == "temoin")


def test_le_point_d_entree_traverse_ses_imports(monkeypatch):
    vu = {}
    monkeypatch.setattr(G, "guetter", lambda d, i: vu.update(d=d, i=i) or {"evenements": 0})
    assert G.main(["--duree", "1", "--intervalle", "0.2"]) == 0 and vu == {"d": 1.0, "i": 0.2}

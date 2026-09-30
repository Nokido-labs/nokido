# -*- coding: utf-8 -*-
"""Non-regression — la TUI affiche du REEL, et un capteur muet ne passe pas pour calme.

Deux defauts mesures le 2026-08-29, chacun verrouille ici :

1. `tools/archive_tui/swarm_dashboard_v2.py` affichait des donnees INVENTEES —
   arbres d'agents en dur, heartbeat fige a « 60 BPM », `simulate_event_bus` qui
   tirait au hasard dans une liste d'evenements. Une TUI de demonstration viole la
   regle « live-only ». Le test `test_aucune_donnee_simulee` empeche ce retour.

2. `forge_tui.get_heartbeats` lisait un champ `timestamp` qui n'existe plus (le
   format ecrit `ts`, sous TROIS formes). L'age valait donc l'epoch entier et
   QUARANTE daemons sur quarante-cinq etaient marques en retard alors qu'ils
   battaient. Un capteur qui lit le mauvais champ ne rend pas « rien » : il rend
   une alarme.

Hermetique : aucun collecteur reel n'est appele (ni reseau, ni SQLite, ni git) —
c'est precisement pourquoi SOURCES porte le NOM du collecteur et non la fonction.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

TUI = pytest.importorskip("forge_tui_textual")
FT = pytest.importorskip("forge_tui")


# ------------------------------------------------------- l'age d'un battement

def test_ts_epoch_flottant(monkeypatch):
    age, source = FT._age_heartbeat({"ts": time.time() - 42}, Path("x"))
    assert source == "ts" and 40 <= age <= 45


def test_ts_iso_naif_est_lu_en_heure_LOCALE():
    """Le supposer UTC ajouterait le decalage a l'age : un daemon sain paraitrait
    en retard de deux heures (mesure : un ts naif a 17:09 pour 17:25 local, quand
    la forme `+00:00` du meme instant dit 15:25)."""
    quand = (datetime.now() - timedelta(seconds=30)).isoformat()
    age, source = FT._age_heartbeat({"ts": quand}, Path("x"))
    assert source == "ts" and 25 <= age <= 35


def test_ts_iso_avec_decalage():
    quand = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    age, source = FT._age_heartbeat({"ts": quand}, Path("x"))
    assert source == "ts" and 25 <= age <= 35


def test_ancien_champ_timestamp_encore_accepte():
    age, source = FT._age_heartbeat({"timestamp": time.time() - 10}, Path("x"))
    assert source == "ts" and 8 <= age <= 12


def test_sans_ts_on_se_rabat_sur_le_mtime_ET_ON_LE_DIT(tmp_path):
    """Deduire l'age du mtime est acceptable ; le faire passer pour un battement
    declare ne l'est pas."""
    f = tmp_path / "x.heartbeat"
    f.write_text("{}", encoding="utf-8")
    age, source = FT._age_heartbeat({}, f)
    assert source == "mtime" and age is not None and age < 60


def test_ts_illisible_ne_fabrique_pas_un_age(tmp_path):
    f = tmp_path / "y.heartbeat"
    f.write_text("{}", encoding="utf-8")
    age, source = FT._age_heartbeat({"ts": "pas une date"}, f)
    assert source == "mtime", "une date illisible ne doit pas valoir zero"
    assert age is not None


# ------------------------------------------- le seuil suit l'intervalle declare

def _heartbeats(tmp_path, monkeypatch, contenus: dict) -> list:
    for nom, data in contenus.items():
        (tmp_path / (nom + ".heartbeat")).write_text(
            data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(FT, "HEARTBEAT_DIR", tmp_path)
    return FT.get_heartbeats()


def test_un_daemon_lent_n_est_pas_en_retard(tmp_path, monkeypatch):
    """Un daemon qui bat toutes les 900 s n'est pas en retard a 400 s. Le seuil fixe
    de 300 s marquait 40 daemons sur 45."""
    lignes = _heartbeats(tmp_path, monkeypatch,
                         {"lent": {"ts": time.time() - 400, "interval_s": 900}})
    assert lignes and not lignes[0].startswith("!"), lignes


def test_un_daemon_vraiment_en_retard_est_signale(tmp_path, monkeypatch):
    lignes = _heartbeats(tmp_path, monkeypatch,
                         {"mort": {"ts": time.time() - 9000, "interval_s": 60}})
    assert lignes and lignes[0].startswith("!"), lignes


def test_un_fichier_hors_format_n_emporte_PAS_les_autres(tmp_path, monkeypatch):
    """Mesure : un .heartbeat contenant un flottant nu faisait tomber le panneau
    ENTIER en AttributeError — quarante-quatre daemons lisibles disparaissaient."""
    lignes = _heartbeats(tmp_path, monkeypatch, {
        "casse": "1788017076.27",
        "sain": {"ts": time.time() - 5, "interval_s": 30},
    })
    assert len(lignes) == 2
    assert any("format" in l for l in lignes), lignes
    assert any("sain" in l and not l.startswith("!") for l in lignes), lignes


def test_json_invalide_est_dit_illisible(tmp_path, monkeypatch):
    lignes = _heartbeats(tmp_path, monkeypatch, {"pourri": "{pas du json"})
    assert lignes and "illisible" in lignes[0]


def test_aucun_fichier_se_dit(tmp_path, monkeypatch):
    lignes = _heartbeats(tmp_path, monkeypatch, {})
    assert lignes == ["(aucun fichier heartbeat)"]


# --------------------------------------------------- la TUI, sans rien inventer

def test_collecter_rend_les_quatre_sources(monkeypatch):
    for _ident, _titre, nom in TUI.SOURCES:
        monkeypatch.setattr(FT, nom, lambda: ["ligne"])
    out = TUI.collecter()
    assert set(out) == {"services", "heartbeats", "rag", "git"}
    assert all(err is None and corps == ["ligne"] for _t, corps, err in out.values())


def test_un_collecteur_qui_leve_est_ILLISIBLE_pas_vide(monkeypatch):
    """LE test. Un panneau vide et un panneau muet ne doivent pas se ressembler :
    un ecran calme se lit comme un systeme calme."""
    def _casse():
        raise RuntimeError("base fermee")
    monkeypatch.setattr(FT, "get_rag_status", _casse)
    for nom in ("check_services", "get_heartbeats", "get_git_info"):
        monkeypatch.setattr(FT, nom, lambda: [])
    out = TUI.collecter()
    assert out["rag"][2] and "RuntimeError" in out["rag"][2]
    assert out["services"][2] is None and out["services"][1] == []


def test_instantane_distingue_vide_et_illisible(monkeypatch):
    def _casse():
        raise OSError("disque")
    monkeypatch.setattr(FT, "get_git_info", _casse)
    for nom in ("check_services", "get_heartbeats", "get_rag_status"):
        monkeypatch.setattr(FT, nom, lambda: [])
    texte = TUI.instantane()
    assert "ILLISIBLE" in texte and "OSError" in texte
    assert "lu, et vide" in texte


# Borne DURE de l'attente de montage, en tours de boucle. Elle existe pour que
# l'echec reste un echec BORNE et nomme, jamais une suspension : le garde sort
# en disant ce qui manque. Genereuse a dessein — le test sort des qu'il a sa
# condition, donc l'augmenter ne coute rien a un montage sain.
_TOURS_MAX_MONTAGE = 40


def test_la_tui_monte_et_remplit_ses_panneaux(monkeypatch):
    """Montage REEL de l'App en headless : des widgets que personne ne monte ne se
    voient jamais echouer (c'est ainsi que `HeartbeatTail.on_mount` appelait un
    `scan_heartbeats` inexistant sans que rien ne le signale)."""
    pytest.importorskip("textual")
    for _ident, _titre, nom in TUI.SOURCES:
        monkeypatch.setattr(FT, nom, lambda: ["valeur mesuree"])

    attendus = [ident for ident, _t, _n in TUI.SOURCES]

    async def scenario():
        app = TUI._construire_app()()
        async with app.run_test() as pilot:
            # On attend la CONDITION, jamais un NOMBRE DE TOURS.
            #
            # Mesure du 2026-09-19, CI de reference sur f1a87b4ce : deux
            # `pause()` suffisaient a vide et PAS sous charge. Le 4e panneau
            # rendait '' et faisait rougir une suite de 10 988 tests, alors que
            # le meme test passait 16/16 en isolation sur le MEME arbre. Compter
            # des tours de boucle est un PROXY de la disponibilite, pas la
            # disponibilite -- et un proxy qui depend de la charge transforme un
            # garde en tirage au sort.
            rendus = {}
            for _ in range(_TOURS_MAX_MONTAGE):
                await pilot.pause()
                rendus = {i: (app.query_one("#p_" + i).dernier_texte or "")
                          for i in attendus}
                if all("valeur mesuree" in v for v in rendus.values()):
                    break
            return rendus

    rendus = asyncio.run(scenario())
    # L'IDENTITE des panneaux compte : `len(...) == 4` laisserait passer quatre
    # panneaux dont un serait le mauvais.
    assert set(rendus) == set(attendus), (attendus, sorted(rendus))
    manquants = [i for i in attendus if "valeur mesuree" not in rendus[i]]
    assert not manquants, (
        "montage incomplet apres %d tours — attendus=%s | remplis=%s | "
        "manquants=%s | contenu des manquants=%s. Un garde qui expire DIT ce "
        "qui manque : sans ce detail, un echec devient un timeout opaque et la "
        "mesure est perdue."
        % (_TOURS_MAX_MONTAGE, attendus,
           [i for i in attendus if i not in manquants], manquants,
           {i: rendus[i] for i in manquants}))


def test_aucune_donnee_simulee():
    """La TUI archivee tirait ses evenements au hasard dans une liste ecrite a la
    main. Rien de tel ne doit revenir ici : ce que la TUI montre vient d'un
    collecteur, ou n'est pas montre.

    On inspecte l'AST et NON le texte brut : la docstring du module cite justement
    `simulate_event_bus` pour expliquer ce qu'on ne veut plus. Un garde qui compte
    les mots de sa propre explication crie a faux — et un garde qui crie a faux se
    fait desarmer."""
    import ast as _ast

    arbre = _ast.parse(Path(TUI.__file__).read_text(encoding="utf-8", errors="replace"))

    docstrings = set()
    for noeud in _ast.walk(arbre):
        if isinstance(noeud, (_ast.Module, _ast.ClassDef, _ast.FunctionDef,
                              _ast.AsyncFunctionDef)):
            d = _ast.get_docstring(noeud, clean=False)
            if d:
                docstrings.add(d)

    # DEUX ensembles, parce que les deux questions sont differentes.
    #
    # `racines` = premier segment : c'est ce qui repond a « une bibliotheque de
    # tirage au hasard est-elle importee ». `modules` = les modules REELLEMENT
    # atteints, segment terminal et noms importes compris.
    #
    # ⚠️ 2026-09-10 — cet oracle ne tenait que `racines`, donc apres la migration
    # il lisait `nokido_agent` la ou il cherchait `forge_tui`, et declarait les
    # collecteurs disparus alors que la TUI les importe toujours. Deux defauts,
    # pas un : le premier segment n'est plus le nom du module, ET la forme reelle
    # `from nokido_agent.tools import forge_tui` porte le module dans le NOM
    # importe, jamais dans `noeud.module`.
    racines: set[str] = set()
    modules: set[str] = set()
    for noeud in _ast.walk(arbre):
        if isinstance(noeud, _ast.Import):
            for a in noeud.names:
                racines.add(a.name.split(".")[0])
                modules.add(a.name.split(".")[-1])
        elif isinstance(noeud, _ast.ImportFrom) and noeud.module:
            racines.add(noeud.module.split(".")[0])
            modules.add(noeud.module.split(".")[-1])
            modules |= {a.name for a in noeud.names}
    assert "random" not in racines, "un tirage au hasard n'a rien a faire dans une TUI live"
    assert "forge_tui" in modules, (
        f"les collecteurs doivent rester ceux de forge_tui, modules = {sorted(modules)}")

    litteraux = [n.value for n in _ast.walk(arbre)
                 if isinstance(n, _ast.Constant) and isinstance(n.value, str)
                 and n.value not in docstrings]
    for texte in litteraux:
        for interdit in ("BPM", "simulate_event_bus"):
            assert interdit not in texte, "donnee simulee reintroduite : %r" % texte[:60]

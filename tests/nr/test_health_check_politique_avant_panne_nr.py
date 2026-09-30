# -*- coding: utf-8 -*-
"""NR — `health_check` ne doit plus confondre un CHOIX avec une PANNE.

MESURE QUI A DECIDE (2026-09-20). Le ledger d'evolution porte 633 experiences en
30 jours, dont 328 `organ_down`. Leurs cibles :

    brain_worker:5557   239   ← 3 services declares sur ce port, TOUS disabled
    graph:7474          182   ← NokidoGraph, disabled = true
    llamacpp:8080       163   ← le service declare sur 8080 est NokidoSearxng (!), disabled
    webhub:7400          17   ← vrai signal
    hub_mcp:8766         11   ← vrai signal

Soit 584 signalements sur 633 (92 %) qui envoient reparer un CHOIX. C'est
exactement `DISABLED_BY_POLICY != RESOURCE_UNAVAILABLE`, la troisieme ligne de la
constitution semantique — commise par le corps lui-meme. Et le bruit NOIE les 28
signalements qui correspondaient a de vraies pannes.

`pat_health_check` porte une table `services_ports` CODEE EN DUR : un port ferme y
devient `down`, sans jamais consulter `services.toml`. Second defaut revele par la
meme mesure : cette table INVENTE des noms — elle appelle `llamacpp` le port 8080,
ou c'est SearXNG qui est declare.

Ce que ce NR verrouille :
  1. un port dont tous les services declares sont `disabled` sort en
     DISABLED_BY_POLICY, jamais en `down`, et n'ouvre AUCUNE experience ;
  2. un port dont un service est actif reste un vrai `down` (contre-epreuve : un
     garde qui classe tout en « choix » ne garde plus rien) ;
  3. un port sans declaration sort en DECLARATION_INCONNUE — ni sain, ni en
     panne : on ne range jamais l'inconnu du cote qui arrange ;
  4. une politique ILLISIBLE ne se lit pas comme « tout est actif » ;
  5. le nom rapporte est celui DECLARE, pas celui de la table en dur.
"""

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TOML = """
[[service]]
name = "NokidoWebHub"
port = 7400

[[service]]
name = "NokidoGraph"
port = 7474
disabled = true

[[service]]
name = "NokidoBrainWorker"
port = 5557
disabled = true

[[service]]
name = "NokidoBrainWorkerRust"
port = 5557
disabled = true

[[service]]
name = "NokidoSearxng"
port = 8080
disabled = true

[[service]]
name = "NokidoMixte"
port = 9100
disabled = true

[[service]]
name = "NokidoMixteActif"
port = 9100
"""


def _mod():
    return importlib.import_module("forge_autonomous_loops")


def _politique(tmp_path):
    f = tmp_path / "services.toml"
    f.write_text(TOML, encoding="utf-8")
    return _mod()._politique_des_ports(f)


def test_un_port_tout_entier_desactive_n_est_pas_une_panne(tmp_path):
    """ROUGE ATTENDU : la politique n'est jamais consultee."""
    mod = _mod()
    pol = _politique(tmp_path)
    down, choix, inconnus = mod._classer_ports_fermes(
        ["graph:7474", "brain_worker:5557"], pol)
    assert down == [], (
        "des organes ETEINTS PAR CHOIX ont ete classes en panne : %r" % (down,))
    assert len(choix) == 2, "les deux doivent sortir en DISABLED_BY_POLICY : %r" % (choix,)
    assert inconnus == []


def test_un_port_actif_reste_une_vraie_panne(tmp_path):
    """Contre-epreuve : sans elle, un `return []` en dur passerait le test 1."""
    mod = _mod()
    down, choix, inconnus = mod._classer_ports_fermes(["webhub:7400"], _politique(tmp_path))
    assert [d for d in down if "7400" in str(d)], (
        "un service ACTIF dont le port est ferme est une vraie panne : %r" % (down,))
    assert choix == []


def test_un_port_partiellement_actif_reste_une_panne(tmp_path):
    """Deux services sur un port, un seul eteint : le port est encore attendu.

    Ranger ce cas du cote « choix » suffirait a taire une vraie panne — c'est la
    dissymetrie du cout des deux erreurs, et elle penche ici vers le signalement.
    """
    mod = _mod()
    down, choix, _ = mod._classer_ports_fermes(["mixte:9100"], _politique(tmp_path))
    assert [d for d in down if "9100" in str(d)], (
        "un port qui porte encore un service actif doit rester un down : %r" % (down,))


def test_un_port_sans_declaration_n_est_ni_sain_ni_en_panne(tmp_path):
    """Trois etats. L'inconnu ne se range pas du cote qui arrange."""
    mod = _mod()
    down, choix, inconnus = mod._classer_ports_fermes(["mystere:65000"], _politique(tmp_path))
    assert inconnus and "65000" in str(inconnus[0]), (
        "un port sans service declare doit sortir en DECLARATION_INCONNUE : %r"
        % ((down, choix, inconnus),))
    assert down == [] and choix == []


def test_une_politique_illisible_ne_vaut_pas_tout_actif(tmp_path):
    """Un fichier de politique absent ou casse ne doit pas fabriquer des pannes.

    `UNKNOWN != NO` : sans politique lisible, on ne peut affirmer NI que l'organe
    est attendu actif, NI qu'il est eteint par choix.
    """
    mod = _mod()
    pol = mod._politique_des_ports(tmp_path / "nexiste_pas.toml")
    assert pol.get("etat") != "ok", "une politique illisible doit se declarer telle"
    down, choix, inconnus = mod._classer_ports_fermes(["graph:7474"], pol)
    assert down == [], "sans politique lisible, on ne DECLARE pas une panne"
    assert inconnus, "et on ne se tait pas non plus : le cas doit etre nomme"


def test_le_nom_rapporte_est_celui_declare(tmp_path):
    """La table en dur appelle `llamacpp` le port 8080 — or c'est SearXNG.

    Un signalement qui nomme le mauvais organe envoie enqueter au mauvais endroit.
    """
    mod = _mod()
    _, choix, _ = mod._classer_ports_fermes(["llamacpp:8080"], _politique(tmp_path))
    assert choix, "8080 est declare disabled : il doit sortir en choix"
    assert any("NokidoSearxng" in str(c) for c in choix), (
        "le nom DECLARE doit apparaitre, pas seulement l'etiquette en dur : %r"
        % (choix,))


def test_aucune_experience_n_est_ouverte_pour_un_choix(tmp_path, monkeypatch):
    """Le chemin REEL : `pat_health_check` lui-meme, pas seulement le classeur.

    Defaut paye le 2026-09-06 : une fonction verte pendant que son point d'entree
    mourait. Ici l'enjeu est le meme — c'est `pat_health_check` qui ecrit au
    ledger, donc c'est lui qu'il faut traverser.
    """
    mod = _mod()
    f = tmp_path / "services.toml"
    f.write_text(TOML, encoding="utf-8")
    monkeypatch.setattr(mod, "SERVICES_TOML_POLITIQUE", f, raising=False)
    monkeypatch.setattr(mod, "_health_down_streak", {}, raising=False)
    monkeypatch.setattr(mod, "_HEALTH_DOWN_THRESHOLD", 1, raising=False)

    # tous les ports fermes : le socket refuse systematiquement
    import socket as _s

    class _Refus:
        def settimeout(self, *a): pass
        def connect(self, *a): raise OSError("ferme")
        def close(self): pass

    monkeypatch.setattr(_s, "socket", lambda *a, **k: _Refus())

    ecrites = []
    monkeypatch.setattr(mod, "record_evolution_experience",
                        lambda rec: ecrites.append(rec) or "exp_fixture")
    monkeypatch.setattr(mod, "_trace_writer_stale", lambda: {"stale": False})
    monkeypatch.setattr(mod, "_sante_endpoints", lambda: {})

    out = mod.pat_health_check()

    cibles = [t for rec in ecrites for t in (rec.get("targets") or [])]
    for eteint in ("5557", "7474", "8080"):
        assert not any(eteint in c for c in cibles), (
            "une experience a ete ouverte pour un organe eteint par CHOIX (%s) : %r"
            % (eteint, cibles))
    assert "disabled_by_policy" in out, (
        "le retour doit EXPOSER ce qui a ete ecarte, sinon la couverture est "
        "surestimee en silence : %r" % (sorted(out),))

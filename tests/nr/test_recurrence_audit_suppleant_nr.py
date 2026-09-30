# -*- coding: utf-8 -*-
"""NR — « je n'ai pas pu voir » doit dire OU quelqu'un a vu, sans jamais sur-promettre.

CE QUI A ETE PAYE (2026-09-18). `forge_recurrence_audit` est la seule metrique capable
de contredire l'agent sur son propre progres. Lance depuis le compte du hub, il rend
`ILLISIBLE : dossier absent/interdit: ~/.claude/projects` -- un refus CORRECT (le
compte n'a pas acces au profil owner) qu'il ne faut surtout pas contourner en forcant
des droits. Mais en l'etat, la seule mesure qui peut me contredire etait simplement
indisponible, et rien n'indiquait qu'un suppleant existait.

Le suppleant est l'artefact depose par `forge_directive_audit` au SessionStart, du cote
ou les transcripts sont lisibles.

LA PRECAUTION QUI FAIT TOUT L'INTERET DU REPLI, et que ce NR verrouille : l'artefact
porte le DENOMINATEUR (evenements par session), il ne porte NI les recadrages NI les
motifs. Servir un suppleant partiel comme s'il repondait a la question d'origine serait
PIRE que le refus -- c'est ce que ce depot appelle un faux calme. `taux_recadrage` doit
donc rester explicitement NON MESURE.

MORSURE (`test_la_branche_ok_est_reellement_traversee`) : le chemin reel du 2026-09-18
n'a atteint que la branche `SANS_VOLUMETRIE`, et c'est precisement pour cela qu'un
`NameError` sur `time` a pu dormir dans la branche `ok` -- le module ne l'importait pas.
Un NR qui ne traverse pas la branche ne prouve rien sur elle.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_recurrence_audit as FRA  # noqa: E402

ABSENT = Path("Z:/dossier_qui_n_existe_pas_pour_ce_nr")


def _artefact(tmp_path, charge) -> Path:
    f = tmp_path / "persona_directives.json"
    f.write_text(json.dumps(charge, ensure_ascii=False), encoding="utf-8")
    return f


def test_la_branche_ok_est_reellement_traversee(tmp_path, monkeypatch):
    """MORSURE — le suppleant complet doit rendre son volume ET son age.

    Cette branche calcule `age_s` avec `time.time()`. Le module ne l'importait pas :
    le defaut est reste invisible parce que le seul essai reel etait tombe dans
    `SANS_VOLUMETRIE`. Emprunter la branche EST le test.
    """
    monkeypatch.setattr(FRA, "ARTEFACT_VOLUMETRIE", _artefact(tmp_path, {
        "genere_ts": int(time.time()) - 3600,
        "volumetrie": [{"session": "aaaaaaaa", "date": "2026-09-18", "lignes": 1200,
                        "messages_owner": 14},
                       {"session": "bbbbbbbb", "date": "2026-09-17", "lignes": 300,
                        "messages_owner": 9}],
    }))
    r = FRA.scan_sessions(ABSENT)
    assert r["etat"] == "ILLISIBLE"
    s = r["suppleant"]
    assert s["etat"] == "ok", s
    assert s["n_sessions"] == 2
    assert 3500 <= s["age_s"] <= 3700, "l'age du suppleant n'est pas calcule : %s" % s
    assert s["volumetrie"][0]["lignes"] == 1200


def test_le_suppleant_ne_pretend_JAMAIS_donner_le_taux(tmp_path, monkeypatch):
    """Un suppleant partiel servi comme complet est pire que le refus."""
    monkeypatch.setattr(FRA, "ARTEFACT_VOLUMETRIE", _artefact(tmp_path, {
        "genere_ts": int(time.time()),
        "volumetrie": [{"session": "cccccccc", "lignes": 10, "messages_owner": 2}],
    }))
    r = FRA.scan_sessions(ABSENT)
    assert "NON MESURE" in r["taux_recadrage"]
    assert "recadrages" not in r and "taux_pct" not in r, (
        "le repli fabrique une grandeur que l'artefact ne porte pas")


def test_un_artefact_absent_est_DIT_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(FRA, "ARTEFACT_VOLUMETRIE", tmp_path / "rien.json")
    s = FRA.scan_sessions(ABSENT)["suppleant"]
    assert s["etat"] == "ABSENT" and s["attendu"], s


def test_un_artefact_de_version_anterieure_est_DISTINGUE_d_un_absent(tmp_path, monkeypatch):
    """Trois etats, jamais deux : absent / present sans volumetrie / complet.

    Cas REEL mesure le 2026-09-18 : l'artefact existait, depose par la version
    d'avant, donc sans le champ. Le confondre avec « absent » enverrait chercher un
    fichier qui est la.
    """
    monkeypatch.setattr(FRA, "ARTEFACT_VOLUMETRIE",
                        _artefact(tmp_path, {"genere_ts": 1, "directives": []}))
    s = FRA.scan_sessions(ABSENT)["suppleant"]
    assert s["etat"] == "SANS_VOLUMETRIE", s
    assert "prochain demarrage" in s["raison"]


def test_un_artefact_illisible_ne_passe_pas_pour_un_absent_silencieux(tmp_path, monkeypatch):
    f = tmp_path / "casse.json"
    f.write_text("{ ceci n est pas du json", encoding="utf-8")
    monkeypatch.setattr(FRA, "ARTEFACT_VOLUMETRIE", f)
    s = FRA.scan_sessions(ABSENT)["suppleant"]
    assert s["etat"] == "ABSENT" and s["raison"], "la cause de l'echec n'est pas nommee"

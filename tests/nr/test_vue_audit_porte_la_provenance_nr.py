# -*- coding: utf-8 -*-
"""NR — la vue d'audit doit AGREGER la provenance, pas seulement l'identite.

MESURE DU 2026-09-21 (P1-S), sur 314 206 observations reelles
    Le journal dit parfaitement QUI, et s'effondre sur CE QUI A ETE DECIDE :

        via / agent / ring / tool      0,0 %  absent
        decision                      93,7 %  absent   <- premiere perte
        scope / reason               100,0 %  absent

    `_resolve_ring` produit 93,7 % des observations et ne porte AUCUNE
    decision : il repond « qui es-tu », jamais « as-tu le droit ».

CE QUE CE FICHIER CORRIGE, ET SA BORNE
    `capture()` RECOIT `acteur` et `sujet` -- les deux champs de provenance de
    la chaine d'appel -- mais `_AXES` ne les contient pas. Ils ne sont donc
    agreges NULLE PART, et le maillon provenance est NON MESURABLE.

        UNE ABSENCE D'AXE N'EST PAS UNE ABSENCE DE DONNEE

    Ce NR ne touche AUCUNE decision d'autorisation. Il rend mesurable ce qui
    etait deja transmis. Mesurer avant de durcir, jamais l'inverse.

CE QU'IL INTERDIT EXPLICITEMENT
    Fabriquer une provenance absente. Un appel sans `acteur` doit compter
    `(absent)` et jamais une valeur reconstruite :

        ABSENCE_DE_DONNEE != DONNEE_RECONSTRUITE
        une absence se voit, une invention se croit
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))
if str(_RACINE / "app") not in sys.path:
    sys.path.insert(0, str(_RACINE / "app"))

_MODULE = "forge_videur_audit"


@pytest.fixture()
def vue_isolee(tmp_path, monkeypatch):
    """Une vue NEUVE, dans un fichier a part.

    Le module tient un etat global et persiste dans `sandbox/`. Sans
    redirection, un test ecrirait dans la vue REELLE du corps -- un
    instrument ne pollue jamais la mesure qu'il observe.
    """
    m = importlib.import_module(_MODULE)
    monkeypatch.setattr(m, "_VUE", tmp_path / "vue_test.json")
    monkeypatch.setattr(m, "_vue", {})
    monkeypatch.setattr(m, "_depuis_flush", 0)
    return m


def test_acteur_et_sujet_sont_des_axes(vue_isolee):
    """Sans axe, aucune agregation -- le maillon provenance reste aveugle."""
    assert "acteur" in vue_isolee._AXES, (
        "`acteur` n'est pas agrege : la provenance de la chaine d'appel est "
        "transmise a capture() et perdue par la vue")
    assert "sujet" in vue_isolee._AXES, "`sujet` n'est pas agrege"


def test_la_provenance_est_comptee_depuis_l_identite(vue_isolee):
    vue_isolee.noter(
        {"via": "token", "agent": "CLAUDE", "ring": 1,
         "acteur": "classe:porteur_maitre", "sujet": "CLAUDE"},
        "_resolve_ring", {"decision": "ALLOW"})
    d = vue_isolee.vue()
    assert d["by_acteur"].get("classe:porteur_maitre") == 1
    assert d["by_sujet"].get("CLAUDE") == 1


def test_la_provenance_est_lue_dans_extra_en_repli(vue_isolee):
    """`_resolve_ring` passe la provenance en `extra` (suppl.), pas en identite.

    Lire un seul des deux emplacements rendrait 100 % d'absence sur le chemin
    REEL, en laissant croire que la donnee n'existe pas.
    """
    vue_isolee.noter(
        {"via": "token", "agent": "GEMINI", "ring": 2},
        "_resolve_ring", {"acteur": "agent:GEMINI", "sujet": "GEMINI"})
    d = vue_isolee.vue()
    assert d["by_acteur"].get("agent:GEMINI") == 1
    assert d["by_sujet"].get("GEMINI") == 1


def test_une_provenance_absente_reste_absente(vue_isolee):
    """CONTRE-EPREUVE : ne jamais reconstruire ce qui n'a pas ete resolu."""
    vue_isolee.noter({"via": "token", "agent": "TRAY", "ring": 3},
                     "_resolve_ring", {"decision": "ALLOW"})
    d = vue_isolee.vue()
    assert d["by_acteur"].get("(absent)") == 1, (
        "une provenance non resolue doit compter `(absent)`")
    assert "TRAY" not in d["by_acteur"], (
        "l'agent a ete recopie en acteur : c'est une provenance FABRIQUEE")


def test_la_vue_distingue_provenance_et_identite(vue_isolee):
    """Un acteur n'est pas un agent : deux questions, deux axes.

    Sans cette separation, « qui a demande » et « au nom de qui » se
    confondent -- exactement la confusion que la campagne mesure.
    """
    vue_isolee.noter(
        {"via": "master_token", "agent": "POST_COMMIT", "ring": 1,
         "acteur": "classe:porteur_maitre", "sujet": "POST_COMMIT"},
        "_resolve_ring", {"decision": "ALLOW"})
    d = vue_isolee.vue()
    assert d["by_agent"].get("POST_COMMIT") == 1
    assert d["by_acteur"].get("classe:porteur_maitre") == 1
    assert d["by_acteur"].get("POST_COMMIT") is None


def test_aucun_porteur_ne_transite_par_la_vue(vue_isolee):
    """Invariant de securite : `token_h` est ECARTE, le porteur JAMAIS lu."""
    vue_isolee.noter(
        {"via": "token", "agent": "CLAUDE", "ring": 1,
         "token_h": "abcdef0123456789", "acteur": "agent:CLAUDE"},
        "_resolve_ring", {"decision": "ALLOW"})
    serialise = json.dumps(vue_isolee.vue(), ensure_ascii=False)
    assert "abcdef0123456789" not in serialise, "le hash de porteur a fuit"
    assert "by_token_h" not in serialise


def test_une_vue_ancienne_se_charge_sans_perdre_les_nouveaux_axes(
        vue_isolee, tmp_path):
    """Compatibilite : une vue ecrite AVANT ces axes ne doit pas casser.

    `_charger` complete par `setdefault`. Sans ce test, la premiere lecture
    d'une vue persistee leverait KeyError sur `by_acteur` -- et le module
    avale ses erreurs, donc la panne serait MUETTE.
    """
    ancienne = {"total": 7, "by_via": {"token": 7}, "by_agent": {"CLAUDE": 7},
                "by_tool": {}, "by_decision": {}, "by_reason": {},
                "by_scope": {}, "by_ring": {}}
    (tmp_path / "vue_test.json").write_text(
        json.dumps(ancienne), encoding="utf-8")
    vue_isolee._vue = {}
    vue_isolee.noter({"via": "token", "agent": "CLAUDE", "acteur": "agent:CLAUDE"},
                     "_resolve_ring", {})
    d = vue_isolee.vue()
    assert d["total"] == 8, "la vue existante a ete perdue au lieu d'etre etendue"
    assert d["by_acteur"].get("agent:CLAUDE") == 1


def test_la_vue_dit_ce_qu_elle_n_expose_pas(vue_isolee):
    """Un instrument nomme ce qu'il n'a PAS pu voir."""
    d = vue_isolee.vue()
    assert d.get("non_exposes"), "la vue doit nommer ce qu'elle n'expose jamais"
    assert "note_denominateur" in d, (
        "le denominateur compte des OBSERVATIONS, pas des requetes : le dire "
        "evite de lire un volume pour un trafic")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

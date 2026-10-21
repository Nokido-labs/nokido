# -*- coding: utf-8 -*-
"""NR — l'arbre d'évolution des roadmaps : marqueur en tête = liste blanche.

CHANTIER `roadmap_p1_arbre_evolution_ui_web_20261017` (livré par OPENCODE_NEMOTRON, job_094dea4e,
non commité par l'exécuteur ; intégré et relu par CLAUDE le 18/10).
======================================================
But : rendre la trajectoire des roadmaps lisible par l'UI web. Le keeper
(`tools/forge_roadmap_keeper.py`) apprend la sous-commande `--arbre` : elle lit le
tableau noir (zone `architecture_rules`, category `roadmap`) et écrit
`docs/roadmap_arbre.json` — un arbre groupé par état, consommable tel quel par une
page statique.

L'ÉTAT SE LIT EN TÊTE, ET SEUL EN TÊTE
======================================
Le marqueur ouvre le texte du fait : `[CLOS ...]`, `[PARTIEL ...]`,
`[DECISION OWNER ...]`, `[OWNER-PLANIFIE ...]`, `[GELE ...]` / `[SANS OBJET ...]`,
éventuellement après un préfixe de priorité (`P0: [PARTIEL ...]`). Chercher le
marqueur au fil du texte fermerait un chantier par le mot « fait » de la phrase qui
le décrit — même piège que `etat_roadmap` (`app/forge_ssot_maintainer.py`) et que le
minage regex sur de la prose qui rendait déjà des items coupés en plein mot
(mesuré le 2026-07-22, rejoué le 2026-09-22 par `test_roadmap_statut_declare_nr.py`).

LISTE BLANCHE, JAMAIS NOIRE — l'invariant de ce fichier
=======================================================
ABSENCE DE MARQUEUR = SANS_MARQUEUR. MARQUEUR INCONNU = SANS_MARQUEUR.
Seul un marqueur de la liste blanche range un item dans un état qualifié, et
SANS_MARQUEUR n'est JAMAIS CLOS : clore par défaut est exactement le mode d'échec
que la doctrine sémantique du dépôt interdit (un instrument qui ferme sans preuve
fait disparaître des chantiers vivants). Les six compteurs de `par_etat` sont
publiés même à zéro — un comptage absent ne se distingue pas d'un comptage nul.

ZÉRO I/O MACHINE DANS LES TESTS
===============================
Le `read_zone` est un double injecté dans `sys.modules` (patron prouvé par
`test_roadmap_statut_declare_nr.py`) : le test tourne dans un worktree détaché où
la base n'est pas joignable, et aucun NR ne sonde une propriété de la machine. Le
JSON est écrit dans `tmp_path`, jamais dans `docs/` du dépôt pendant pytest.
"""

import json
import sys
import types
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_roadmap_keeper as K  # noqa: E402

# Trois items synthétiques couvrant les trois familles : un marqueur qui QUALIFIE,
# un marqueur de décision owner, et un texte SANS marqueur (jamais clos).
FAITS = [
    {"key": "P0_pont_arbre_green",
     "value": ("[PARTIEL le 2026-10-17 ; reste = ecrire le GREEN du keeper] "
               "P0: le pont arbre est a moitie construit"),
     "trust": 0.9, "updated_at": 1},
    {"key": "p1_decision_owner_seuils",
     "value": ("[DECISION OWNER le 2026-10-16 ; reste = attendre le geste owner] "
               "P1: seuils de methodes a fixer"),
     "trust": 0.9, "updated_at": 2},
    {"key": "P2_item_sans_marqueur",
     "value": ("P2: un texte sans aucun marqueur en tete ; "
               "reste = ne jamais etre range clos"),
     "trust": 0.9, "updated_at": 3},
]


def _double(monkeypatch, faits=None, appels=None):
    """Injecte un `read_zone` faux dans sys.modules (patron test_roadmap_statut_declare)."""
    faux = types.ModuleType("nokido_agent.app.forge_swarm_blackboard")
    appels = appels if appels is not None else []

    def read_zone(zone, *, category=None, min_trust=None, limit=200):
        appels.append({"zone": zone, "category": category, "limit": limit})
        return list(FAITS if faits is None else faits)

    faux.read_zone = read_zone
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_swarm_blackboard", faux)
    return appels


def test_arbre_ecrit_le_json_attendu(tmp_path, monkeypatch):
    """Bout en bout : double read_zone -> JSON écrit au chemin demandé (tmp, pas docs/)."""
    appels = _double(monkeypatch)
    cible = tmp_path / "sous" / "roadmap_arbre.json"
    doc = K.arbre(out=cible)

    assert cible.exists(), "arbre n'a pas écrit le JSON au chemin demandé"
    disque = json.loads(cible.read_text(encoding="utf-8"))
    assert disque == doc, "le JSON relu diffère du document retourné"
    assert "docs" not in cible.parts or tmp_path in cible.parents, (
        "le test ne doit jamais écrire dans docs/ du dépôt"
    )

    datetime.fromisoformat(doc["genere_le"])  # ISO parseable, sinon ValueError ici
    assert doc["total"] == 3
    for etat in ("CLOS", "PARTIEL", "DECISION_OWNER", "OWNER_PLANIFIE",
                 "GELE", "SANS_MARQUEUR"):
        assert etat in doc["par_etat"], (
            f"compteur {etat} absent — les six états sont publiés même à zéro "
            "(un comptage absent ne se distingue pas d'un comptage nul)"
        )
    assert doc["par_etat"] == {"CLOS": 0, "PARTIEL": 1, "DECISION_OWNER": 1,
                               "OWNER_PLANIFIE": 0, "GELE": 0, "SANS_MARQUEUR": 1}, doc["par_etat"]

    par_cle = {i["cle"]: i for i in doc["items"]}
    assert set(par_cle) == {f["key"] for f in FAITS}
    i1 = par_cle["P0_pont_arbre_green"]
    assert i1["etat"] == "PARTIEL" and i1["priorite"] == "P0"
    assert i1["reste"] == "ecrire le GREEN du keeper"
    i2 = par_cle["p1_decision_owner_seuils"]
    assert i2["etat"] == "DECISION_OWNER" and i2["priorite"] == "P1"
    assert i2["reste"] == "attendre le geste owner"
    i3 = par_cle["P2_item_sans_marqueur"]
    assert i3["etat"] == "SANS_MARQUEUR" and i3["priorite"] == "P2"
    assert i3["etat"] != "CLOS", "un texte sans marqueur a été rangé CLOS"

    assert appels, "read_zone n'a jamais été appelé"
    assert appels[0]["zone"] == "architecture_rules"
    assert appels[0]["category"] == "roadmap"


def test_etat_arbre_marqueur_en_tete_liste_blanche():
    """La liste blanche qualifie ; seul le marqueur en tête compte."""
    e = K._etat_arbre
    # Famille de clôture (cohérente avec _ROADMAP_CLOTURE du SSoT).
    assert e("[CLOS 2026-09-20] la phase 0 est sortie") == "CLOS"
    assert e("P1: [CLOS le 2026-09-20] la phase 0 est sortie") == "CLOS"
    assert e("[FAIT le 2026-09-15] les outils consomment la politique") == "CLOS"
    assert e("[LIVRE le 2026-09-15, commit 154800e6b] le triage est executable") == "CLOS"
    assert e("[RESOLU] plus rien a faire ici") == "CLOS"
    assert e("[TERMINE] la campagne est finie") == "CLOS"
    assert e("[FERME] la porte est fermee") == "CLOS"
    # Marqueurs qui qualifient sans clore.
    assert e("[PARTIEL le 2026-10-02] moitie du remede") == "PARTIEL"
    assert e("[PARTIAL / STRUCTURAL le 2026-09-12] corrige mon propre fait") == "PARTIEL"
    assert e("[DECISION OWNER le 2026-10-16] attendre le geste") == "DECISION_OWNER"
    assert e("[OWNER-PLANIFIE 2026-10-16] phase 2 apres l audit") == "OWNER_PLANIFIE"
    assert e("[OWNER PLANIFIE le 2026-10-16] phase 2") == "OWNER_PLANIFIE"
    assert e("[OWNER_PLANIFIE] phase 2") == "OWNER_PLANIFIE"
    assert e("[GELE depuis 2026-10-01] pause owner") == "GELE"
    assert e("[GELÉ depuis 2026-10-01] pause owner") == "GELE"
    assert e("[SANS OBJET] rien a dire ici") == "GELE"


def test_etat_arbre_sans_marqueur_n_est_jamais_clos():
    """ABSENCE DE MARQUEUR = SANS_MARQUEUR. MARQUEUR INCONNU = SANS_MARQUEUR.

    Un marqueur qui QUALIFIE ne clôt pas ; le mot « fait » au fil du texte ne
    clôt pas non plus. Clore par défaut fermerait des chantiers vivants.
    """
    e = K._etat_arbre
    for txt in [
        "P0: le verrou RAG n est pas une contention",
        "P2: un texte sans aucun marqueur en tete",
        "[OUVERT le 2026-09-22] marqueur ouvert",
        "[MESURE le 2026-09-17 sur l arbre COURANT] re-mesure des gates",
        "[DIRECTIVE OWNER REPETEE, consignee le 2026-09-18] le webhub 7400",
        "[ETAPE B MESUREE le 2026-09-15] la campagne docs/launch",
        "[ZORGLUB le 2026-09-22] marqueur invente",
        "[OWNER 2026-10-16 laisserie au owner] ce n est pas un planifie",
        "le mot FAIT apparait au fil du texte et ne ferme rien",
        "", None, 42,
    ]:
        assert e(txt) == "SANS_MARQUEUR", (
            f"{str(txt)[:60]!r} a été rangé à tort : {e(txt)}"
        )


def test_priorite_arbre_cle_puis_texte():
    """P0/P1/P2 dans la clé d'abord, sinon dans le texte, sinon "" — jamais P3."""
    p = K._priorite_arbre
    assert p("P0_audit_gemini", "du texte sans prio") == "P0"
    assert p("p2_ctl_wake_404", "du texte sans prio") == "P2"
    assert p("sans_prio", "la cible P1 est ici") == "P1"
    assert p("", "") == ""
    assert p("xp1 colle", "rien") == "", "P collé à un alnum n'est pas une priorité"
    assert p("p12_donnees", "rien") == "", "P12 n'est pas une priorité"


def test_reste_arbre_premiere_occurrence_et_borne():
    """Premier « reste = » (insensible casse), coupé au « ] », 200 caractères max."""
    r = K._reste_arbre
    assert r("[PARTIEL ; reste = ecrire le GREEN] P0: suite") == "ecrire le GREEN"
    assert r("Reste = avec majuscule en tete") == "avec majuscule en tete"
    assert r("reste = d abord, puis reste = la seconde occurrence est ignoree") == (
        "d abord, puis reste = la seconde occurrence est ignoree"
    )
    assert r("reste = coupe au crochet] encore du texte") == "coupe au crochet"
    assert r("aucune mention de reste ici") == ""
    assert r(None) == "" and r("") == ""
    long = "reste = " + "x" * 300
    assert len(r(long)) <= 200, "reste non borné à 200 caractères"


def test_arbre_source_muette_compte_zero(tmp_path, monkeypatch):
    """Source muette (pas en erreur) : le champ existe et vaut zéro — pas d'exception."""
    _double(monkeypatch, faits=[])
    cible = tmp_path / "vide.json"
    doc = K.arbre(out=cible)
    assert doc["total"] == 0 and doc["items"] == []
    assert all(v == 0 for v in doc["par_etat"].values()), doc["par_etat"]
    assert set(doc["par_etat"]) == {
        "CLOS", "PARTIEL", "DECISION_OWNER", "OWNER_PLANIFIE", "GELE", "SANS_MARQUEUR"
    }


def test_sous_commande_arbre_cli(tmp_path, monkeypatch):
    """La CLI `--arbre` écrit bien le JSON — dans le chemin redirigé par le test,
    jamais dans docs/ du dépôt pendant pytest."""
    _double(monkeypatch)
    cible = tmp_path / "cli.json"
    monkeypatch.setattr(K, "ARBRE_JSON", cible)
    monkeypatch.setattr(sys, "argv", ["forge_roadmap_keeper", "--arbre"])
    rc = K._main()
    assert rc == 0, "--arbre a renvoyé un code d'échec"
    assert cible.exists(), "--arbre n'a pas écrit ARBRE_JSON"
    doc = json.loads(cible.read_text(encoding="utf-8"))
    assert doc["total"] == 3 and doc["par_etat"]["SANS_MARQUEUR"] == 1

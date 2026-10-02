# -*- coding: utf-8 -*-
"""NR — un item de roadmap déclare son ÉTAT, et l'absence de marqueur vaut OUVERT.

LE TROU MESURÉ
==============
Le 2026-09-22, la zone `architecture_rules/roadmap` porte **155 faits** et **aucun
champ de statut**. Les colonnes du blackboard sont `key`, `value`, `category`,
`trust`, `effective_trust`, `age_days`, `worker_id`, `updated_at` — rien qui dise
si un chantier est fini.

Conséquence payée le jour même : pour répondre « quelles roadmaps sont encore
ouvertes ? », il a fallu chercher `FAIT|CLOS|LIVRE` dans les cent quinze premiers
caractères de chaque fait. Le compte obtenu — 21 fermés sur 155 — est un PLANCHER,
pas un verdict : un chantier réellement fini mais non marqué compte ouvert, et un
fait dont le marqueur arrive au caractère 120 passe inaperçu. Dans le même point
d'état, deux findings de sécurité corrigés depuis quatre jours ont été annoncés
« jamais faits ».

LA CONVENTION EXISTE DÉJÀ, ELLE N'EST PAS LUE
=============================================
De nombreux faits portent déjà un marqueur en tête : `P0: [MESURE le 2026-09-17]`,
`P0: [FAIT le 2026-09-15]`, `P1: [VERDICT DE REFERENCE ...]`. On ne crée donc pas
une convention : on rend LISIBLE par la machine celle que les agents écrivent déjà,
dans la fonction qui parse DÉJÀ ce préfixe (`_roadmap_build_doc`), plutôt que dans
un système parallèle.

LISTE BLANCHE, JAMAIS NOIRE — c'est tout le contrat
===================================================
Seul un marqueur RECONNU ferme un item. `[MESURE le ...]`, `[DIRECTIVE OWNER]`,
`[ETAPE B]`, `[CARTO COMPLETE]`, `[PARTIAL]` qualifient un travail sans le clore, et
un marqueur inventé demain ne doit pas fermer non plus. Une liste noire laisserait
toute valeur inattendue tomber du côté « fini » par défaut, ce qui est précisément
le mode d'échec que la constitution sémantique interdit.

    ABSENCE DE MARQUEUR = OUVERT.  MARQUEUR INCONNU = OUVERT.
    Seul un marqueur de la liste blanche ferme.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_ssot_maintainer as M  # noqa: E402


def test_les_marqueurs_de_cloture_ferment():
    for txt, attendu in [
        ("P0: [FAIT le 2026-09-15] les trois outils consomment la politique", "FAIT"),
        ("P1: [CLOS 2026-09-20] la phase 0 est sortie", "CLOS"),
        ("P0: [LIVRE le 2026-09-15, commit 154800e6b] le triage est executable", "LIVRE"),
        ("P2: [RESOLU] plus rien a faire ici", "RESOLU"),
    ]:
        assert M.etat_roadmap(txt) == attendu, f"marqueur de cloture non reconnu : {txt[:48]}"


def test_un_marqueur_qui_QUALIFIE_ne_ferme_pas():
    """Ces cinq formes existent dans la zone AUJOURD'HUI et décrivent un travail
    en cours. Les compter comme closes effacerait cinq chantiers vivants."""
    for txt in [
        "P0: [MESURE le 2026-09-17 sur l arbre COURANT] re-mesure des trois gates",
        "P1: [DIRECTIVE OWNER REPETEE, consignee le 2026-09-18] le webhub 7400",
        "P0: [ETAPE B MESUREE le 2026-09-15] la campagne docs/launch",
        "P0: [CARTO COMPLETE le 2026-09-15, mesure avant tout deport] l empreinte",
        "P1: [PARTIAL / STRUCTURAL le 2026-09-12] corrige mon propre fait",
    ]:
        assert M.etat_roadmap(txt) == "OUVERT", (
            f"un marqueur qui QUALIFIE a ferme l'item : {txt[:60]}"
        )


def test_absence_de_marqueur_et_marqueur_inconnu_valent_OUVERT():
    """Liste BLANCHE : ce qui n'est pas prouvé fini reste ouvert."""
    assert M.etat_roadmap("P0: le verrou RAG n est pas une contention") == "OUVERT"
    assert M.etat_roadmap("P1: [ZORGLUB le 2026-09-22] marqueur invente") == "OUVERT"
    assert M.etat_roadmap("") == "OUVERT"
    assert M.etat_roadmap(None) == "OUVERT"


def test_le_marqueur_doit_etre_EN_TETE_pas_au_fil_du_texte():
    """Sinon le mot « fait » dans une phrase fermerait le chantier qu'elle décrit.
    Mesure du motif frère : le minage regex sur de la prose rendait déjà des items
    coupés en plein mot."""
    txt = "P0: le scrub DETECTE mais ne masque rien, ce qui a ete FAIT le 2026-09-15 ailleurs"
    assert M.etat_roadmap(txt) == "OUVERT", "un marqueur au fil du texte a ferme l'item"


def test_le_doc_separe_les_ouverts_des_clos_et_COMPTE_les_deux():
    """Une borne dit COMBIEN : un état qui ne publie que les ouverts laisse croire
    que le reste n'existe pas.

    ⚠️ CE TEST PORTE SUR LE CODE, PAS SUR LA MACHINE. Première version : il exigeait
    `total > 0`, c'est-à-dire que le blackboard porte des faits. Vert sur le poste de
    travail, ROUGE en CI — la suite tourne dans un worktree détaché où la base n'est
    pas joignable, et l'assertion rendait `assert 0 > 0`. Un seul échec sur 11 637
    tests, et il était de moi.

        UN NR NE SONDE JAMAIS UNE PROPRIÉTÉ DE LA MACHINE.

    Leçon du 2026-09-19 (un NR ne doit jamais asserter `CONFORME`) et ligne R10 de
    `docs/AUDIT_SECURITE_REGISTRE.md`, où deux tests passaient en isolation et
    échouaient en suite pour ce motif exact. Troisième occurrence recensée.

    Ce qui est du CODE et reste exigé : le champ existe, il porte au moins `OUVERT`,
    et le nombre d'items publiés comme restant à faire ne dépasse pas les ouverts.
    Ce qui est de la MACHINE et devient un skip motivé : la présence de faits.
    """
    doc = M._roadmap_build_doc()
    assert "roadmap_statuts" in doc, "le doc ne publie aucun comptage par etat"
    st = doc["roadmap_statuts"]
    assert "OUVERT" in st, (
        f"l'etat OUVERT n'est pas compte : {sorted(st)} — le champ doit etre publie "
        "MEME a zero, sinon un comptage absent ne se distingue pas d'un comptage nul"
    )
    # Cette cohérence tient à vide comme à plein : c'est une propriété du code.
    publies = sum(len(v) for v in doc["roadmap"].values())
    assert publies <= st["OUVERT"], (
        f"{publies} items publies comme restant a faire, pour seulement {st['OUVERT']} "
        "ouverts mesures — des items clos sont republies comme du travail"
    )
    total = sum(st.values())
    print(f"[roadmap] {total} fait(s) avec priorite · par etat : {dict(sorted(st.items()))}")
    if total == 0:
        pytest.skip(
            "blackboard non joignable depuis cet arbre (worktree detache en CI) — "
            "le CONTRAT du doc est verifie ci-dessus, la COUVERTURE sur donnees "
            "reelles ne l'est pas. ILLISIBLE n'est pas CONFORME."
        )


def test_le_doc_tient_son_contrat_QUAND_LE_BLACKBOARD_EST_MUET(monkeypatch):
    """Le cas exact qui a fait rougir la CI, rejoué EN LOCAL.

    Sans ce test, la correction ci-dessus ne serait vérifiée qu'à la prochaine CI
    complète — soit une demi-heure de machine pour savoir si une ligne tient. Le
    chemin qui a cassé doit être exerçable là où on le corrige.

    Contrat quand la source se tait : le champ EXISTE et vaut zéro. Un comptage
    absent ne se distingue pas d'un comptage nul, et c'est la confusion que ce
    champ existe pour tuer.
    """
    import types

    faux = types.ModuleType("nokido_agent.app.forge_swarm_blackboard")
    faux.read_zone = lambda *a, **kw: []  # source muette, pas en erreur
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_swarm_blackboard", faux)

    doc = M._roadmap_build_doc()
    assert "roadmap_statuts" in doc, (
        "blackboard muet -> le doc ne publie plus le comptage : c'est exactement "
        "l'echec de la CI du 2026-09-22 sur le sha 8c990eaf1"
    )
    st = doc["roadmap_statuts"]
    assert st.get("OUVERT") == 0, f"attendu OUVERT=0 sur source muette, obtenu {st}"
    assert doc.get("roadmap_clos") == [], f"clos non vide sur source muette : {doc.get('roadmap_clos')}"
    print(f"[roadmap] source muette -> statuts={st}, contrat tenu")


def test_un_BLOCKER_clos_ne_bloque_plus(monkeypatch):
    """2026-10-02 : la regle de statut ne s'appliquait qu'aux items P0-P2. Un
    « BLOCKER: [CLOS le 2026-10-02 sur remesure] ... » restait affiche parmi les
    bloqueurs du SSoT. Un bloqueur clos sort de la liste et rejoint roadmap_clos ;
    un marqueur qui QUALIFIE ([PARTIEL], [INSTRUIT]) le laisse ouvert (liste blanche)."""
    import types

    faits = [
        {"key": "b_ouvert", "value": "BLOCKER: le verrou tient encore", "trust": 0.9, "updated_at": 1},
        {"key": "b_clos", "value": "BLOCKER: [CLOS le 2026-10-02 sur remesure] l organe vit", "trust": 0.9,
         "updated_at": 2},
        {"key": "b_partiel", "value": "BLOCKER: [PARTIEL le 2026-10-02] moitie du remede", "trust": 0.9,
         "updated_at": 3},
    ]
    faux = types.ModuleType("nokido_agent.app.forge_swarm_blackboard")
    faux.read_zone = lambda *a, **kw: list(faits)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_swarm_blackboard", faux)

    doc = M._roadmap_build_doc()
    bloqueurs = " | ".join(doc["blockers"])
    assert "le verrou tient encore" in bloqueurs and "moitie du remede" in bloqueurs, bloqueurs
    assert "l organe vit" not in bloqueurs, "un BLOCKER clos est encore affiche comme bloquant"
    clos = [c for c in doc["roadmap_clos"] if c.get("priorite") == "BLOCKER"]
    assert [c["cle"] for c in clos] == ["b_clos"] and clos[0]["etat"] == "CLOS", clos

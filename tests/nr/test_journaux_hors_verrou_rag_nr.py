# -*- coding: utf-8 -*-
"""NR — les journaux quittent le verrou RAG, et l'ANCIEN EMPLACEMENT est interdit.

Contrat arrêté par l'owner le 2026-09-22 :

    « On ne déplace pas des tables ; on retire des écrivains du verrou RAG. »
    Le critère n'est pas que la nouvelle base reçoive, c'est que la GROSSE
    CESSE DE RECEVOIR.

CE QUE LA MESURE DIT AUJOURD'HUI
================================
`%NOKIDO_DATA%\embeddings.db` pèse 26 047 Mo et son WAL 1 699 Mo (+91,6 Mo en deux jours).
Sur la fenêtre depuis le 2026-09-20, trois journaux prennent le verrou d'écriture
**15 717 fois**, soit ~4,2 par minute, en concurrence avec le RAG, l'ingestion et
l'embedding :

    token_usage       6 720 écritures
    inspector_log     7 457 insertions réelles (COUNT plafonné à 2000, rotatif)
    conversation_log  1 540 écritures

CONTRE-ÉPREUVE QUI VALIDE LA MÉTHODE : `agent_messages` n'a **aucune** écriture
depuis le 2026-09-20 et sa dernière remonte au 2026-09-06 09:44:54 — la bascule
`m2m.switch` TIENT, seize jours après. Et `task_queue` reste à 3 lignes du
2026-04-27, ce qui confirme que sa migration était un changement sans gain.

LE PIÈGE DU CHANTIER : LE ROTATEUR
==================================
`inspector_log` a **DEUX** écrivains, pas un :

    app/forge_inspector.py        insère
    tools/forge_log_retention.py  SUPPRIME (rotation)

L'écart entre `COUNT=2000` et `MAX(rowid)=176072` vient entièrement du second.
Migrer l'inserteur sans le rotateur laisserait **la moitié des prises de verrou**
sur la base de 25 Go, tout en se relisant comme une migration faite.

    ON NE MIGRE PAS UNE TABLE, ON RETIRE TOUS SES ÉCRIVAINS.

CE QUE CE NR GARDE, ET CE QU'IL NE GARDE PAS
============================================
Il garde le CÂBLAGE et le CONTRAT de l'accesseur, pas l'état du disque. La
bascule elle-même — poser `sandbox/journaux.switch` — est un geste séparé et
réversible, qui se mesure AVANT/APRÈS sur le WAL et la fréquence d'écriture.

C'est l'ordre que `journal_path` rend possible et que sa docstring énonce : un
site qui migre vers l'accesseur **ne change pas de comportement** tant que
l'interrupteur est absent, ce qui permet de vérifier la migration avant de
basculer, puis de basculer d'un seul geste.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_db_path as D  # noqa: E402

# Périmètre MESURÉ le 2026-09-22 : 2 518 modules lus (1 870 à la racine de app/ et
# tools/, 648 dans leurs sous-répertoires sur deux niveaux), 0 illisible, et aucun
# écrivain au-delà de ces quatre. `_attic` et `__pycache__` sont volontairement
# écartés, et c'est dit plutôt que tu.
ECRIVAINS = {
    "app/forge_conversation_logger.py": "conversation_log",
    "app/forge_inspector.py": "inspector_log",
    "tools/forge_log_retention.py": "inspector_log",   # le ROTATEUR
    "app/forge_token_monitor.py": "token_usage",
}


def test_les_trois_journaux_sont_declares():
    """Un journal non déclaré retomberait silencieusement dans la base RAG."""
    connus = set(D.journaux_connus())
    attendus = {"conversation_log", "inspector_log", "token_usage"}
    manquants = attendus - connus
    assert not manquants, f"journaux non declares : {sorted(manquants)} (connus : {sorted(connus)})"


def test_un_journal_inconnu_LEVE_au_lieu_de_retomber_sur_la_base_rag():
    """CONTRE-ÉPREUVE du garde : s'il retombait sur `db_path()`, une faute de
    frappe ramènerait un journal dans le verrou sans que personne le voie."""
    with pytest.raises(ValueError) as exc:
        D.journal_path("journal_qui_n_existe_pas")
    assert "inconnu" in str(exc.value).lower()


def test_sans_interrupteur_le_comportement_est_HISTORIQUE():
    """La migration du câblage ne doit RIEN changer tant qu'on n'a pas basculé.
    C'est ce qui permet de vérifier avant de basculer."""
    if D.journaux_bascules():
        pytest.skip("interrupteur POSE sur cet arbre — ce test décrit l'état d'avant bascule")
    for nom in D.journaux_connus():
        assert D.journal_path(nom) == D.db_path(), (
            f"{nom} ne rend plus la base historique alors que l'interrupteur est absent : "
            "le câblage a changé le comportement, ce qu'il ne doit pas faire"
        )


def test_avec_interrupteur_AUCUN_journal_ne_rend_l_ancienne_base(tmp_path, monkeypatch):
    """LE CONTRAT : ancien emplacement INTERDIT.

    Ce n'est pas « la nouvelle base reçoit » — cette assertion-là est vraie même
    dans une migration fantôme où un chemin continue d'alimenter l'ancienne. La
    seule qui tranche est le NÉGATIF.
    """
    interrupteur = tmp_path / "journaux.switch"
    interrupteur.write_text("test", encoding="utf-8")
    monkeypatch.setattr(D, "_JOURNAUX_SWITCH", interrupteur)
    for nom in D.journaux_connus():
        variable, _f = D._JOURNAUX[nom]
        monkeypatch.delenv(variable, raising=False)
    ancienne = D.db_path()
    retenus = D.journaux_retenus()
    basculables = [n for n in D.journaux_connus() if n not in retenus]
    # Contre-épreuve : une retenue qui engloberait tout rendrait ce test vide.
    assert basculables, "aucun journal basculable : le contrat ne teste plus rien"
    for nom in basculables:
        cible = D.journal_path(nom)
        assert cible != ancienne, (
            f"{nom} rend TOUJOURS {ancienne} alors que l'interrupteur est posé — "
            "la bascule ne retirerait aucun écrivain du verrou"
        )
    # Symétrique : un journal RETENU (décision owner 2026-09-22) reste sur place.
    for nom in retenus:
        assert D.journal_path(nom) == ancienne, (
            f"{nom} est déclaré RETENU mais quitte la base historique"
        )
    assert D.journaux_bascules() is True, "l'interrupteur posé n'est pas vu comme tel"


def test_chaque_ecrivain_resout_sa_base_par_l_accesseur():
    """Le câblage, écrivain par écrivain — y compris le ROTATEUR.

    Un chemin en dur ne suit pas l'interrupteur : le jour de la bascule, il
    continuerait d'écrire dans la base de 25 Go pendant que le reste part
    ailleurs, et la migration se relirait comme faite.
    """
    manquants = []
    for rel, journal in ECRIVAINS.items():
        texte = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        if "journal_path" not in texte:
            manquants.append(f"{rel} ({journal})")
    print(
        f"[journaux] {len(ECRIVAINS) - len(manquants)}/{len(ECRIVAINS)} ecrivain(s) cable(s) "
        f"sur l'accesseur"
    )
    assert not manquants, (
        "ecrivain(s) resolvant leur base HORS de `journal_path`, donc insensible(s) a "
        f"l'interrupteur : {manquants}. Rappel : inspector_log a DEUX ecrivains, "
        "l'inserteur et le rotateur — migrer l'un sans l'autre laisse la moitie des "
        "prises de verrou en place."
    )

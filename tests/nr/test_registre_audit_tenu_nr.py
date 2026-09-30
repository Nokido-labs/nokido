"""NR — le registre des findings de sécurité reste exploitable.

`docs/AUDIT_SECURITE_REGISTRE.md` est le SSoT des défauts trouvés et des
correctifs restants. Un registre qui se périme en silence est pire qu'absent :
on lui fait confiance.

Ce test ne juge pas le CONTENU des findings — il n'en a pas les moyens. Il
verrouille ce qui rend le registre utilisable :

- tout état appartient au vocabulaire déclaré (sinon `ÉTAT` devient du texte
  libre et le tableau cesse d'être lisible par quiconque) ;
- un finding `GELÉ` nomme un NR qui EXISTE — sinon « verrouillé par un NR » est
  une affirmation sans porteur, exactement la dette de câblage que ce dépôt
  paye ailleurs ;
- la section « Restant à faire » ne disparaît pas ;
- les pièges de méthode restent écrits.

⚠️ Ce test n'exige PAS que la liste des restants soit vide. Un registre honnête
porte ses dettes ; c'est leur EFFACEMENT qui serait le défaut.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

REGISTRE = RACINE / "docs" / "AUDIT_SECURITE_REGISTRE.md"
ETATS = {"CORRIGÉ", "GELÉ", "INSTRUIT", "OWNER", "OUVERT", "RÉFUTÉ"}


def _texte() -> str:
    assert REGISTRE.exists(), "le registre des findings a disparu : %s" % REGISTRE
    return REGISTRE.read_text(encoding="utf-8", errors="replace")


def test_tous_les_etats_appartiennent_au_vocabulaire():
    txt = _texte()
    # Les états sont cités entre accents graves dans les colonnes ÉTAT.
    cites = set(re.findall(r"`(CORRIG\w+|GEL\w+|INSTRUIT|OWNER|OUVERT|RÉFUT\w+)`", txt))
    assert cites, "aucun etat trouve : le format du registre a change"
    inconnus = {c for c in cites if c not in ETATS}
    assert not inconnus, (
        "etats hors vocabulaire : %s — si un etat nouveau est necessaire, "
        "l'ajouter a la legende ET a ce test" % inconnus)


def test_chaque_finding_GELE_nomme_un_NR_qui_existe():
    """« verrouillé par un NR » sans NR est une dette de câblage, pas une sécurité."""
    txt = _texte()
    nrs = set(re.findall(r"(test_[a-z0-9_]+_nr)", txt))
    assert nrs, "aucun NR nomme dans le registre : les findings GELES ne sont pas verrouilles"
    manquants = [n for n in nrs if not (RACINE / "tests" / "nr" / (n + ".py")).exists()]
    assert not manquants, (
        "le registre nomme des NR qui n'existent pas : %s" % manquants)


def test_les_findings_CORRIGES_citent_un_sha():
    """⚠️ Ne PAS confondre la legende avec les findings.

    La table de legende contient elle aussi le mot `CORRIGÉ` — la premiere
    version de ce test l'a prise pour un finding sans sha. On ne retient donc
    que les lignes d'un finding, reconnaissables a leur identifiant `| S<n> |`.
    Un instrument qui ne distingue pas son sujet de sa notice mesure autre chose.
    """
    txt = _texte()
    lignes = [l for l in txt.splitlines()
              if "`CORRIG" in l and re.match(r"^\|\s*S\d+\s*\|", l)]
    assert lignes, "plus aucun finding corrige : le tableau a change de forme"
    for l in lignes:
        assert re.search(r"`[0-9a-f]{7,40}`", l), (
            "un finding CORRIGE sans sha de commit n'est pas verifiable : %s" % l[:120])


def test_la_section_des_restants_survit():
    txt = _texte()
    assert "Restant à faire" in txt, (
        "la section des restants a disparu — un registre qui n'affiche plus ses "
        "dettes donne une fausse impression de cloture")
    assert "`OWNER`" in txt, "plus aucun item OWNER : verifier que ce n'est pas un effacement"


def test_les_pieges_de_methode_restent_ecrits():
    """Chacun a coûté une mesure fausse. Les perdre, c'est les re-payer."""
    txt = _texte()
    for marqueur in ("affichage ment", "subprocess", "témoin mal formé",
                     "non appelé", "git archive"):
        assert marqueur.lower() in txt.lower(), (
            "le piege « %s » a disparu du registre" % marqueur)


def test_le_motif_transversal_est_nomme():
    txt = _texte()
    assert "une voie sur N" in txt or "porte" in txt.lower(), (
        "le motif « un garde qui tient une voie sur N » doit rester nomme : "
        "c'est ce qui fait chercher les AUTRES portes")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

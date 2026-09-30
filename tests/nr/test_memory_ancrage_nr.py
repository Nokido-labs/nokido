# -*- coding: utf-8 -*-
"""NR — une memoire n'a jamais plus d'autorite que la preuve qui l'ancre.

HIERARCHIE figee avec l'owner le 2026-09-05, du plus fort au plus faible :
comportement mesure MAINTENANT > code et NR > SSoT du depot > memoire > souvenir
conversationnel. Une fiche ne doit donc jamais battre un NR vert ni un commit.

CAS PAYE LE MEME JOUR. Une fiche affirmait « `axes[nom]` ecrase l'antecedent, donc
rejeu impossible » alors qu'un NR de huit tests prouvait le contraire depuis la
veille. Elle etait VRAIE a son ecriture et FAUSSE le lendemain, et rien ne le
signalait : c'est la boucle qu'on ferme — un fait ancien relu, cru, puis dementi par
l'instrumentation, apres une enquete dans la mauvaise direction.

CE QUE CE GARDE NE FAIT PAS. Il ne lit pas le SENS des fiches et ne pretend detecter
aucune contradiction semantique. Il verifie une relation EXPLICITE et decidable :
memoire -> source -> commit. Une fiche sans ancrage ne devient pas fausse ; elle
cesse seulement de pouvoir se presenter comme un fait courant.

HERMETIQUE : `dernier_commit` est injecte, donc aucun depot git n'est fabrique et
aucun fichier du profil owner n'est lu — le compte qui execute la CI ne peut de
toute facon pas voir `C:/Users/<owner>/...`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_memory_staleness as S  # noqa: E402

RACINE = ROOT


def _fm(**kw):
    return dict(kw)


def _fige(sha):
    """Un `dernier_commit` deterministe : le NR teste le VERDICT, pas git."""
    return lambda source, racine: (sha, None)


def _illisible(motif="git indisponible : PermissionError"):
    return lambda source, racine: (None, motif)


# ── les quatre etats ─────────────────────────────────────────────────────────

def test_source_inchangee_reste_ACTIVE():
    a = S.ancrage(_fm(source="app/x.py", valid_at="abc123def456"), RACINE,
                  _fige("abc123def456"))
    assert a["etat"] == S.ANCRAGE_ACTIF and a["revalidable"] is True


def test_source_changee_depuis_la_verification_rend_STALE():
    """L'invariant central : le monde a bouge, la fiche ne le sait pas."""
    a = S.ancrage(_fm(source="app/x.py", valid_at="abc123def456"), RACINE,
                  _fige("999999999999"))
    assert a["etat"] == S.ANCRAGE_STALE, a
    assert "a change depuis la verification" in a["raison"]


def test_supersession_explicite_prime_sur_tout():
    a = S.ancrage(_fm(source="app/x.py", valid_at="abc123", superseded_by="def456"),
                  RACINE, _fige("abc123"))
    assert a["etat"] == S.ANCRAGE_SUPERSEDED and a["revalidable"] is False


def test_git_illisible_rend_UNKNOWN_et_jamais_ACTIVE():
    """« Je n'ai pas pu demander a git » n'est pas « la source n'a pas bouge ».

    Acquitter ici reviendrait a valider une fiche que personne n'a pu verifier —
    le faux negatif le plus couteux de tout ce corps.
    """
    a = S.ancrage(_fm(source="app/x.py", valid_at="abc123"), RACINE, _illisible())
    assert a["etat"] == S.ANCRAGE_INCONNU, a
    assert a["revalidable"] is True


def test_source_sans_commit_de_verification_rend_UNKNOWN():
    a = S.ancrage(_fm(source="app/x.py"), RACINE, _fige("abc123"))
    assert a["etat"] == S.ANCRAGE_INCONNU
    assert "SANS commit" in a["raison"]


def test_une_fiche_sans_source_reste_active_mais_NON_revalidable():
    """Une regle durable n'a pas de commit : elle ne doit ni bloquer ni mentir."""
    a = S.ancrage(_fm(type="feedback"), RACINE, _fige("abc123"))
    assert a["etat"] == S.ANCRAGE_ACTIF and a["revalidable"] is False


# ── classement ───────────────────────────────────────────────────────────────

def test_la_classe_se_derive_de_ce_que_la_fiche_PORTE():
    assert S.classe(_fm(source="app/x.py")) == "POINTER"
    assert S.classe(_fm(type="feedback")) == "RULE"
    assert S.classe(_fm(type="project")) == "DECISION"
    assert S.classe(_fm()) == "NON_CLASSE"


def test_une_classe_declaree_prime_sur_la_derivation():
    assert S.classe(_fm(classe="RULE", source="app/x.py")) == "RULE"


def test_le_frontmatter_absent_ne_leve_pas():
    assert S.frontmatter("pas de frontmatter du tout") == {}
    assert S.classe(S.frontmatter("")) == "NON_CLASSE"


def test_un_ancrage_perime_devient_un_motif_actionnable():
    """Le lien avec l'axe existant : STALE doit RESSORTIR, pas rester decoratif.

    Un etat calcule que rien ne remonte est une dette de cablage, jamais une
    securite — c'est la lecon `garde branche sur un signal que personne n'emet`.
    """
    a = S.ancrage(_fm(source="app/x.py", valid_at="aaa"), RACINE, _fige("bbb"))
    motif = "ancrage PERIME : %s" % a["raison"]
    assert "app/x.py" in motif and "change" in motif

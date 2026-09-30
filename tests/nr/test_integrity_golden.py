# -*- coding: utf-8 -*-
"""NR -- ordre des rings d'integrite : invariants CALCULES, plus de golden fige.

CE QUI S'EST PASSE (2026-08-20). Ce fichier lisait des datasets figes dans
`data_nr/` via une fixture `data_nr`. Le dossier a disparu du depot, la fixture
aussi : les quatre tests remontaient en ERREUR de setup (« fixture 'data_nr' not
found »), et pytest chargeait un `.pyc` d'un ANCIEN chemin -- les traces
affichaient `...\\LaForge\\tests\\nr\\`, avec « source code not available ». Un
test qui ne peut plus lire ce qu'il compare ne protege rien ; il entretient
l'illusion d'une couverture.

CE QU'ON N'A PAS FAIT. Re-generer un golden depuis le code courant : ce serait
figer un etat non observe, et le socle deviendrait la photo du bug eventuel.
Le projet refuse deja ce raccourci ailleurs (« REFUS de geler : matrice
absente »).

CE QU'ON A FAIT. Garder l'INTENTION -- verifier l'ordre de privilege des rings
-- en la fondant sur des proprietes qui se CALCULENT : reflexivite,
transitivite, antisymetrie, et le sens de la relation. Un golden n'etait qu'un
moyen ; l'invariant, lui, tient sans fichier annexe.

Regle du domaine : `is_at_least(ring, requis)` vaut `ring <= requis`, car un
ring INFERIEUR possede PLUS de droits (MASTER=-1 ... UNTRUSTED=4).
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _zone in ("app", "tools"):
    _p = str(ROOT / _zone)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from forge_integrity import IntegrityRing, is_at_least  # noqa: E402


@pytest.mark.nr
class TestOrdreDesRings:
    """L'ordre de privilege est une relation d'ordre : on le verifie comme telle."""

    def test_tout_ring_se_satisfait_lui_meme(self):
        """Reflexivite : detenir un ring donne au moins les droits de ce ring."""
        for r in IntegrityRing:
            assert is_at_least(r, r) is True, r.name

    def test_la_relation_est_transitive(self):
        """Transitivite : si a couvre b et b couvre c, alors a couvre c.

        C'est l'invariant qui empeche un trou de privilege -- sans lui, une
        chaine d'autorisations pourrait accorder plus que chacun de ses maillons.
        """
        for a, b, c in itertools.product(IntegrityRing, repeat=3):
            if is_at_least(a, b) and is_at_least(b, c):
                assert is_at_least(a, c) is True, (a.name, b.name, c.name)

    def test_deux_rings_qui_se_couvrent_sont_le_meme(self):
        """Antisymetrie : pas deux rings distincts au meme niveau de privilege."""
        for a, b in itertools.product(IntegrityRing, repeat=2):
            if is_at_least(a, b) and is_at_least(b, a):
                assert a is b, (a.name, b.name)

    def test_un_ring_inferieur_a_PLUS_de_droits(self):
        """Le sens de la relation, celui que la docstring du module fixe.

        C'est le piege du domaine : la valeur numerique DECROIT quand le
        privilege CROIT. Une comparaison naive `>` inverserait la securite.
        """
        for a, b in itertools.product(IntegrityRing, repeat=2):
            assert is_at_least(a, b) is (a.value <= b.value), (a.name, b.name)

    def test_master_couvre_tout_et_untrusted_ne_couvre_que_lui_meme(self):
        """Les deux bornes, nommees : elles rendent une inversion evidente."""
        for r in IntegrityRing:
            assert is_at_least(IntegrityRing.MASTER, r) is True, r.name
        couverts = [r for r in IntegrityRing
                    if is_at_least(IntegrityRing.UNTRUSTED, r)]
        assert couverts == [IntegrityRing.UNTRUSTED]

    def test_la_frontiere_de_securite_tient(self):
        """COLLAB et UNTRUSTED ne doivent JAMAIS atteindre les droits TRUSTED."""
        for bas in (IntegrityRing.COLLAB, IntegrityRing.UNTRUSTED):
            assert is_at_least(bas, IntegrityRing.TRUSTED) is False, bas.name
            assert is_at_least(bas, IntegrityRing.SYSTEM) is False, bas.name
            assert is_at_least(bas, IntegrityRing.MASTER) is False, bas.name

    def test_les_six_rings_sont_tous_distincts(self):
        """Un doublon de valeur casserait silencieusement l'antisymetrie."""
        valeurs = [r.value for r in IntegrityRing]
        assert len(valeurs) == len(set(valeurs)) == 6

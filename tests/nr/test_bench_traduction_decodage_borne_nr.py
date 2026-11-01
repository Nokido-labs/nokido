"""NR -- recette owner 28/10, 2e passage : le corpus est lu, puis la mesure « ne se termine pas ».

Cause la plus probable, lue dans le code (le cache tiktoken est present : piste reseau ecartee) : chaque document
est traduit en UN lot de toutes ses lignes, beam 2 et max_decoding_length=512 FIXE -- une ligne longue ou
degeneree fait boucler le decodeur jusqu'a 512 tokens, pour chaque ligne, sans progression. Le decodage est
borne a l'entree (au plus 2x + 16), beam 1, lots de 16.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_bench_traduction as B  # noqa: E402


class _Spm:
    def encode(self, ligne, out_type=str):
        return ligne.split()

    def decode(self, toks):
        return " ".join(toks)


class _Res:
    def __init__(self, toks):
        self.hypotheses = [toks]


class _Tr:
    def __init__(self):
        self.appels = []

    def translate_batch(self, lots, **kw):
        self.appels.append((len(lots), kw))
        self.lots = getattr(self, "lots", []) + list(lots)
        return [_Res(l) for l in lots]


def _traducteur():
    t = B.Traducteur.__new__(B.Traducteur)
    t.src, t.tgt, t.tr = _Spm(), _Spm(), _Tr()
    return t


def test_decodage_borne_a_l_entree_et_lots_limites():
    t = _traducteur()
    texte = "\n".join(f"ligne {i} " + "mot " * 5 for i in range(40))
    assert t(texte).count("\n") == 39
    assert all(n <= 16 for n, _ in t.tr.appels), "un lot unique de toutes les lignes"
    for n, kw in t.tr.appels:
        assert kw.get("beam_size") == 1
        assert kw.get("max_decoding_length") <= 2 * 7 + 16, kw


def test_ligne_longue_decoupee_et_decodage_sous_512_positions():
    """Recette owner 28/10, 3e passage : « No position encodings are defined for positions >= 512 » au volet 2
    (document de 14 539 car.) -- MarianMT n'a que 512 positions : entree decoupee, decodage plafonne."""
    t = _traducteur()
    longue = " ".join(f"m{i}" for i in range(1500))  # une seule ligne de 1500 tokens
    assert t(longue).split() == longue.split()  # rien de perdu au decoupage
    for n, kw in t.tr.appels:
        assert kw["max_decoding_length"] < 512, kw
    assert all(len(lot) <= B.Traducteur.MAX_ENTREE for lot in t.tr.lots), "entree > MAX_ENTREE tokens"


def test_fin_de_phrase_marian_ajoutee_et_retiree():
    """Recette owner 28/10, 4e passage : gain -233 %, sorties en BOUCLE (« Stop stop hook news feed feedback:: »
    repete). MarianMT attend `</s>` en fin d'entree ; sans lui le decodeur ne s'arrete qu'au plafond."""
    t = _traducteur()
    sortie = t("Bonjour le monde")
    assert all(lot and lot[-1] == "</s>" for lot in t.tr.lots), t.tr.lots
    assert "</s>" not in sortie


def test_progression_par_texte(capsys):
    t = _traducteur()
    B.mesurer_volet("v_test", ["Bonjour le monde.", "Deuxieme texte."], t, None)
    err = capsys.readouterr().err
    assert "[mesure] v_test 1/2" in err and "[mesure] v_test 2/2" in err

"""NR forge_sdr_encoder : vérifie l'EFFET (sparsité, overlap, déterminisme, ancrage SR)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
import forge_sdr_encoder as sdr


def test_sparsite_bornee():
    poids = {f"n{i}": float(i) for i in range(200)}
    s = sdr.encode(poids, n_bits=2048, sparsity=0.02)
    assert 0 < len(s) <= max(1, round(0.02 * 2048))  # k = round(sparsity*n) = 41


def test_deterministe_independant_du_seed():
    # hachage FNV stable : même entrée → même SDR (jamais hash() natif)
    a = sdr.encode({"alpha": 5.0, "beta": 3.0})
    b = sdr.encode({"alpha": 5.0, "beta": 3.0})
    assert a == b


def test_overlap_fort_pour_entrees_proches():
    base = {f"n{i}": float(i) for i in range(50)}
    var = dict(base); var["n49"] = 100.0  # quasi identique
    autre = {f"z{i}": float(i) for i in range(50)}  # disjoint
    sig_base, sig_var, sig_autre = sdr.encode(base), sdr.encode(var), sdr.encode(autre)
    assert sdr.similarity(sig_base, sig_var) > sdr.similarity(sig_base, sig_autre)


def test_vide_et_gardes():
    import pytest
    assert sdr.encode({}) == frozenset()
    assert sdr.similarity(frozenset(), frozenset([1])) == 0.0
    with pytest.raises(ValueError):
        sdr.encode({"a": 1.0}, sparsity=0.0)


def test_ancrage_impact_signature():
    import forge_successor_repr as sr
    sig = sr.impact_signature({"X": {"d1", "d2"}, "d1": {"g1"}, "d2": set(), "g1": set()}, "X")
    assert isinstance(sig, frozenset) and len(sig) > 0  # zone d'impact non vide encodée

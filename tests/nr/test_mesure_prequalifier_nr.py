"""NR : prequalifier / exiger_tools / artefact_reference (forge_mesure)."""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app import forge_mesure as fm  # noqa: E402


def _sonde_compteur():
    appels = []

    def sonde(*a, **k):
        appels.append(1)
        return 7
    return sonde, appels


def test_temoin_muet_ne_lance_pas_la_sonde():
    sonde, appels = _sonde_compteur()
    m = fm.prequalifier(lambda: False)(sonde)()
    assert m.statut == "ILLISIBLE" and "témoin muet" in m.motif
    assert appels == []


def test_temoin_en_exception():
    def temoin():
        raise KeyError("x")
    sonde, appels = _sonde_compteur()
    m = fm.prequalifier(temoin)(sonde)()
    assert m.statut == "ILLISIBLE" and "exception du témoin : KeyError" in m.motif
    assert appels == []


def test_exception_sonde_illisible_avec_type():
    def sonde():
        raise ValueError("boom")
    m = fm.prequalifier(lambda: True)(sonde)()
    assert m.statut == "ILLISIBLE" and "ValueError" in m.motif and "boom" in m.motif


def test_succes_valeur_avec_temoin():
    sonde, appels = _sonde_compteur()
    m = fm.prequalifier(lambda: True)(sonde)()
    assert m.statut == "VALEUR" and m.valeur == 7 and m.temoin_positif is True
    assert appels == [1]


def test_payload_sans_tools_non_note():
    for p in ({}, {"tools": []}, {"tools": None}, None):
        m = fm.exiger_tools(p)
        assert m.statut in ("NON_APPLICABLE", "ILLISIBLE") and "tools non transmis" in m.motif
    assert fm.exiger_tools({"tools": [{"n": 1}]}).statut == "VALEUR"


def test_artefact_absent_et_sha(tmp_path):
    assert fm.artefact_reference(str(tmp_path / "nope.md")).statut == "ILLISIBLE"
    f = tmp_path / "r.md"
    f.write_bytes(b"audit")
    assert fm.artefact_reference(str(f)).statut == "VALEUR"
    bon = hashlib.sha256(b"audit").hexdigest()
    assert fm.artefact_reference(str(f), bon).statut == "VALEUR"
    m = fm.artefact_reference(str(f), "0" * 64)
    assert m.statut == "ILLISIBLE" and "référence absente" in m.motif

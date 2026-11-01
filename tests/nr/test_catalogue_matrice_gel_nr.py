"""NR : construire_matrice (chemin reel) gele les voies refusees via geler_voie ; aucun reseau."""
from tools import forge_provider_catalogue as fpc

REPONSES = {
    "ok": (200, "", 10),
    "quota": (429, "Rate limit reached: tokens per day (TPD)", 20),
    "solde": (402, "insufficient balance", 30),
    "absent": (404, "model does not exist", 40),
    "debit": (429, "Too many requests", 50),
}


def _construire():
    fam = "llama-3.3-70b"
    ids = ["meta/llama-3.3-70b-" + k for k in REPONSES]

    def sonder(url, cle, mid):
        return REPONSES[mid.rsplit("-", 1)[1]]

    etiquette = next(e for e, _k, u in fpc.FOURNISSEURS
                     if e not in fpc.SANS_GENERATION and "127.0.0.1" not in u and "localhost" not in u)
    m = fpc.construire_matrice(familles=(fam,), get_secret=lambda k: "cle-bidon",
                               interroger_fn=lambda u, c: (200, ids, ""), sonder_fn=sonder,
                               par_famille_max=10)
    return {v["modele"].rsplit("-", 1)[1]: v for v in m["familles"][fam] if v["fournisseur"] == etiquette}


def test_refus_geles_jamais_retires_ni_zero():
    v = _construire()
    assert set(v) == set(REPONSES)  # aucune voie retiree
    for k in ("quota", "solde", "absent", "debit"):
        assert v[k]["gelee"] is True and v[k]["score"] is None
    assert v["quota"]["etat"] == "QUOTA_EPUISE" and v["quota"]["echeance"]
    assert v["solde"]["etat"] == "SANS_SOLDE"
    assert v["absent"]["etat"] == "MODELE_ABSENT"
    assert "gelee" not in v["ok"] and v["ok"]["etat"] == "JOIGNABLE"


def test_debit_reste_a_resonder_sans_echeance():
    d = _construire()["debit"]
    assert d["etat"] == "DEBIT" and d["a_resonder"] is True and "echeance" not in d

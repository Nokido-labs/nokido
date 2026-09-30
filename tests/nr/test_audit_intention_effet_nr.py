"""NR — le contrat intention/objectif distingue-t-il vraiment QUATRE etats ?

Ce test couvre `forge_audit_intention_effet` et la partie contrat de
`forge_service_capabilities`, ajoutes le 2026-08-25 apres l'audit owner
(« ce qui n'est pas utile a l'instant T ne devrait pas tourner »).

Ce qu'il verifie, et pourquoi c'est l'EFFET et pas l'import : tout l'interet du
contrat tient a ne PAS confondre « objectif manque » et « mesure illisible ». Un
capteur qui rend `manque` quand il n'a pas pu regarder condamne des services sains
— c'est le defaut exact que cette famille d'outils a paye toute la journee du
2026-08-25 (un `False` d'ACL lu comme une absence, un runner `busy=False` lu comme
un job orphelin, un comptage de connexions instantane lu comme « ne sert a rien »).
La contre-epreuve finale verifie que le garde SAIT MORDRE : un garde incapable
d'echouer ne garde rien.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

import forge_service_capabilities as sc  # noqa: E402


def test_evaluer_objectif_distingue_quatre_etats():
    """atteint / manque / illisible / sans_objet — jamais trois."""
    assert sc.evaluer_objectif("hb<900", {"hb_s": 120.0})[0] == "atteint"
    assert sc.evaluer_objectif("hb<900", {"hb_s": 5000.0})[0] == "manque"
    assert sc.evaluer_objectif("aucun", {})[0] == "sans_objet"


def test_mesure_absente_rend_illisible_et_jamais_manque():
    """LE point du contrat. Une mesure a None n'est pas un zero.

    Si ce test tombe, le contrat condamne des services qu'il n'a pas su mesurer.
    """
    etat, detail, _ = sc.evaluer_objectif("hb<900", {"hb_s": None})
    assert etat == "illisible", detail
    etat, _, _ = sc.evaluer_objectif("cpu>0.05 | conn>0", {})
    assert etat == "illisible"


def test_le_signal_de_vie_emane_ou_est_palpe():
    """Correction owner : un heartbeat EMANE, un cpu se PALPE. Pas la meme chose.

    Sans cette distinction, un organe qui ne temoigne jamais recoit le meme verdict
    qu'un organe qui declare son etat — et la palpation dispense de l'innerver.
    """
    assert sc.nature_de("hb<900") == "AFFERENT"
    assert sc.nature_de("emis<600") == "AFFERENT"
    assert sc.nature_de("cpu>0.05") == "PALPATION"
    assert sc.nature_de("conn>0") == "PALPATION"
    assert sc.nature_de("listen") == "PALPATION"
    # `actes` est ce que la REGULATION dit du service, pas ce que le service emet.
    assert sc.nature_de("actes>3") == "PALPATION"
    assert sc.nature_de("bidule>1") == "INCONNUE"


def test_le_temoignage_prime_sur_la_palpation():
    """Si les deux preuves existent, la nature retenue doit etre AFFERENTE.

    Autrement l'ORDRE D'ECRITURE dans services.toml deciderait de la nature de la
    preuve — un detail de redaction ne doit pas trancher une question de conception.
    """
    _, _, nature = sc.evaluer_objectif("cpu>0.05 | hb<900",
                                       {"cpu_pct": 9.0, "hb_s": 10.0})
    assert nature == "AFFERENT"


def test_innerve_designe_les_organes_muets():
    """Un contrat sans aucun terme afferent = organe DENERVE, et il faut le dire."""
    blocs = sc._blocs()
    if not blocs:
        pytest.skip("services.toml illisible dans cet environnement")
    # Contre-epreuve : la fonction doit savoir repondre NON, sinon elle ne designe rien.
    reponses = {sc.innerve(s) for s in blocs}
    assert False in reponses, (
        "innerve() ne rend jamais False : elle ne peut designer aucun organe muet"
    )


def test_objectif_est_un_OU_une_seule_preuve_suffit():
    etat, detail, _ = sc.evaluer_objectif("cpu>0.05 | conn>0", {"cpu_pct": 0.0, "conn": 3})
    assert etat == "atteint", detail
    etat, _, _ = sc.evaluer_objectif("cpu>0.05 | conn>0", {"cpu_pct": 0.0, "conn": 0})
    assert etat == "manque"


def test_terme_de_grammaire_inconnue_ne_condamne_pas():
    """Un objectif mal ecrit doit rendre `illisible`, pas `manque`.

    Autrement une faute de frappe dans services.toml suffirait a declarer un
    service defaillant — un garde qui punit sa propre configuration.
    """
    assert sc.evaluer_objectif("bidule>3", {})[0] == "illisible"


def test_contrat_derive_avant_de_declarer_ABSENT():
    """La derivation doit couvrir la majorite, sinon le contrat est inapplicable."""
    blocs = sc._blocs()
    if not blocs:
        pytest.skip("services.toml illisible dans cet environnement")
    sources = [sc.contrat_de(s)["source"] for s in blocs]
    assert sources.count("ABSENT") < len(sources) / 2, (
        "plus de la moitie des services sans contrat deductible : la derivation "
        "ne remplit pas son role, chaque service devrait etre ecrit a la main"
    )
    for s in blocs:
        c = sc.contrat_de(s)
        assert c["source"] in ("declare", "derive", "ABSENT")
        if c["source"] != "ABSENT":
            assert c["intention"] and c["objectif"]


def test_declare_prime_sur_derive():
    """Un objectif ecrit a la main doit l'emporter sur la derivation automatique."""
    blocs = sc._blocs()
    declares = [s for s in blocs if (blocs[s].get("intention") or blocs[s].get("objectif"))]
    if not declares:
        pytest.skip("aucun contrat explicite declare pour le moment")
    for s in declares:
        assert sc.contrat_de(s)["source"] == "declare"


def test_audit_mesure_le_heartbeat_en_trois_etats(tmp_path):
    """`forge_audit_intention_effet` doit rendre None / inf / une valeur — pas un booleen."""
    pytest.importorskip("psutil")
    import forge_audit_intention_effet as aie

    # pas de heartbeat declare -> None, et surtout pas 0
    assert aie._heartbeat_age("ServiceQuiNExistePas", {}) is None
    # heartbeat declare mais fichier absent -> infini, distinct de "pas declare"
    age = aie._heartbeat_age("X", {"X": {"heartbeat": "sandbox/inexistant.heartbeat"}})
    assert age == float("inf")


# ─────────────────────── le nerf afferent (forge_organ_afferent) ─────────────
def test_le_pouls_absent_rend_None_et_une_raison():
    """`dernier_pouls` doit rendre TROIS etats, jamais un booleen.

    None = cet organe n'a JAMAIS battu. Ce n'est ni « il va mal », ni « la moelle
    est illisible » — et la raison rendue permet de les distinguer.
    """
    import forge_organ_afferent as oa

    age, raison = oa.dernier_pouls("OrganeQuiNExistePas")
    assert age is None
    assert raison, "un silence sans raison ne se diagnostique pas"


def test_emettre_relaie_le_refus_de_la_moelle(monkeypatch):
    """Quand la moelle refuse, le nerf doit rendre False ET la raison.

    Un `emettre` qui rendrait True en avalant le refus ferait croire a un organe
    innerve alors que rien n'est arrive dans la moelle — exactement le faux positif
    que ce contrat existe pour empecher.

    Le refus est SIMULE : ce test ne doit rien ECRIRE dans la moelle reelle. Un test
    qui pollue l'organe qu'il observe fausse toutes les mesures suivantes, et il
    n'aurait pas sa place dans une suite dite « pure ».
    """
    import forge_organ_afferent as oa

    monkeypatch.setattr(oa.spine, "ingerer",
                        lambda *a, **k: (None, "provenance refusee (simulee)"))
    ok, raison = oa.emettre("organe_de_test", "organe/test", {"x": 1})
    assert ok is False
    assert "refusee" in raison, raison


def test_emettre_signale_une_ecriture_perdue(monkeypatch):
    """Ingestion acceptee mais ECRITURE echouee : le nerf ne doit pas rendre True.

    Une trace perdue ne se distingue pas d'un evenement qui n'a pas eu lieu — la
    moelle le dit elle-meme dans son propre journal d'erreur.
    """
    import forge_organ_afferent as oa

    monkeypatch.setattr(oa.spine, "ingerer", lambda *a, **k: ({"ts": 0.0}, ""))
    monkeypatch.setattr(oa.spine, "ecrire", lambda *a, **k: False)
    ok, raison = oa.emettre("organe_de_test", "organe/test", {"x": 1})
    assert ok is False and raison


def test_les_organes_medies_declarent_ce_qu_ils_temoignent():
    """Chaque organe medie doit nommer son interface ET les champs qui sont SA mesure.

    Sans les champs, on retomberait a lire n'importe quoi de la reponse — donc a
    palper a travers une API au lieu de recueillir un temoignage.
    """
    import forge_organ_afferent as oa

    assert oa.MEDIES, "aucun organe medie declare"
    for svc, spec in oa.MEDIES.items():
        assert spec.get("url"), "%s sans interface" % svc
        assert spec.get("champs"), "%s sans champ de temoignage" % svc
        assert spec.get("organe"), "%s sans organe declare" % svc


def test_le_garde_sait_mordre():
    """Contre-epreuve : le contrat DOIT pouvoir rendre `manque`.

    Sans elle, une implementation qui renverrait `atteint` ou `illisible` en toute
    circonstance passerait ce fichier au vert et ne garderait rien.
    """
    etats = {sc.evaluer_objectif("hb<10", {"hb_s": v})[0] for v in (1.0, 9999.0)}
    assert etats == {"atteint", "manque"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

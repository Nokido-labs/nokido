"""NR — le manifeste de certification distingue le SUJET de ce qui a ete JUGE.

Mesure fondatrice, 2026-09-19 : `e5ab874eb` (certifie) et `01ad657eb` (publie)
different par **une seule entree de `PURE_TESTS`**. Zero fichier produit ne change
entre les deux. Sans `test_plan_hash`, les deux certifications seraient
indiscernables tout en n'ayant pas juge le meme perimetre — et le raisonnement
« meme produit, donc meme certification » passerait pour valide.

Ces tests gardent les quatre proprietes qui font qu'une preuve est une preuve :
canonique (l'ordre d'ecriture ne la change pas) · discriminante (une entree de
plus la change) · honnete sur ses angles morts · et RECALCULEE a la lecture,
jamais recopiee.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
fcp = importlib.import_module("forge_ci_proof")

PLAN = ["tests/nr/test_a_nr.py", "tests/nr/test_b_nr.py"]
BLOCS = [("tests/nr/test_hub_auth.py", "motif"), ("tests/nr/test_x.py", "motif")]


def _m(**kw):
    base = dict(target_sha="e5ab874eb3af", observed_head="e5ab874eb3af",
                process_state="CAPTURED", certification_state="SUITE_COMPLETE",
                test_plan_hash="p", ci_contract_hash="c",
                environment_fingerprint="e")
    base.update(kw)
    return fcp.manifeste(**base)


# ───────────────────────────────── canonique ────────────────────────────────

def test_l_ordre_d_ecriture_ne_change_PAS_l_empreinte_du_plan():
    """Sinon l'empreinte cesse de mesurer le PLAN pour mesurer sa mise en page."""
    assert fcp.hash_plan(PLAN, BLOCS) == fcp.hash_plan(list(reversed(PLAN)),
                                                       list(reversed(BLOCS)))
    assert fcp.hash_plan(PLAN + PLAN, BLOCS) == fcp.hash_plan(PLAN, BLOCS), \
        "un doublon n'ajoute rien au perimetre declare"


def test_UNE_entree_de_plus_change_l_empreinte(
):
    """Le cas MESURE : e5ab874eb vs 01ad657eb, une seule entree d'ecart."""
    avant = fcp.hash_plan(PLAN, BLOCS)
    apres = fcp.hash_plan(PLAN + ["tests/nr/test_bump_superrepo_ordre_nr.py"], BLOCS)
    assert avant != apres


def test_une_EXCLUSION_explicite_fait_partie_du_plan():
    """Un test retire change le plan autant qu'un test ajoute ; le taire rendrait
    un retrait invisible."""
    assert fcp.hash_plan(PLAN, BLOCS) != fcp.hash_plan(PLAN, BLOCS, exclusions=["x"])


def test_un_bloc_isole_compte_dans_le_plan():
    assert fcp.hash_plan(PLAN, BLOCS) != fcp.hash_plan(PLAN, BLOCS[:1])


# ───────────────────────────────── contrat ──────────────────────────────────

def test_le_contrat_change_avec_le_contenu_des_regles(tmp_path):
    f = tmp_path / "regle.py"
    f.write_text("A", encoding="utf-8")
    h1, ill1 = fcp.hash_contrat([f])
    f.write_text("B", encoding="utf-8")
    h2, ill2 = fcp.hash_contrat([f])
    assert h1 != h2 and ill1 == [] and ill2 == []


def test_un_fichier_de_contrat_ILLISIBLE_est_NOMME_pas_ignore(tmp_path):
    """Hacher ce qu'on a pu lire en se taisant sur le reste produirait une
    empreinte qui a l'air complete."""
    ok = tmp_path / "ok.py"
    ok.write_text("A", encoding="utf-8")
    _h, illisibles = fcp.hash_contrat([ok, tmp_path / "absent.py"])
    assert len(illisibles) == 1 and "absent.py" in illisibles[0]


# ─────────────────────────────── certification ──────────────────────────────

def test_seule_une_suite_COMPLETE_certifie():
    for etat in ("SUITE_INCOMPLETE", "SUITE_PARTIELLE", "NON_CERTIFIANT",
                 "UNKNOWN", ""):
        ok, motif = fcp.certifie(_m(certification_state=etat))
        assert not ok, etat
    assert fcp.certifie(_m())[0]


def test_un_process_state_non_CAPTURE_ne_certifie_JAMAIS():
    """L'etat de PREUVE prime sur l'etat de TEST.

    Une suite declaree complete sur un sujet qu'on n'a pas su identifier ne
    certifie rien : sans capture, `observed_head` est inconnu, donc la suite
    n'a pas de sujet PROUVE. Le manifeste le dit au lieu de le normaliser.
    """
    for etat in ("NO_CAPTURE", "CAPTURE_REFUSED", "INCONNU"):
        m = _m(process_state=etat)
        ok, motif = fcp.certifie(m)
        assert not ok, etat
        assert m["incoherences"], "la contradiction doit etre DITE, pas tue"


def test_sujet_promouvable_rend_l_OBSERVE_jamais_le_DECLARE():
    """`target_sha` est une DEMANDE, `observed_head` une MESURE.

    Promouvoir le sha declare reviendrait a certifier un arbre qu'on n'a pas
    juge. Le contre-cas le prouve : quand les deux different, le manifeste
    refuse AVANT de rendre quoi que ce soit.
    """
    sujet, motif = fcp.sujet_promouvable(_m())
    assert sujet == "e5ab874eb3af", motif
    m = _m(observed_head="ffffffffffff")
    assert m["incoherences"], "divergence declare/observe non signalee"
    sujet2, motif2 = fcp.sujet_promouvable(m)
    assert sujet2 is None and "observed_head" in motif2


def test_une_capture_manquante_laisse_observed_head_a_None_pas_au_declare():
    """Taire l'inconnu, jamais le combler avec ce qu'on esperait.

    Recopier `target_sha` dans `observed_head` ferait d'une DEMANDE une MESURE
    — c'est exactement la confusion que la paire de champs existe pour tuer.
    """
    m = _m(observed_head=None, process_state="NO_CAPTURE",
           certification_state="NON_CERTIFIANT")
    assert m["observed_head"] is None
    assert m["target_sha"] == "e5ab874eb3af"
    ok, motif = fcp.certifie(m)
    assert not ok and "observed_head" in motif


def test_un_champ_absent_REFUSE_et_le_NOMME():
    ok, motif = fcp.certifie(_m(test_plan_hash=None))
    assert not ok and "test_plan_hash" in motif


def test_un_contrat_illisible_REFUSE_la_certification():
    ok, motif = fcp.certifie(_m(contrat_illisible=["tools/ci_local.py (OSError)"]))
    assert not ok and "ILLISIBLE" in motif


def test_un_schema_inconnu_REFUSE():
    m = _m()
    m["schema_version"] = 999
    ok, motif = fcp.certifie(m)
    assert not ok and "schema" in motif


def test_la_promotion_peut_EXIGER_davantage():
    """`dependency_lock_hash` arrive avec le chantier B : aujourd'hui absent,
    donc DECLARE non couvert. Une promotion qui l'exige doit etre refusee."""
    m = _m()
    assert fcp.certifie(m)[0], "la certification de base passe sans le lock"
    assert "dependency_lock_hash" in m["non_couvert"], \
        "un manque tu se lirait comme un poste couvert"
    ok, motif = fcp.certifie(m, exiger=("dependency_lock_hash",))
    assert not ok and "dependency_lock_hash" in motif

    # Contrat DURCI par B (2026-09-19) : le hash seul ne suffit plus, la
    # reconciliation avec l'installe doit l'accompagner. Ce test portait
    # l'ancien contrat et l'a signale en tombant — c'est son role.
    m2 = _m(dependency_lock_hash="abc", dependency_match="CONFORME")
    assert m2["non_couvert"] == []
    assert fcp.certifie(m2, exiger=("dependency_lock_hash",))[0]


def test_un_lock_DECLARE_sans_reconciliation_ne_certifie_PAS():
    """Le coeur de B (owner 2026-09-19) : un hash de lock affirme quelque chose
    sur un FICHIER. Sans reconciliation, il n'affirme rien sur l'environnement
    qui a produit la preuve — et avec un env PERMANENT partage avec le hub, c'est
    precisement l'ecart a fermer.
    """
    ok, motif = fcp.certifie(_m(dependency_lock_hash="abc"))
    assert not ok and "NON RECONCILIE" in motif

    for etat in ("DIVERGENT", "ILLISIBLE"):
        ok2, motif2 = fcp.certifie(_m(dependency_lock_hash="abc",
                                      dependency_match=etat))
        assert not ok2 and etat in motif2

    assert fcp.certifie(_m(dependency_lock_hash="abc",
                           dependency_match="CONFORME"))[0]


def test_sans_lock_du_tout_la_certification_de_BASE_reste_possible():
    """Ne pas fermer la porte avant que B soit livre : le manque est DECLARE."""
    m = _m()
    assert fcp.certifie(m)[0]
    assert "dependency_lock_hash" in m["non_couvert"]
    assert not fcp.certifie(m, exiger=("dependency_lock_hash",))[0]


def test_le_manifeste_ne_PORTE_pas_de_booleen_certified():
    """Un booleen transporte survit a la raison qui l'a rendu vrai."""
    m = _m()
    assert "certified" not in m and "certifie" not in m
    assert isinstance(fcp.certifie(m), tuple)


# ──────────────────────────────── substrat ──────────────────────────────────

def test_le_substrat_REJOINT_l_empreinte_d_environnement():
    """Owner 2026-09-19 : deux runs du meme sha sur des materiels differents ne
    sont pas la meme experience. Le materiel n'etait meme pas un angle mort
    DECLARE de `empreinte_contexte`.
    """
    a = fcp.manifeste(target_sha="s", observed_head="s", process_state="CAPTURED",
                      certification_state="SUITE_COMPLETE", test_plan_hash="p",
                      ci_contract_hash="c", environment_fingerprint="e",
                      substrat={"cpu_count": 16, "modele_cpu": "Ryzen 7 8700G"})
    b = fcp.manifeste(target_sha="s", observed_head="s", process_state="CAPTURED",
                      certification_state="SUITE_COMPLETE", test_plan_hash="p",
                      ci_contract_hash="c", environment_fingerprint="e",
                      substrat={"cpu_count": 8, "modele_cpu": "Ryzen 7 8700G"})
    assert a["environment_fingerprint"] != b["environment_fingerprint"], \
        "un substrat different doit donner une empreinte differente"


def test_le_substrat_reste_LISIBLE_a_cote_du_hash():
    """Un hash seul ne se diagnostique pas : « les empreintes different » n'apprend
    rien sans le detail."""
    m = _m(substrat={"cpu_count": 16, "modele_cpu": "Ryzen 7 8700G"})
    assert m["substrate"]["modele_cpu"] == "Ryzen 7 8700G"


def test_un_module_absent_n_est_PAS_une_capacite_absente():
    """Mesure 2026-08-30 : `crawl4ai` conteneurise, lu ABSENT par find_spec dans
    trois environnements. Le vocabulaire doit interdire la sur-deduction.
    """
    sub = fcp.empreinte_substrat()
    for m, etat in sub["modules"].items():
        assert etat == "present" or etat.startswith(("module_absent", "ILLISIBLE")), \
            "%s -> %r : ni 'absent' ni False, qui se liraient comme une capacite absente" % (m, etat)
    assert any("SERVICE" in x or "CONTENEURISEES" in x for x in sub["NON_COUVERT"]), \
        "l'angle mort doit etre DECLARE, sinon l'empreinte se lit comme exhaustive"


def test_le_substrat_dit_ce_qu_il_n_a_pas_pu_lire(monkeypatch):
    """ILLISIBLE n'est pas INCONNU : sur un compte bride, on le DIT."""
    import builtins
    vrai = builtins.__import__

    def _ko(nom, *a, **k):
        if nom == "winreg":
            raise ImportError("pas de registre ici")
        return vrai(nom, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _ko)
    assert fcp.empreinte_substrat()["modele_cpu"].startswith("ILLISIBLE")


def test_le_substrat_reel_de_cette_machine_est_renseigne():
    """Chemin reel : sur la machine de certification, ces champs ne doivent pas
    etre vides — une empreinte vide se lirait comme un substrat neutre."""
    sub = fcp.empreinte_substrat()
    assert sub["arch"] and sub["cpu_count"] and sub["os"]
    assert set(sub["modules"]) >= {"torch", "faiss", "onnxruntime"}


# ──────────────────────────────── ecriture ──────────────────────────────────

def test_ecrire_RELIT_ce_qu_il_a_ecrit(tmp_path):
    """Conclure sur l'absence d'erreur d'ecriture laisse passer une preuve
    tronquee."""
    cible = tmp_path / "sous" / "ci_proof.json"
    ok, motif = fcp.ecrire(cible, _m())
    assert ok, motif
    assert json.loads(cible.read_text(encoding="utf-8"))["target_sha"] == "e5ab874eb3af"


def test_lire_distingue_ABSENT_de_ILLISIBLE(tmp_path):
    m, motif = fcp.lire(tmp_path / "jamais_ecrit.json")
    assert m is None and motif.startswith("ABSENT")

    casse = tmp_path / "casse.json"
    casse.write_text("{ pas du json", encoding="utf-8")
    m2, motif2 = fcp.lire(casse)
    assert m2 is None and motif2.startswith("ILLISIBLE")


def test_le_manifeste_relu_reste_certifiable(tmp_path):
    """Chemin reel : ecrire -> relire -> juger. Un manifeste qui ne survit pas a
    son propre aller-retour n'est pas portable."""
    cible = tmp_path / "ci_proof.json"
    assert fcp.ecrire(cible, _m())[0]
    relu, motif = fcp.lire(cible)
    assert relu is not None, motif
    assert fcp.certifie(relu)[0]

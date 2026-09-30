"""NR — chaque cle doit pouvoir nommer son organe proprietaire, ou dire pourquoi elle ne peut pas.

PHASE 3 du mandat « organe de secretion securisee ».

SEARCH BEFORE BUILD, fait avant d'ecrire une ligne :
  * `introspect`                        -> AUCUN registre de provenance dedie
  * `forge_retrieval_sweep provenance`  -> `forge_session_provenance` existe, mais
                                           il trace des SESSIONS, pas des cles
  * `sandbox/workspace/organ_map_full.json` -> EXISTE et est peuple :
                                           1755 modules deja rattaches a un organe
  * `forge_key_rotation`                -> rotation par CONVENTION de suffixes
  * `forge_integrity.IntegrityManager.revoke` -> revocation identite + token

=> La provenance ne se CONSTRUIT pas. Elle se DERIVE de la carte d'organes que
   le corps tient deja, jointe a l'inventaire de cles de la phase 1. Creer un
   second registre aurait garanti qu'il diverge du premier.

CE QUE CE NR VERROUILLE
=======================
1. Le verdict appartient a un ensemble FERME. « 82 cles OK » n'est pas un
   resultat : la question est « qui possede quoi, et qu'est-ce qu'on ignore ».
2. Une carte d'organes ILLISIBLE rend OWNER_UNKNOWN, JAMAIS ORPHAN. Confondre
   « je n'ai pas pu lire la carte » avec « cette cle n'a pas de proprietaire »
   fabriquerait des orphelins par panne d'instrument.
3. N modules dans UN organe n'est PAS un defaut (directive owner). Seul le
   partage ENTRE organes est une question a instruire.
4. Un partage inter-organes EXPLIQUE se declare ; il ne se devine pas. Sans
   declaration, le verdict reste SHARED_UNEXPLAINED -- ce qui est une question
   ouverte, pas une accusation.
5. Aucune valeur de secret n'est lue : la provenance se derive de NOMS, de
   CHEMINS et d'une carte de modules.
"""
import json

import pytest

MOD = "nokido_agent.tools.forge_secret_source_audit"

VERDICTS = {
    "OWNER_PROVEN",         # tous les sites dans UN seul organe
    "SHARED_BY_DESIGN",     # plusieurs organes, partage DECLARE
    "SHARED_UNEXPLAINED",   # plusieurs organes, aucun contrat -- a instruire
    "OWNER_UNKNOWN",        # des sites reels, mais l'organe n'est pas connaissable
    "ORPHAN",               # aucun site : declaree et jamais demandee
}


@pytest.fixture()
def audit():
    import importlib

    return importlib.import_module(MOD)


@pytest.fixture()
def depot(tmp_path):
    """Un mini-depot dont on connait la reponse exacte."""
    app = tmp_path / "app"
    app.mkdir()
    (app / "rein_a.py").write_text(
        "from nokido_agent.app.forge_secrets import get_secret\n"
        "K = get_secret('CLE_D_UN_SEUL_ORGANE')\n",
        encoding="utf-8",
    )
    (app / "rein_b.py").write_text(
        "from nokido_agent.app.forge_secrets import get_secret\n"
        "K = get_secret('CLE_D_UN_SEUL_ORGANE')\n"
        "J = get_secret('CLE_PARTAGEE_ENTRE_ORGANES')\n",
        encoding="utf-8",
    )
    (app / "foie_c.py").write_text(
        "from nokido_agent.app.forge_secrets import get_secret\n"
        "J = get_secret('CLE_PARTAGEE_ENTRE_ORGANES')\n",
        encoding="utf-8",
    )
    (app / "inconnu_d.py").write_text(
        "from nokido_agent.app.forge_secrets import get_secret\n"
        "Z = get_secret('CLE_SANS_ORGANE_CONNU')\n",
        encoding="utf-8",
    )
    carte = tmp_path / "carte.json"
    carte.write_text(json.dumps({"module_organ": {
        "rein_a.py": "Renal", "rein_b.py": "Renal", "foie_c.py": "Hepatique",
        # inconnu_d.py VOLONTAIREMENT absent de la carte
    }}), encoding="utf-8")
    return tmp_path, carte


# ------------------------------------------------------------- le contrat

def test_la_fonction_existe_et_rend_un_verdict_ferme(audit, depot):
    racine, carte = depot
    assert hasattr(audit, "proprietaires"), (
        "la provenance doit etre EXPOSEE par le module qui porte deja "
        "l'inventaire, pas recalculee par chaque appelant"
    )
    prov, stats = audit.proprietaires(racine=racine, bases=("app",), carte=carte)
    assert set(prov), "un depot avec des cles ne peut pas rendre une carte vide"
    for nom, fiche in prov.items():
        assert fiche["verdict"] in VERDICTS, "%s porte %r" % (nom, fiche.get("verdict"))
    assert "modules_classes" in stats, "l'instrument doit dire sur quoi il s'appuie"


def test_un_seul_organe_plusieurs_modules_nest_pas_un_defaut(audit, depot):
    """Directive owner : « consommee par 17 modules mais un seul organe, ce
    n'est pas automatiquement un defaut »."""
    racine, carte = depot
    prov, _ = audit.proprietaires(racine=racine, bases=("app",), carte=carte)
    fiche = prov["CLE_D_UN_SEUL_ORGANE"]
    assert fiche["verdict"] == "OWNER_PROVEN"
    assert fiche["organes"] == ["Renal"]
    assert len(fiche["sites"]) == 2


def test_un_partage_entre_organes_est_une_question_pas_un_verdict(audit, depot):
    racine, carte = depot
    prov, _ = audit.proprietaires(racine=racine, bases=("app",), carte=carte)
    fiche = prov["CLE_PARTAGEE_ENTRE_ORGANES"]
    assert fiche["verdict"] == "SHARED_UNEXPLAINED"
    assert sorted(fiche["organes"]) == ["Hepatique", "Renal"]
    assert fiche.get("instruire"), (
        "SHARED_UNEXPLAINED doit dire ce qu'il faut instruire, sinon c'est un "
        "cul-de-sac comme l'etait INDETERMINE avant la phase 2"
    )


def test_un_partage_declare_devient_by_design(audit, depot):
    """On DECLARE un partage, on ne le devine pas."""
    racine, carte = depot
    prov, _ = audit.proprietaires(
        racine=racine, bases=("app",), carte=carte,
        partages_declares={"CLE_PARTAGEE_ENTRE_ORGANES": "bus commun a tous les organes"},
    )
    fiche = prov["CLE_PARTAGEE_ENTRE_ORGANES"]
    assert fiche["verdict"] == "SHARED_BY_DESIGN"
    assert fiche["contrat"], "un partage by-design doit porter SA RAISON"


def test_un_module_hors_carte_rend_owner_unknown(audit, depot):
    """Ce n'est PAS 'sans proprietaire' : c'est un module non classe. Le remede
    est de declarer son organe, pas d'inventer un propietaire."""
    racine, carte = depot
    prov, _ = audit.proprietaires(racine=racine, bases=("app",), carte=carte)
    fiche = prov["CLE_SANS_ORGANE_CONNU"]
    assert fiche["verdict"] == "OWNER_UNKNOWN"
    assert fiche["sites_sans_organe"], "il doit NOMMER les modules non classes"


# -------------------------------------------------- l'instrument qui echoue

def test_une_carte_illisible_ne_fabrique_pas_des_orphelins(audit, depot, tmp_path):
    """L'invariant central du mandat, rendu executable.

    « Tu ne dois plus conclure ABSENT a partir de : ma sonde ne le voit pas. »
    Une carte d'organes absente ou corrompue doit rendre OWNER_UNKNOWN pour
    tout le monde -- et le DIRE dans les stats -- jamais ORPHAN.
    """
    racine, _ = depot
    absente = tmp_path / "carte_qui_n_existe_pas.json"
    prov, stats = audit.proprietaires(racine=racine, bases=("app",), carte=absente)
    assert stats["carte"] != "LUE", "l'instrument doit dire que la carte a manque"
    assert stats["modules_classes"] == 0
    for nom, fiche in prov.items():
        assert fiche["verdict"] == "OWNER_UNKNOWN", (
            "%s classee %r alors que la CARTE est illisible : c'est une panne "
            "d'instrument, pas une absence de proprietaire" % (nom, fiche["verdict"])
        )
    assert not any(f["verdict"] == "ORPHAN" for f in prov.values())


def test_une_carte_corrompue_est_dite_et_non_avalee(audit, depot, tmp_path):
    racine, _ = depot
    pourrie = tmp_path / "carte_pourrie.json"
    pourrie.write_text("{ ceci n est pas du json", encoding="utf-8")
    prov, stats = audit.proprietaires(racine=racine, bases=("app",), carte=pourrie)
    assert "LUE" not in stats["carte"]
    assert all(f["verdict"] == "OWNER_UNKNOWN" for f in prov.values())


def test_la_provenance_nouvre_aucun_coffre(audit, depot, monkeypatch):
    """Elle derive de NOMS, de CHEMINS et d'une carte. Jamais d'une valeur."""
    import importlib

    racine, carte = depot
    secrets = importlib.import_module("nokido_agent.app.forge_secrets")
    touche = []
    for nom in ("_machine_vault", "_wcm", "_dotenv"):
        monkeypatch.setattr(secrets, nom, lambda k, _n=nom: touche.append(_n))
    audit.proprietaires(racine=racine, bases=("app",), carte=carte)
    assert touche == [], "la provenance a interroge %s" % touche


# ------------------------------------------------------- raccord au reel

def test_le_depot_reel_rend_une_matrice_exploitable(audit):
    """Le raccord : une piece juste sur fixture et muette sur le depot ne
    fermerait aucune transition."""
    prov, stats = audit.proprietaires()
    assert stats["modules_classes"] > 100, (
        "la carte d'organes du depot doit etre lue (1755 modules mesures le "
        "2026-09-20) ; sinon l'instrument travaille a l'aveugle"
    )
    assert len(prov) > 50
    verdicts = {f["verdict"] for f in prov.values()}
    assert verdicts <= VERDICTS
    assert "OWNER_PROVEN" in verdicts

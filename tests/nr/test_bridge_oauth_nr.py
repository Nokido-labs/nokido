"""L'autorite OAuth n'est PAS une seconde autorite.

CE QUE CES TESTS DEFENDENT. Le jeton d'acces delivre par le flot OAuth EST une
habilitation du pont : meme signature, memes champs, meme lecture. Si ce fichier
se met un jour a verifier quoi que ce soit lui-meme, il y aura deux
implementations de l'autorisation -- et c'est toujours la plus permissive des deux
qui finit par faire loi.

    flot OAuth  ->  forger_capacite()      <- l'emission du pont, pas une autre
    requete     ->  _lire_capacite()       <- la verification du pont, pas une autre

CE QU'ILS DEFENDENT AUSSI, et qui est moins evident : qu'aucun verdict ne soit mis
en CACHE. Une revocation ne vaut que si elle est relue ; un serveur qui garde en
memoire « ce jeton etait bon » transforme une coupure en delai indetermine.

ENFIN, LE CONSENTEMENT. Un serveur d'autorisation qui accorde a qui demande ne
protege rien : le rempart redeviendrait le transport seul. L'octroi exige donc un
code d'appariement, et son absence interdit toute delivrance -- fail-closed.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import time

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
CHEMIN = RACINE / "tools" / "forge_bridge_oauth.py"
CLEF_FACTICE = "2" * 64


def _source() -> str:
    return CHEMIN.read_text(encoding="utf-8", errors="replace")


@pytest.fixture()
def oauth(monkeypatch):
    if not CHEMIN.exists():
        pytest.fail("%s introuvable" % CHEMIN)
    monkeypatch.setenv("NOKIDO_BRIDGE_CAPABILITY_KEY", CLEF_FACTICE)
    monkeypatch.delenv("NOKIDO_BRIDGE_REVOKED", raising=False)
    spec = importlib.util.spec_from_file_location("forge_bridge_oauth", CHEMIN)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        pytest.fail("le module ne s'importe pas : %s: %s" % (type(exc).__name__, exc))
    return module


def _habilitation(module, **remplace):
    charge = {"sub": "nr", "aud": module.PONT.AUDIENCE, "scope": module.PONT.SCOPE,
              "resource": module.depot_unique(),
              "exp": int(time.time()) + 600,
              "jti": "nr-oauth-%.6f" % time.time(), "replay": "multi"}
    charge.update(remplace)
    return module.PONT.forger_capacite(charge)


# ------------------------------------------- aucune autorite reimplementee

def test_aucune_verification_n_est_reimplementee_ici(oauth):
    """La signature, la liste des depots et l'appel sortant vivent DANS LE PONT."""
    src = _source()
    for motif in ("hmac.new", "DEPOTS_AUTORISES =",
                  "api.github.com", "urlopen", "def _lire_capacite"):
        assert motif not in src, (
            "l'autorite OAuth reimplemente %r : une seconde implementation "
            "divergera, et la plus permissive fera loi" % motif)
    # `hashlib.sha256` : toléré dans `_empreinte` SEULEMENT (2026-09-29) -- l'empreinte de STOCKAGE
    # des renouvellements, qui ne signe ni ne verifie aucune habilitation du pont. Ailleurs dans
    # l'autorite, il signerait une seconde implementation de la verification : refus.
    import ast
    arbre = ast.parse(src)
    toleres = set()
    for f in ast.walk(arbre):
        if isinstance(f, ast.FunctionDef) and f.name == "_empreinte":
            toleres |= {id(n) for n in ast.walk(f)}
    hors = [n.lineno for n in ast.walk(arbre)
            if isinstance(n, ast.Attribute) and n.attr == "sha256"
            and getattr(n.value, "id", "") == "hashlib" and id(n) not in toleres]
    assert not hors, ("l'autorite OAuth hache hors de `_empreinte` (lignes %s) : une seconde "
                      "implementation de la verification divergera" % hors)


def test_la_verification_delegue_au_pont(oauth, monkeypatch):
    """`verifier` ne doit rien trancher : il transmet et rend le verdict du pont."""
    vus = []

    def _espion(jeton):
        vus.append(jeton)
        return {"sub": "x"}, None

    monkeypatch.setattr(oauth.PONT, "_lire_capacite", _espion)
    charge, motif = oauth.verifier("un-jeton")
    assert vus == ["un-jeton"], "le jeton n'a pas ete transmis au pont"
    assert charge == {"sub": "x"} and motif is None


def test_le_depot_vient_de_la_liste_blanche_du_pont(oauth):
    assert oauth.depot_unique() in oauth.PONT.DEPOTS_AUTORISES
    assert "Nokido-labs" not in _source(), (
        "le nom du depot est ecrit en dur : deux listes finiraient par diverger")


# ------------------------------------------------------ consentement obligatoire

def test_sans_code_d_appariement_aucune_delivrance(oauth, monkeypatch):
    """Fail-closed. Un serveur d'autorisation sans consentement accorderait a
    quiconque atteint le transport -- exactement ce qu'on cherche a quitter."""
    monkeypatch.delenv("NOKIDO_BRIDGE_OAUTH_APPARIEMENT", raising=False)
    assert oauth.code_d_appariement() == ""
    src = _source()
    assert "compare_digest" in src, (
        "le code d'appariement doit etre compare en temps constant")
    assert "not attendu or not" in src, (
        "un code d'appariement absent doit interdire l'octroi, pas l'autoriser")


def test_le_consentement_est_une_etape_du_flot(oauth):
    """`authorize` ne doit JAMAIS rendre directement l'URL du client."""
    src = _source()
    assert "/consentement?demande=" in src, (
        "l'autorisation ne passe pas par une page de consentement")
    assert "poser_consentement" in src


# --------------------------------------------- ce que le jeton doit etre

def test_le_jeton_delivre_est_une_habilitation_du_pont(oauth):
    """Pas un jeton maison : l'objet meme que `traiter()` sait lire."""
    src = _source()
    assert "PONT.forger_capacite(" in src, (
        "l'autorite forge son propre jeton au lieu d'emettre une habilitation")
    jeton = _habilitation(oauth)
    charge, motif = oauth.verifier(jeton)
    assert charge is not None, "le pont refuse une habilitation qu'il a forgee : %s" % motif


def test_le_jeton_est_REJOUABLE_pendant_sa_duree_de_vie(oauth):
    """Un jeton d'acces sert plusieurs fois -- c'est la definition.

    En `single`, l'identifiant d'usage serait consomme par la verification du
    transport et l'appel metier suivant serait refuse : une panne qui ressemble a
    une expiration.
    """
    assert '"replay": "multi"' in _source(), (
        "l'autorite delivre un jeton a usage unique : le second appel serait refuse")
    jeton = _habilitation(oauth, replay="multi")
    for tour in (1, 2, 3):
        charge, motif = oauth.verifier(jeton)
        assert charge is not None, "refuse au tour %d : %s" % (tour, motif)


def test_un_jeton_a_usage_unique_ne_passe_PAS_deux_fois(oauth):
    """Contre-epreuve : sans elle, le test precedent ne prouverait rien -- il
    pourrait passer sur un pont qui ne verifie pas le rejeu du tout."""
    jeton = _habilitation(oauth, replay="single")
    premier, _ = oauth.verifier(jeton)
    second, motif = oauth.verifier(jeton)
    assert premier is not None, "le premier usage aurait du passer"
    assert second is None and "utilis" in (motif or ""), (
        "le pont ne distingue plus usage unique et cle durable")


# ------------------------------------------------------------- revocation

def test_la_revocation_passe_par_le_registre_EXISTANT(oauth):
    src = _source()
    assert "NOKIDO_BRIDGE_REVOKED" in src, (
        "la revocation n'ecrit pas dans le registre du pont")
    for second_registre in ("sqlite3", "open(", "json.dump", "pathlib.Path("):
        assert second_registre not in src.split("def revoquer")[1].split("def ")[0], \
            "la revocation tient un second registre (%r)" % second_registre


def test_la_revocation_change_le_verdict_AU_PROCHAIN_APPEL(oauth):
    """Le coeur de l'affaire : aucun verdict n'est mis en cache.

    On revoque ENTRE deux lectures du meme jeton, et le second verdict doit
    differer du premier. Un serveur qui memorise « ce jeton etait bon » rendrait
    la coupure inoperante sans que rien ne le signale.
    """
    jeton = _habilitation(oauth)
    charge, _ = oauth.verifier(jeton)
    assert charge is not None, "le jeton devait d'abord etre valide"
    oauth.revoquer(charge["jti"])
    apres, motif = oauth.verifier(jeton)
    assert apres is None, "le jeton revoque est toujours accepte"
    assert "revoqu" in (motif or ""), "motif inattendu : %r" % motif


def test_revoquer_une_valeur_vide_ne_casse_rien(oauth, monkeypatch):
    """Un garde qui leve sur une entree vide se fait retirer du chemin."""
    monkeypatch.setenv("NOKIDO_BRIDGE_REVOKED", "deja-la")
    oauth.revoquer("")
    oauth.revoquer(None)
    import os
    assert os.environ["NOKIDO_BRIDGE_REVOKED"] == "deja-la"


# --------------------------------------------------------------- reglages

def test_les_reglages_activent_inscription_ET_revocation(oauth):
    """Une revocation qu'on ne peut pas DEMANDER n'est pas une revocation."""
    reglages = oauth.reglages("http://127.0.0.1:8791")
    assert reglages.client_registration_options.enabled is True, (
        "sans enregistrement dynamique, le client du relais ne peut pas s'inscrire")
    assert reglages.revocation_options.enabled is True, (
        "le point de revocation est absent : la coupure serait indemandable")
    assert list(reglages.required_scopes or []) == [oauth.PONT.SCOPE]


def test_la_base_publique_suit_les_reglages(oauth):
    """Le relais REECRIT les URL vers son ingress : la base doit etre posee au
    demarrage, pas figee a l'import."""
    oauth.reglages("http://127.0.0.1:9999")
    assert oauth.BASE_PUBLIQUE[0] == "http://127.0.0.1:9999"
    oauth.reglages("http://127.0.0.1:8791/")
    assert oauth.BASE_PUBLIQUE[0] == "http://127.0.0.1:8791", (
        "la barre finale n'est pas retiree : les URL publiees seraient doublees")


def test_le_module_declare_son_organe(oauth):
    assert re.search(r"^__FORGE_COLOR__\s*=", _source()[:12000], re.M), \
        "declaration d'organe absente de la fenetre lue par le census"

"""La passerelle M2M n'ajoute NI autorite NI validateur.

CE QUE CES TESTS DEFENDENT. Un tiers peut desormais lire le bus inter-agents et y
emettre. Trois choses doivent rester vraies quoi qu'il arrive :

    1. l'EMETTEUR vient de l'habilitation, jamais des arguments ;
    2. l'autorisation est celle du pont (`lire_capacite`), pas une copie ;
    3. la validation est celle du protocole (`validate`), pas une copie.

Le premier est le plus important. Un bus ou l'on choisit son identite
n'authentifie personne : un message signe « CLAUDE » par un tiers vaut pire que
pas de message du tout, parce qu'il sera cru. Les deux autres protegent contre la
derive lente -- une seconde implementation finit toujours par diverger, et c'est
la plus permissive qui fait loi.

ECRITS APRES le module et le banc, mais ils ne repetent pas le banc : celui-ci
prouve que la chaine marche UNE fois, ceux-ci empechent qu'elle cesse de marcher.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import time

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
CHEMIN = RACINE / "tools" / "forge_m2m_bridge.py"
CLEF_FACTICE = "3" * 64


def _source() -> str:
    return CHEMIN.read_text(encoding="utf-8", errors="replace")


@pytest.fixture()
def m2m(monkeypatch):
    if not CHEMIN.exists():
        pytest.fail("%s introuvable" % CHEMIN)
    monkeypatch.setenv("NOKIDO_BRIDGE_CAPABILITY_KEY", CLEF_FACTICE)
    monkeypatch.delenv("NOKIDO_BRIDGE_REVOKED", raising=False)
    spec = importlib.util.spec_from_file_location("forge_m2m_bridge", CHEMIN)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        pytest.fail("le module ne s'importe pas : %s: %s" % (type(exc).__name__, exc))
    return module


def _habilitation(m2m, portee=None, **remplace):
    charge = {"sub": "CHATGPT", "aud": m2m.AUDIENCE,
              "scope": portee or m2m.PORTEE_EMISSION,
              "resource": "nokido:m2m", "exp": int(time.time()) + 600,
              "jti": "nr-m2m-%.6f" % time.time(), "replay": "multi"}
    charge.update(remplace)
    return m2m.PONT.forger_capacite(charge)


# ------------------------------------------------ aucune autorite reimplementee

def test_la_verification_est_celle_du_pont(m2m):
    """Pas de sceau, pas d'expiration, pas de revocation recalcules ici."""
    src = _source()
    for motif in ("hmac", "compare_digest", "hashlib", "def lire_capacite",
                  "def _lire_capacite"):
        assert motif not in src, (
            "la passerelle M2M reimplemente %r : deux verifications divergeront, "
            "et la plus permissive fera loi" % motif)
    assert "PONT.lire_capacite(" in src, (
        "l'autorisation ne delegue pas au pont")


def test_la_validation_est_celle_du_protocole(m2m):
    """Le dictionnaire d'intents est une source unique, pas une liste locale."""
    src = _source()
    assert "PROTOCOLE.validate(" in src, (
        "les messages ne sont pas valides par le protocole du corps")
    for motif in ('"COLLAB_PING"', "INTENTS =", "intents = {"):
        assert motif not in src, (
            "la passerelle porte sa propre liste d'intents (%r) : elle acceptera "
            "un jour ce que le protocole refuse" % motif)


# --------------------------------------------------- l'emetteur n'est pas choisi

def test_l_emetteur_vient_de_l_habilitation(m2m):
    assert m2m._sujet({"sub": "chatgpt"}) == "CHATGPT"
    assert m2m._sujet({"sub": "  gemini  "}) == "GEMINI"
    assert m2m._sujet({}) == "INCONNU", (
        "une habilitation sans sujet doit donner un emetteur NOMME inconnu, "
        "jamais une chaine vide qui passerait pour n'importe qui")


def test_un_emetteur_declare_en_argument_est_IGNORE(m2m, monkeypatch):
    """LE test de ce fichier.

    On tente l'usurpation par tous les noms de champ plausibles. Le message doit
    partir au nom du sujet de l'habilitation, quoi qu'il arrive.
    """
    vus = []

    def _espion(operation, args, capacite):  # pragma: no cover - remplace
        return True, {}

    monkeypatch.setattr(m2m, "chemin_du_bus",
                        lambda: pathlib.Path("/introuvable/m2m.db"))
    porteuse = _habilitation(m2m)
    for usurpation in ({"de": "CLAUDE"}, {"from_agent": "CLAUDE"},
                       {"sub": "CLAUDE"}, {"emetteur": "CLAUDE"}):
        args = {"destinataire": "CLAUDE",
                "message": {"intent": "COLLAB_PING", "pointer_ref": "bb:nr",
                            "proposed_action": "x", "confidence": 0.5}}
        args.update(usurpation)
        ok, motif = m2m.traiter("m2m_notifier", args, porteuse)
        # L'ecriture echoue (chemin introuvable), mais le refus ne doit JAMAIS
        # venir d'une confusion d'emetteur : on verifie qu'on est alle jusqu'a
        # l'ecriture, donc que l'usurpation n'a pas ete prise en compte.
        assert ok is False
        assert "ecriture sur le bus" in motif, (
            "l'argument %r a change le chemin suivi : %s" % (usurpation, motif))
    assert vus == []


# ----------------------------------------------------------- portees distinctes

def test_la_portee_lecture_ne_peut_pas_emettre(m2m):
    lecture = _habilitation(m2m, portee=m2m.PORTEE_LECTURE)
    ok, motif = m2m.traiter("m2m_notifier",
                            {"destinataire": "CLAUDE",
                             "message": {"intent": "COLLAB_PING",
                                         "pointer_ref": "bb:nr"}}, lecture)
    assert ok is False and "portee" in motif.lower(), (
        "une habilitation de lecture a pu emettre : les deux portees ne servent "
        "alors a rien")


def test_la_portee_emission_peut_lire(m2m):
    """Ecrire sans pouvoir relire ce qu'on ecrit n'aurait pas de sens."""
    emission = _habilitation(m2m, portee=m2m.PORTEE_EMISSION)
    ok, _ = m2m.traiter("m2m_intents", {}, emission)
    assert ok is True


def test_une_habilitation_GITHUB_n_ouvre_pas_le_bus(m2m):
    """Deux fenetres, deux clefs. Sinon la plus large emporte l'autre."""
    github = m2m.PONT.forger_capacite({
        "sub": "CHATGPT", "aud": m2m.PONT.AUDIENCE, "scope": m2m.PONT.SCOPE,
        "resource": sorted(m2m.PONT.DEPOTS_AUTORISES)[0],
        "exp": int(time.time()) + 600, "jti": "nr-gh-%.6f" % time.time(),
        "replay": "multi"})
    ok, motif = m2m.traiter("m2m_intents", {}, github)
    assert ok is False and "audience" in motif.lower()


def test_une_habilitation_M2M_n_ouvre_pas_un_depot(m2m):
    """La reciproque, sans laquelle le test precedent ne prouve qu'une moitie."""
    porteuse = _habilitation(m2m)
    ok, motif = m2m.PONT.traiter("repo_info",
                                 {"repo": sorted(m2m.PONT.DEPOTS_AUTORISES)[0]},
                                 porteuse)
    assert ok is False, "une habilitation M2M a ouvert un depot GitHub"


# --------------------------------------------------------- listes et plafonds

def test_les_destinataires_sont_une_liste_BLANCHE(m2m, monkeypatch):
    monkeypatch.delenv("NOKIDO_M2M_DESTINATAIRES", raising=False)
    autorises = m2m.agents_autorises()
    assert "GEMINI" in autorises and "CLAUDE" in autorises
    porteuse = _habilitation(m2m)
    ok, motif = m2m.traiter("m2m_notifier",
                            {"destinataire": "INTRUS",
                             "message": {"intent": "COLLAB_PING",
                                         "pointer_ref": "bb:nr"}}, porteuse)
    assert ok is False and "liste autorisee" in motif, (
        "un destinataire inconnu recevrait un message que personne ne draine")


def test_le_debit_est_plafonne(m2m, monkeypatch):
    """Un emetteur externe qui inonde le bus est une panne pour TOUS les agents."""
    monkeypatch.setenv("NOKIDO_M2M_PLAFOND_HORAIRE", "3")
    m2m._EMISSIONS.clear()
    assert m2m.plafond_par_heure() == 3
    for tour in range(3):
        assert m2m._debit_ok("CHATGPT") is True, "refus au tour %d" % tour
    assert m2m._debit_ok("CHATGPT") is False, "le plafond ne mord pas"
    assert m2m._debit_ok("GEMINI") is True, (
        "le plafond doit etre PAR SUJET : un emetteur ne doit pas bloquer "
        "les autres")


def test_un_plafond_illisible_ne_desarme_pas_le_garde(m2m, monkeypatch):
    monkeypatch.setenv("NOKIDO_M2M_PLAFOND_HORAIRE", "beaucoup")
    assert m2m.plafond_par_heure() == 20
    monkeypatch.setenv("NOKIDO_M2M_PLAFOND_HORAIRE", "0")
    assert m2m.plafond_par_heure() >= 1, (
        "un plafond a zero bloquerait tout : le garde deviendrait une panne")


# --------------------------------------------------------------- surface

def test_la_surface_est_exactement_trois_operations(m2m):
    assert set(m2m.OPERATIONS) == {"m2m_intents", "m2m_inbox", "m2m_notifier"}
    assert m2m.OPERATIONS_EMISSION == frozenset({"m2m_notifier"})


def test_aucune_operation_d_assignation_ni_d_execution(m2m):
    """La passerelle ne cree pas d'agent adressable et n'execute rien."""
    src = _source()
    for interdit in ("task_assign", "subprocess", "os.system", "eval(",
                     "run_job", "governed_edit"):
        assert interdit not in src, (
            "la passerelle porte %r : elle sortirait de son perimetre" % interdit)


def test_une_operation_inconnue_n_atteint_pas_l_autorisation(m2m, monkeypatch):
    vus = []
    monkeypatch.setattr(m2m.PONT, "lire_capacite",
                        lambda *a, **k: (vus.append(a), (None, "x"))[1])
    for nom in ("run", "m2m_supprimer", "", "__import__"):
        ok, _ = m2m.traiter(nom, {}, "peu importe")
        assert ok is False
    assert vus == [], "un nom invente a atteint la couche d'autorisation"


def test_le_module_declare_son_organe(m2m):
    assert re.search(r"^__FORGE_COLOR__\s*=", _source()[:12000], re.M), \
        "declaration d'organe absente de la fenetre lue par le census"

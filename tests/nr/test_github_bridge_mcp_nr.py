"""L'adaptateur MCP n'est qu'un TRANSPORT : il n'ajoute aucune autorite.

POURQUOI IL EXISTE. Le Secure MCP Tunnel relaie un serveur MCP local vers un
service d'inference par une connexion SORTANTE : aucun port n'est ouvert, aucune
URL publique n'est creee. Mais il transporte du MCP, et la passerelle parle REST.
Cet adaptateur comble cet ecart -- et RIEN d'autre.

L'INVARIANT, et la seule chose que ces tests defendent vraiment :

    outil MCP  ->  forge_github_bridge.traiter()

jamais

    outil MCP  ->  nouvelle verification  ->  traiter()

Une seconde implementation de l'autorisation finirait par diverger de la premiere,
et c'est la plus permissive des deux qui ferait loi. L'adaptateur ne valide donc
rien : il traduit un appel et rend une reponse.

CE QUE LE TRANSPORT CHANGE, et qu'il faut nommer. En stdio il n'y a pas d'en-tete
`Authorization` : le client ne PEUT pas presenter d'habilitation. Celle-ci passe
donc du statut de jeton porte par l'appelant a celui de BORNE DU PROCESSUS, lue
dans son environnement au lancement -- l'authentification de l'appelant etant
assuree par le tunnel lui-meme. La borne (depot, portee, expiration, revocation)
reste integralement verifiee a chaque appel, par `traiter()`.

EN HTTP, CE CONTRAT S'INVERSE, ET UN NR DE CE FICHIER A DU ETRE RETOURNE AVEC LUI.
Mesure du 2026-09-14 : le relais TRANSMET l'en-tete `Authorization` du client au
serveur MCP local. L'appelant peut donc a nouveau presenter son habilitation, et
c'est desormais la seule qui vaille sur ce transport -- la borne du processus n'y
est PAS un repli, sinon un appel sans en-tete emprunterait l'habilitation de
l'operateur et le serveur n'authentifierait personne tout en paraissant le faire.

Le NR qui EXIGEAIT un parametre `habilitation` dans la signature de l'outil est
donc devenu faux, et il est remplace par son contraire : ce parametre doit avoir
DISPARU du schema annonce. Un jeton qu'un client peut poser dans le corps de
l'appel n'est plus porte par le transport -- c'est une seconde grammaire
d'authentification, et la plus permissive des deux ferait loi.

ECRITS AVANT L'ADAPTATEUR : au premier passage ils echouent a l'import.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
CHEMIN = RACINE / "tools" / "forge_github_bridge_mcp.py"
CLEF_FACTICE = "1" * 64

OPERATIONS_ATTENDUES = {"repo_info", "branch_head", "commit_info", "compare",
                        "read_file"}


def _source() -> str:
    return CHEMIN.read_text(encoding="utf-8", errors="replace")


@pytest.fixture()
def adaptateur(monkeypatch):
    """Le module reel, charge par son CHEMIN, avec une borne d'habilitation posee."""
    if not CHEMIN.exists():
        pytest.fail("%s introuvable -- l'adaptateur doit exister" % CHEMIN)
    monkeypatch.setenv("NOKIDO_BRIDGE_CAPABILITY_KEY", CLEF_FACTICE)
    spec = importlib.util.spec_from_file_location("forge_github_bridge_mcp", CHEMIN)
    if spec is None or spec.loader is None:
        pytest.fail("%s illisible par l'importeur" % CHEMIN)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        pytest.fail("l'adaptateur ne s'importe pas : %s: %s"
                    % (type(exc).__name__, exc))
    # Depot d'ESSAI (2026-09-30) : les tests du mecanisme ne suivent pas le nom du
    # depot reel, verrouille a part (test_la_description_nomme_le_depot_reel).
    monkeypatch.setattr(module.PONT, "DEPOTS_AUTORISES",
                        frozenset({"Nokido-labs/nokido"}))
    # une habilitation de processus valide, signee par la passerelle elle-meme
    import time as _t
    monkeypatch.setenv("NOKIDO_BRIDGE_HABILITATION", module.PONT.forger_capacite({
        "sub": "tunnel-essai", "aud": module.PONT.AUDIENCE,
        "scope": module.PONT.SCOPE, "resource": "Nokido-labs/nokido",
        "exp": int(_t.time()) + 600, "jti": "nr-mcp", "replay": "multi"}))
    return module


# ------------------------------------------------------------ surface exposee

def test_exactement_cinq_outils_sont_exposes(adaptateur):
    noms = set(adaptateur.outils_exposes())
    assert noms == OPERATIONS_ATTENDUES, (
        "surface MCP = %s, attendu %s : tout ecart doit etre un choix explicite"
        % (sorted(noms), sorted(OPERATIONS_ATTENDUES)))


def test_la_surface_MCP_est_celle_de_la_passerelle(adaptateur):
    """Deux listes qui divergent : un outil annonce que personne n'execute."""
    assert set(adaptateur.outils_exposes()) == set(adaptateur.PONT.OPERATIONS), (
        "l'adaptateur annonce autre chose que ce que la passerelle execute")


def test_aucun_outil_d_ecriture_ni_d_execution(adaptateur):
    interdits = ("run", "governed_edit", "oracle_python_repl", "ps_clm", "shell",
                 "task", "skill")
    for nom in adaptateur.outils_exposes():
        assert nom not in interdits, "outil interdit expose : %s" % nom
        assert not any(i in nom.lower()
                       for i in ("write", "creat", "delet", "updat", "push")), \
            "%s ressemble a une mutation" % nom


# ------------------------------- aucune autorite ajoutee, aucune dupliquee

def test_chaque_outil_passe_par_traiter(adaptateur, monkeypatch):
    """L'unique porte. Si un outil court-circuite `traiter`, il court-circuite
    l'habilitation, le depot et la validation des parametres d'un seul coup."""
    vus = []

    def _espion(operation, args, capacite):
        vus.append((operation, dict(args)))
        return True, {"ok": True}

    monkeypatch.setattr(adaptateur.PONT, "traiter", _espion)
    # Une habilitation est presentee : depuis que l'authentification de l'appelant
    # est exigee par defaut, un appel nu serait refuse AVANT d'atteindre `traiter`
    # -- et ce test-ci verifie la delegation, pas le controle d'acces.
    porteuse = _habilitation(adaptateur.PONT)
    for nom in sorted(OPERATIONS_ATTENDUES):
        vus.clear()
        adaptateur.appeler(nom, {"repo": "Nokido-labs/nokido"}, porteuse)
        assert len(vus) == 1, "%s n'a pas appele traiter() exactement une fois" % nom
        assert vus[0][0] == nom, "%s a appele traiter() pour %r" % (nom, vus[0][0])


def test_l_adaptateur_ne_reimplemente_aucune_verification(adaptateur):
    """Il ne doit y avoir qu'UNE implementation de l'autorisation, dans le pont."""
    src = _source()
    for motif in ("hmac", "compare_digest", "DEPOTS_AUTORISES =", "def _lire_capacite",
                  "urlopen", "api.github.com"):
        assert motif not in src, (
            "l'adaptateur reimplemente une verification ou un appel (%r) : une "
            "seconde implementation divergera, et la plus permissive fera loi"
            % motif)


def test_un_outil_inconnu_est_refuse_sans_atteindre_le_pont(adaptateur, monkeypatch):
    vus = []
    monkeypatch.setattr(adaptateur.PONT, "traiter",
                        lambda *a, **k: (vus.append(a), (True, {}))[1])
    for nom in ("run", "governed_edit", "github", "__import__", ""):
        ok, _ = adaptateur.appeler(nom, {"repo": "Nokido-labs/nokido"})
        assert ok is False, "outil inconnu accepte : %r" % nom
    assert vus == [], "un outil inconnu a tout de meme atteint la passerelle"


# ------------------------------------------------ frontiere du processus

def test_l_adaptateur_n_importe_pas_le_hub(adaptateur):
    src = _source()
    for interdit in ("forge_mcp_registry", "nokido_hub", "forge_videur",
                     "forge_secrets", "forge_auth_tokens", "subprocess"):
        assert interdit not in src, (
            "l'adaptateur reference %s : il sortirait de son perimetre" % interdit)


def test_le_depot_reste_celui_de_la_liste_blanche(adaptateur):
    """L'adaptateur n'elargit pas l'allowlist : il n'en porte pas."""
    assert adaptateur.PONT.DEPOTS_AUTORISES == frozenset({"Nokido-labs/nokido"})
    assert "frozenset({" not in _source(), "l'adaptateur porte sa propre liste"


def test_la_description_nomme_le_depot_de_la_liste_blanche(adaptateur, monkeypatch):
    """2026-09-30 : c'est par la description MCP que ChatGPT apprend la valeur de
    `repo`. Elle la LIT dans la liste blanche du pont : un renommage s'y propage
    sans configuration tenue a la main cote client."""
    monkeypatch.setattr(adaptateur.PONT, "DEPOTS_AUTORISES",
                        frozenset({"Nokido-labs/nokido-private"}))
    for nom in adaptateur.outils_exposes():
        texte = adaptateur.description_outil(nom)
        assert "Nokido-labs/nokido-private" in texte, texte
        assert "ecriture" in texte.lower()


def test_l_habilitation_vient_du_processus_pas_de_l_appelant(adaptateur):
    """En stdio, l'appelant ne peut presenter aucun en-tete : la borne est celle du
    processus. Ce test fige ce contrat pour qu'il ne devienne pas, en silence,
    « aucune borne du tout »."""
    src = _source()
    assert "NOKIDO_BRIDGE_HABILITATION" in src, (
        "l'adaptateur doit lire une habilitation de processus, nommee")
    assert adaptateur.habilitation_du_processus.__doc__, \
        "le contrat doit etre documente la ou il est lu"


def test_sans_habilitation_de_processus_rien_ne_passe(adaptateur, monkeypatch):
    """Fail-closed : pas de borne posee = aucun appel, jamais un appel sans borne."""
    monkeypatch.delenv("NOKIDO_BRIDGE_HABILITATION", raising=False)
    vus = []
    monkeypatch.setattr(adaptateur.PONT, "traiter",
                        lambda *a, **k: (vus.append(a), (True, {}))[1])
    ok, motif = adaptateur.appeler("repo_info", {"repo": "Nokido-labs/nokido"})
    assert ok is False, "un appel est passe sans habilitation de processus"
    assert "habilitation" in motif.lower()
    assert vus == []


# ------------- l'authentification du TRANSPORT ne doit pas etre la seule

def _habilitation(pont, **remplace):
    import time as _t
    charge = {"sub": "appelant-essai", "aud": pont.AUDIENCE, "scope": pont.SCOPE,
              "resource": "Nokido-labs/nokido", "exp": int(_t.time()) + 600,
              "jti": "nr-appelant-%.6f" % _t.time(), "replay": "multi"}
    charge.update(remplace)
    return pont.forger_capacite(charge)


def test_PAR_DEFAUT_l_appelant_doit_s_authentifier(adaptateur, monkeypatch):
    """Le defaut est l'EXIGENCE, pas la permissivite.

    Un serveur qui ne demande rien n'authentifie personne : sans ce defaut,
    quiconque atteint le tunnel appelle les cinq outils. Le transport
    authentifierait SEUL, et une confiance unique n'est pas une defense.
    """
    monkeypatch.delenv("NOKIDO_BRIDGE_EXIGER_HABILITATION", raising=False)
    assert adaptateur.habilitation_appelant_exigee() is True
    vus = []
    monkeypatch.setattr(adaptateur.PONT, "traiter",
                        lambda *a, **k: (vus.append(a), (True, {}))[1])
    ok, motif = adaptateur.appeler("repo_info", {"repo": "Nokido-labs/nokido"})
    assert ok is False, "sans habilitation, l'appel est passe alors qu'aucune "
    assert "exig" in motif.lower()
    assert vus == [], "le refus a tout de meme atteint la passerelle"


def test_le_mode_EXIGE_refuse_un_appel_sans_habilitation(adaptateur, monkeypatch):
    """Sans ce mode, le transport authentifie SEUL : quiconque atteint le tunnel
    peut appeler. Une confiance unique n'est pas une defense en profondeur."""
    monkeypatch.setenv("NOKIDO_BRIDGE_EXIGER_HABILITATION", "1")
    vus = []
    monkeypatch.setattr(adaptateur.PONT, "traiter",
                        lambda *a, **k: (vus.append(a), (True, {}))[1])
    ok, motif = adaptateur.appeler("repo_info", {"repo": "Nokido-labs/nokido"})
    assert ok is False, "un appel sans habilitation est passe malgre le mode exige"
    assert "exig" in motif.lower()
    assert vus == [], "le refus a tout de meme atteint la passerelle"


def test_le_mode_EXIGE_accepte_une_habilitation_presentee(adaptateur, monkeypatch):
    monkeypatch.setenv("NOKIDO_BRIDGE_EXIGER_HABILITATION", "1")
    vus = []

    def _espion(operation, args, capacite):
        vus.append(capacite)
        return True, {"ok": True}

    monkeypatch.setattr(adaptateur.PONT, "traiter", _espion)
    presentee = _habilitation(adaptateur.PONT)
    ok, _ = adaptateur.appeler("repo_info", {"repo": "Nokido-labs/nokido"}, presentee)
    assert ok is True
    assert vus == [presentee], (
        "c'est l'habilitation de l'APPELANT qui doit etre verifiee, pas celle du "
        "processus, quand l'appelant en presente une")


def test_une_habilitation_d_appelant_INVALIDE_est_refusee(adaptateur, monkeypatch):
    """Le mode n'est pas un simple test de presence : la valeur est VERIFIEE, et
    par la meme fonction du pont -- il n'y a qu'une implementation."""
    monkeypatch.setenv("NOKIDO_BRIDGE_EXIGER_HABILITATION", "1")
    for mauvaise in ("n-importe-quoi", "a.b", _habilitation(adaptateur.PONT,
                                                            aud="autre-service")):
        ok, _ = adaptateur.appeler("repo_info", {"repo": "Nokido-labs/nokido"},
                                   mauvaise)
        assert ok is False, "habilitation invalide acceptee : %r" % mauvaise[:24]


def test_le_controle_ne_se_DESARME_pas_par_accident(adaptateur, monkeypatch):
    """Une faute de frappe ne doit pas ouvrir une porte.

    Seule la valeur `0`, ecrite exactement, desarme. Ni l'absence de variable, ni
    une chaine vide, ni `false`, ni `non` -- toutes ces formes laissent le controle
    ARME. C'est la difference entre une liste blanche et une liste noire, appliquee
    a un interrupteur.
    """
    monkeypatch.delenv("NOKIDO_BRIDGE_EXIGER_HABILITATION", raising=False)
    assert adaptateur.habilitation_appelant_exigee() is True, "absent = arme"
    for valeur in ("", "1", "oui", "true", "on", "2", "00", "0 ", "non", "false"):
        monkeypatch.setenv("NOKIDO_BRIDGE_EXIGER_HABILITATION", valeur)
        attendu = valeur.strip() != "0"
        assert adaptateur.habilitation_appelant_exigee() is attendu, (
            "%r desarme le controle alors que seul '0' le doit" % valeur)
    monkeypatch.setenv("NOKIDO_BRIDGE_EXIGER_HABILITATION", "0")
    assert adaptateur.habilitation_appelant_exigee() is False, \
        "la desactivation explicite doit rester possible pour un diagnostic local"


# ------------------------------------------- transport HTTP : l'en-tete fait foi

def test_l_habilitation_n_est_plus_un_parametre_d_outil(adaptateur):
    """Le contraire du NR d'avant, et c'est voulu.

    Un parametre d'habilitation apparait dans le schema annonce au client, qui peut
    donc le renseigner lui-meme. L'habilitation cesse alors d'etre portee par le
    transport : n'importe quel appel peut en fabriquer une dans son corps. On la
    lit desormais dans l'en-tete, et nulle part ailleurs.
    """
    src = _source()
    assert "habilitation: str = \"\"" not in src, (
        "l'outil expose encore un parametre d'habilitation : un client pourrait le "
        "poser lui-meme, et le transport n'authentifierait plus rien")
    assert "entete_autorisation_courante" in src, (
        "l'adaptateur ne lit pas l'en-tete d'autorisation de la requete en cours")


def test_le_schema_annonce_ne_porte_aucun_champ_d_habilitation(adaptateur):
    """Le chemin REEL : ce que le client VOIT, pas ce que la source suggere.

    La coroutine est lancee par `asyncio.run` plutot que par un marqueur de
    plugin : la CI tourne avec le chargement automatique des greffons DESACTIVE,
    et un test marque `anyio` y echoue en disant que le langage ne sait pas
    executer une fonction asynchrone. Le marqueur faisait donc dependre un NR
    d'un greffon absent -- mesure du 2026-09-14, 2 echecs sur la suite pure.
    """
    import asyncio

    serveur = adaptateur.construire_serveur()
    champs = set()
    for outil in asyncio.run(serveur.list_tools()):
        champs |= set(((getattr(outil, "inputSchema", None) or {})
                       .get("properties") or {}))
    assert "habilitation" not in champs, (
        "le schema annonce porte un champ d'habilitation : %s" % sorted(champs))


def test_seul_le_schema_Bearer_est_une_habilitation(adaptateur):
    """On ne devine pas ce qu'un client a voulu dire.

    Accepter `Basic`, ou un jeton nu, « parce que c'est probablement ca »
    fabriquerait une seconde grammaire d'authentification a cote de la premiere.
    """
    lire = adaptateur.habilitation_de_l_entete
    assert lire("Bearer abc") == "abc"
    assert lire("bearer abc") == "abc", "le schema est insensible a la casse (RFC)"
    assert lire("  Bearer   abc  ") == "abc"
    for refuse in ("", "   ", "abc", "Basic abc", "Bearer", "Token abc",
                   "Bearer\tabc extra"):
        rendu = lire(refuse)
        assert rendu in ("", "abc extra"), (
            "%r a produit une habilitation : %r" % (refuse, rendu))
    assert lire("Basic abc") == "", "un schema inconnu n'est pas une habilitation"


def test_hors_requete_HTTP_l_entete_vaut_None_et_non_chaine_vide(adaptateur):
    """TROIS ETATS, jamais deux.

    `None` (pas d'en-tetes du tout) et `""` (en-tete absent) ne sont pas la meme
    chose : confondre les deux ferait retomber un appel HTTP non authentifie sur la
    borne du processus, c'est-a-dire ouvrir la porte en croyant la fermer.
    """
    assert adaptateur.entete_autorisation_courante() is None, (
        "hors requete HTTP, l'en-tete doit valoir None -- pas une chaine vide")


def test_en_HTTP_aucun_repli_sur_la_borne_du_processus(adaptateur, monkeypatch):
    """LE test de ce transport, et il est discriminant.

    Une borne de processus VALIDE est posee. Si `repli_processus` etait ignore, un
    appel sans habilitation d'appelant passerait quand meme -- en empruntant
    l'habilitation de l'operateur. Le controle d'exigence est volontairement
    DESARME ici pour que le refus ne puisse venir que du non-repli.
    """
    monkeypatch.setenv("NOKIDO_BRIDGE_EXIGER_HABILITATION", "0")
    vus = []

    def _espion(operation, args, capacite):
        vus.append(capacite)
        return True, {"ok": True}

    monkeypatch.setattr(adaptateur.PONT, "traiter", _espion)

    ok, motif = adaptateur.appeler("repo_info", {"repo": "Nokido-labs/nokido"},
                                   "", repli_processus=False)
    assert ok is False, (
        "un appel HTTP sans en-tete a emprunte l'habilitation du processus")
    assert "habilitation" in motif.lower()
    assert vus == [], "le refus a tout de meme atteint la passerelle"

    # Contre-epreuve : en stdio, ce meme appel DOIT passer par la borne.
    ok, _ = adaptateur.appeler("repo_info", {"repo": "Nokido-labs/nokido"})
    assert ok is True, (
        "en stdio la borne du processus reste la seule habilitation possible : "
        "la refuser rendrait ce transport inutilisable")
    assert len(vus) == 1


def test_l_adresse_d_ecoute_est_le_loopback_ET_n_est_pas_une_option(adaptateur):
    """Un serveur qui PEUT s'ouvrir sur l'exterieur finit par s'y ouvrir.

    L'hote n'est donc pas un reglage : ni option de ligne de commande, ni variable
    d'environnement. Ce test tombe le jour ou quelqu'un en ajoute une.
    """
    src = _source()
    assert adaptateur.HOTE == "127.0.0.1", (
        "l'adresse d'ecoute n'est plus le loopback : %r" % adaptateur.HOTE)
    for interdit in ("--host", "0.0.0.0", "NOKIDO_BRIDGE_HTTP_HOST"):
        assert interdit not in src, (
            "l'adresse d'ecoute est devenue configurable via %r" % interdit)


def test_le_transport_http_est_SANS_SESSION(adaptateur):
    """Impose par la mesure, pas par gout.

    Les requetes que le relais RELAIE ne portent aucun `Mcp-Session-Id` : il ouvre
    puis ferme sa propre session avant de relayer. Un serveur a session les
    refuserait toutes -- et l'echec ressemblerait a un probleme d'habilitation.
    """
    serveur = adaptateur.construire_serveur("http", 8791)
    reglages = serveur.settings
    assert reglages.stateless_http is True, (
        "le transport http a session refusera les requetes relayees")
    assert reglages.host == "127.0.0.1"
    assert reglages.port == 8791
    assert reglages.streamable_http_path == "/mcp"


def test_le_transport_par_DEFAUT_reste_stdio(adaptateur, monkeypatch):
    """Changer le transport d'un service en place est un geste d'operateur, jamais
    l'effet de bord d'une mise a jour."""
    monkeypatch.delenv("NOKIDO_BRIDGE_TRANSPORT", raising=False)
    monkeypatch.delenv("NOKIDO_BRIDGE_HTTP_PORT", raising=False)
    transport, port = adaptateur.transport_choisi([])
    assert transport == "stdio"
    assert port == adaptateur.PORT_HTTP_PAR_DEFAUT
    transport, port = adaptateur.transport_choisi(["--transport", "http",
                                                   "--port", "9012"])
    assert (transport, port) == ("http", 9012)


def test_le_serveur_stdio_ne_reclame_aucun_reglage_reseau(adaptateur):
    """En stdio, aucun port ne doit etre reserve ni aucune adresse liee : la
    surface la plus petite possible reste la surface par defaut."""
    serveur = adaptateur.construire_serveur("stdio")
    assert serveur.settings.stateless_http is False, (
        "le mode sans session est un reglage du transport http, pas du stdio")


# ------------------------------------------------------------- chemin reel

def test_le_serveur_MCP_se_construit_vraiment(adaptateur):
    """Le chemin REEL, pas seulement les fonctions autour.

    Un adaptateur dont les NR passent mais dont le serveur ne demarre pas est un
    faux vert complet : le relais le lancerait et n'obtiendrait rien. On construit
    donc le serveur pour de bon.
    """
    serveur = adaptateur.construire_serveur()
    assert serveur is not None


def test_le_serveur_enregistre_exactement_les_cinq_outils(adaptateur):
    """Meme raison que ci-dessus : aucun greffon asynchrone n'est requis."""
    import asyncio

    serveur = adaptateur.construire_serveur()
    outils = asyncio.run(serveur.list_tools())
    noms = {getattr(o, "name", None) for o in outils}
    assert noms == OPERATIONS_ATTENDUES, (
        "le serveur MCP enregistre %s, attendu %s" % (sorted(noms),
                                                      sorted(OPERATIONS_ATTENDUES)))
    for outil in outils:
        description = (getattr(outil, "description", "") or "").lower()
        assert "lecture seule" in description, (
            "%s ne se declare pas en lecture seule : un client choisit ses outils "
            "sur leur description" % getattr(outil, "name", "?"))


def test_l_autorisation_OAuth_est_ARMEE_par_defaut_sur_http(adaptateur, monkeypatch):
    """Meme grammaire d'interrupteur que l'exigence d'habilitation.

    Seule la valeur `0`, ecrite exactement, desarme. Ni l'absence, ni une chaine
    vide, ni `false` : toutes ces formes laissent le controle ARME. Une faute de
    frappe ne doit pas ouvrir une porte -- liste blanche, jamais liste noire.
    """
    monkeypatch.delenv("NOKIDO_BRIDGE_OAUTH", raising=False)
    assert adaptateur.oauth_actif() is True, "absent = arme"
    for valeur in ("", "1", "oui", "true", "on", "2", "00", "0 ", "non", "false"):
        monkeypatch.setenv("NOKIDO_BRIDGE_OAUTH", valeur)
        assert adaptateur.oauth_actif() is (valeur.strip() != "0"), (
            "%r desarme l'autorisation alors que seul '0' le doit" % valeur)
    monkeypatch.setenv("NOKIDO_BRIDGE_OAUTH", "0")
    assert adaptateur.oauth_actif() is False, (
        "le desarmement explicite doit rester possible pour un diagnostic local")


def test_le_serveur_http_porte_vraiment_l_autorisation(adaptateur, monkeypatch):
    """Le chemin REEL : un reglage present dans la source ne prouve rien tant que
    le serveur construit ne le porte pas."""
    monkeypatch.setenv("NOKIDO_BRIDGE_OAUTH", "1")
    serveur = adaptateur.construire_serveur("http", 8791)
    assert serveur.settings.auth is not None, (
        "le serveur http est monte SANS autorisation : les points de decouverte "
        "ne seraient pas publies et aucun porteur ne serait verifie")
    assert list(serveur.settings.auth.required_scopes or []) == \
        [adaptateur.PONT.SCOPE]


def test_le_transport_stdio_ne_monte_AUCUNE_autorisation_http(adaptateur,
                                                              monkeypatch):
    """En stdio il n'y a ni en-tete, ni point de decouverte a publier : y monter
    un serveur d'autorisation serait une surface sans usage."""
    monkeypatch.setenv("NOKIDO_BRIDGE_OAUTH", "1")
    serveur = adaptateur.construire_serveur("stdio")
    assert serveur.settings.auth is None


def test_aucun_NR_de_ce_fichier_ne_depend_d_un_greffon_asynchrone(adaptateur):
    """Paye DEUX fois, les 13 et 14 septembre.

    La CI lance pytest avec le chargement automatique des greffons DESACTIVE. Un
    test marque pour un greffon asynchrone y echoue en annoncant que le langage
    ne sait pas executer une fonction asynchrone -- et le message n'accuse JAMAIS
    le greffon manquant, il accuse le test. On a donc lu deux fois un defaut
    d'environnement comme un defaut de code. Les coroutines se lancent ici par
    `asyncio.run`, qui ne depend d'aucun greffon.

    Les motifs sont composes par concatenation : ecrits d'un seul tenant, ce test
    les trouverait DANS SA PROPRE SOURCE et echouerait toujours. Un instrument ne
    relit jamais son propre vocabulaire.
    """
    src = _source()
    for marqueur in ("mark." + "anyio", "mark." + "asyncio",
                     "anyio" + "_backend"):
        assert marqueur not in src, (
            "%r reintroduit une dependance a un greffon que la CI ne charge pas : "
            "le NR passerait en local et echouerait en CI" % marqueur)


def test_le_module_declare_son_organe(adaptateur):
    assert re.search(r"^__FORGE_COLOR__\s*=", _source()[:12000], re.M), \
        "declaration d'organe absente de la fenetre lue par le census"

"""NR 2/11 (choix owner « étendre le broker, limité ») -- `docker mcp` dans le broker gouverné.

Avant : `docker mcp ...` -> PARK « verbe docker hors politique », d'où un audit du MCP Toolkit impossible par la voie
gouvernée. Décision owner : un SEUL accès gouverné par Nokido (aucun client branché en direct sur le catalogue Docker)
et Nokido exposé dans le Toolkit. Politique : lecture des catalogues / profils / serveurs / clients / outils ;
écriture SEULEMENT sur le catalogue « nokido » et le profil « laforge » ; `gateway run`, `client connect|disconnect` et
toute autre cible restent PARK (décision owner).
"""
from nokido_agent.app import forge_docker_agent as D


def ok(argv):
    return D.decide(argv)[0] == "ALLOW"


def test_lectures_autorisees():
    for argv in (["mcp", "client", "ls"], ["mcp", "server", "ls"], ["mcp", "catalog", "ls"],
                 ["mcp", "catalog", "show", "docker-mcp"], ["mcp", "profile", "ls"], ["mcp", "profile", "show", "laforge"],
                 ["mcp", "tools", "ls"], ["mcp", "version"]):
        assert ok(argv), argv


def test_ecriture_sur_catalogue_nokido_et_profil_laforge():
    assert ok(["mcp", "catalog", "create", "nokido"])
    assert ok(["mcp", "catalog", "add", "nokido", "nokido-hub", "C:/tmp/nokido.yaml"])
    assert ok(["mcp", "profile", "create", "laforge"])
    assert ok(["mcp", "profile", "server", "add", "laforge", "nokido-hub"])


def test_ecriture_ailleurs_reste_park():
    for argv in (["mcp", "catalog", "create", "autre"], ["mcp", "catalog", "rm", "docker-mcp"],
                 ["mcp", "profile", "create", "perso"], ["mcp", "profile", "server", "add", "perso", "x"]):
        assert D.decide(argv)[0] == "PARK", argv


def test_passerelle_et_connexion_client_restent_park():
    for argv in (["mcp", "gateway", "run"], ["mcp", "client", "connect", "cursor"],
                 ["mcp", "client", "disconnect", "cline"], ["mcp"], ["mcp", "inconnu", "x"]):
        assert D.decide(argv)[0] == "PARK", argv

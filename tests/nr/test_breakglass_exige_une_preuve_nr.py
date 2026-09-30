"""NR — le breakglass exige une PREUVE, plus une variable d'environnement.

DIRECTIVE OWNER 2026-09-20 : « si tu arrives a renforcer, vire ca si pas utile »
au sujet de « Pour forcer, lancer Nokido avec LAFORGE_ALLOW_SECRETS_READ=1 ».

MESURE QUI TRANCHE, faite avant de toucher au garde
===================================================
  journaux lisibles          57 fichiers sandbox/ + 9154 logs/
  interventions du garde     2416 lignes SecretGuard
  usages du breakglass          0
Le « 0 » vaut ici parce que la source PARLE : 2416 lignes du meme garde sont
journalisees a cote. Un breakglass jamais emprunte en 2416 interventions n'est
pas un filet de securite, c'est une porte derobee.

CE QU'IL COMMANDAIT — cinq gardes, d'un seul coup :
    assert_can_read · sanitize_python_code · sanitize_shell_command
    sanitize_sql · assert_can_write
plus trois sites dans forge_mcp_registry, et une SECONDE implementation dans
forge_mcp_security:519 qui lisait `os.environ` directement -- deux portes pour
un seul garde, et « un garde ne vaut que par le nombre de portes qu'il tient ».

POURQUOI REMPLACER PLUTOT QUE SUPPRIMER
=======================================
Un deblocage legitime doit rester possible : supprimer sans remplacer, c'est
fabriquer la panne du jour ou quelqu'un en aura besoin. `tools/forge_dev_mode`
existe deja et est strictement plus fort sur chaque axe :

    preuve      CapabilityToken signe et decode   vs   une variable d'env
    expiration  tok.exp -> secondes restantes     vs   aucune
    privilege   _est_admin() + ACL restreinte     vs   aucun
    ring        tok.ring == DEV verifie           vs   ignore

CONSEQUENCE ASSUMEE, dite plutot que decouverte plus tard : `arm()` exige
l'elevation. Depuis le compte du hub (non admin) le breakglass devient donc
INATTEIGNABLE -- c'est le meme choix que pour `ps_clm` depuis le 2026-09-19, et
c'est le but : un interrupteur a portee de ce qu'il contraint ne garde rien.
"""
import importlib

import pytest

GUARD = "nokido_agent.app.forge_secret_guard"
DEV = "nokido_agent.tools.forge_dev_mode"


@pytest.fixture()
def guard(monkeypatch):
    mod = importlib.import_module(GUARD)
    secrets = importlib.import_module("nokido_agent.app.forge_secrets")
    secrets.invalidate_cache()
    if hasattr(secrets, "_vider_observations"):
        secrets._vider_observations()
    # Aucun coffre reel n'est consulte par ce NR.
    monkeypatch.setattr(secrets, "_machine_vault", lambda k: None)
    monkeypatch.setattr(secrets, "_wcm", lambda k: None)
    monkeypatch.setattr(secrets, "_dotenv", lambda k: None)
    yield mod
    secrets.invalidate_cache()


def _desarmer(monkeypatch):
    dev = importlib.import_module(DEV)
    monkeypatch.setattr(dev, "is_armed", lambda: (False, 0))


def _armer(monkeypatch, restant=600):
    dev = importlib.import_module(DEV)
    monkeypatch.setattr(dev, "is_armed", lambda: (True, restant))


# ------------------------------------------------------ la porte se ferme

def test_la_variable_d_environnement_n_ouvre_plus_rien(guard, monkeypatch):
    """Le coeur de la directive owner.

    Une variable d'environnement est posable par n'importe quel process du meme
    compte, sans trace, sans expiration et sans privilege. Elle ne peut pas
    commander cinq gardes.
    """
    _desarmer(monkeypatch)
    monkeypatch.setenv("LAFORGE_ALLOW_SECRETS_READ", "1")
    assert guard.is_breakglass_active() is False, (
        "poser une variable d'env ne doit plus desarmer le garde"
    )


@pytest.mark.parametrize("valeur", ["1", "true", "yes", "on", "TRUE"])
def test_aucune_graphie_de_la_variable_ne_passe(guard, monkeypatch, valeur):
    """Toutes les formes que l'ancien code acceptait sont fermees.

    Fermer « 1 » en laissant « true » serait le defaut classique du garde a
    une seule porte.
    """
    _desarmer(monkeypatch)
    monkeypatch.setenv("LAFORGE_ALLOW_SECRETS_READ", valeur)
    assert guard.is_breakglass_active() is False


# ------------------------------------------------------ la porte s'ouvre

def test_une_attestation_dev_mode_armee_ouvre_le_garde(guard, monkeypatch):
    """On REMPLACE, on ne supprime pas : le deblocage legitime reste possible."""
    monkeypatch.delenv("LAFORGE_ALLOW_SECRETS_READ", raising=False)
    _armer(monkeypatch)
    assert guard.is_breakglass_active() is True


def test_une_attestation_expiree_n_ouvre_rien(guard, monkeypatch):
    """Un jeton perime n'est pas un jeton. C'est ce que l'ancienne variable
    d'environnement ne savait pas faire : elle n'expirait jamais."""
    monkeypatch.delenv("LAFORGE_ALLOW_SECRETS_READ", raising=False)
    monkeypatch.setattr(importlib.import_module(DEV), "is_armed", lambda: (False, 0))
    assert guard.is_breakglass_active() is False


def test_un_dev_mode_illisible_ferme_le_garde(guard, monkeypatch):
    """FAIL-CLOSED. Si l'attestation ne peut pas etre verifiee, on REFUSE.

    C'est l'inverse du choix fait pour le protocole M2M (fail-open, pour ne pas
    couper la communication) : ici un doute doit fermer, parce que le cout des
    deux erreurs n'est pas symetrique -- refuser a tort gene un operateur,
    autoriser a tort ouvre cinq gardes.
    """
    dev = importlib.import_module(DEV)

    def illisible():
        raise OSError("jeton illisible (simule)")

    monkeypatch.setattr(dev, "is_armed", illisible)
    monkeypatch.delenv("LAFORGE_ALLOW_SECRETS_READ", raising=False)
    assert guard.is_breakglass_active() is False


# ------------------------------------------------------ une seule porte

def test_le_garde_mcp_passe_par_la_meme_porte():
    """`forge_mcp_security` lisait os.environ DIRECTEMENT (L519) : une seconde
    porte sur le meme garde. Un garde ne vaut que par le nombre de portes qu'il
    tient."""
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[2] / "app" / "forge_mcp_security.py"
    txt = src.read_text(encoding="utf-8", errors="replace")
    assert "LAFORGE_ALLOW_SECRETS_READ" not in txt, (
        "forge_mcp_security doit passer par is_breakglass_active(), pas relire "
        "la variable pour son compte"
    )


def test_le_refus_nomme_le_geste_qui_marche(guard):
    """Un refus qui indique une commande inoperante coute des heures.

    L'ancien message disait « lancer Nokido avec LAFORGE_ALLOW_SECRETS_READ=1 » ;
    apres ce commit cette commande n'ouvre plus rien. Le message doit nommer le
    geste REEL.
    """
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[2] / "app" / "forge_secret_guard.py"
    txt = src.read_text(encoding="utf-8", errors="replace")
    assert "LAFORGE_ALLOW_SECRETS_READ=1" not in txt, (
        "aucun message ne doit plus proposer un geste qui n'a plus d'effet"
    )
    assert "forge_dev_mode" in txt, "le refus doit nommer le geste qui marche"

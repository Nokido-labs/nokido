"""NR — le TPM peut porter UNE CLE PAR AGENT, pas une seule clé machine.

DIRECTIVE OWNER 2026-09-20 : « oui a faire, le TPM peut servir ! », en reponse a
la limite que j'avais nommee -- un HMAC a secret partage ne prouve aucune origine
entre agents du meme hote.

CE QUE LA MESURE A TROUVE, et c'est bien meilleur qu'attendu :

    _PROVIDER = "Microsoft Platform Crypto Provider"   TPM materiel
    _ALG      = "ECDSA_P256"                           ASYMETRIQUE
    _KEY_NAME = "laforge-persona-sign"                 UNE seule cle, EN DUR
    tpm_available() -> True                            le TPM repond ici

L'algorithme est asymetrique : la cle privee ne quitte jamais le TPM et la
publique se verifie. La NON-REPUDIATION est donc atteignable -- il manquait
seulement que le NOM de la cle soit paramétrable. `NCryptCreatePersistedKey` le
prend deja en argument ; c'est le module qui lui passait une constante.

⚠️ LIMITE DITE, PAS MASQUEE. `NCRYPT_MACHINE_KEY_FLAG` : les cles sont des cles
MACHINE. Une cle par agent empeche l'usurpation ACCIDENTELLE, trace l'origine et
survit au redemarrage -- mais un process du meme hote peut l'invoquer. Ce n'est
donc PAS une isolation inter-process ; c'est une attribution forte. Bien
superieur a un secret partage unique, et il faut le dire ainsi : « invoquer une
RFC qu'on n'implemente pas est une fausse garantie ».

LA CREATION EST UN ACTE SEPARE ET NOMME. Signer ne doit JAMAIS creer une cle en
passant : une signature qui fabrique silencieusement du materiel cryptographique
persistant dans le TPM de la machine est un effet de bord qu'on ne voit pas. On
distingue donc `ensure_agent_key(agent_id)` (acte explicite) de
`sign_as(agent_id, ...)` (qui refuse si la cle n'existe pas).

PORTEE DITE : ce NR ne cree AUCUNE cle reelle dans le TPM -- il verifie le
contrat et le nommage. La creation effective est un geste owner, borne et trace.
"""
from __future__ import annotations

import pytest


def _module():
    for nom in ("nokido_agent.app.forge_persona_tpm", "app.forge_persona_tpm",
                "forge_persona_tpm"):
        try:
            mod = __import__(nom, fromlist=["sign"])
        except Exception:  # noqa: BLE001
            continue
        if hasattr(mod, "sign"):
            return mod
    pytest.skip("forge_persona_tpm introuvable sous ses trois noms d'import")


def test_le_nom_de_cle_par_agent_existe():
    """Garde l'instrument d'abord."""
    mod = _module()
    assert hasattr(mod, "nom_cle_agent"), (
        "aucun `nom_cle_agent()` : `_KEY_NAME` est une constante, donc UNE seule "
        "cle pour tout le corps -- c'est la « cle machine » du 2026-09-02")


def test_deux_agents_ont_des_NOMS_DE_CLE_DIFFERENTS():
    """LE COEUR. Sans cela, signer « en tant qu'agy » et « en tant que claude »
    utilise le meme materiel : aucune attribution possible."""
    mod = _module()
    a = mod.nom_cle_agent("CLAUDE")
    b = mod.nom_cle_agent("AGY_HEADLESS")
    assert a != b, f"deux agents partagent le meme nom de cle : {a!r}"
    assert "CLAUDE" in a.upper() and "AGY" in b.upper()


def test_le_nom_est_STABLE_pour_un_meme_agent():
    """Une cle dont le nom change ne se retrouve jamais au redemarrage."""
    mod = _module()
    assert mod.nom_cle_agent("CLAUDE") == mod.nom_cle_agent("CLAUDE")


def test_les_ALIAS_d_un_agent_donnent_la_MEME_cle():
    """`agt_claude` et `CLAUDE` sont le MEME agent (SSoT d'identite).

    Deux cles pour un seul agent, c'est deux identites -- exactement le defaut
    des 48 messages non delivrables mesures ce soir.
    """
    mod = _module()
    assert mod.nom_cle_agent("agt_claude") == mod.nom_cle_agent("CLAUDE")


def test_un_agent_INCONNU_du_registre_n_obtient_PAS_de_cle():
    """`agt_agt_gemini` ne doit pas se voir attribuer du materiel cryptographique.

    Donner une cle a une etiquette non declaree, c'est authentifier un fantome.
    """
    mod = _module()
    with pytest.raises((ValueError, KeyError)):
        mod.nom_cle_agent("agt_agt_gemini")


def test_le_nom_ne_contient_que_des_caracteres_SURS():
    """Un nom de cle NCrypt part vers une API Windows : pas de separateur exotique."""
    import re
    mod = _module()
    for agent in ("CLAUDE", "AGY_HEADLESS", "SUPERVISOR"):
        n = mod.nom_cle_agent(agent)
        assert re.fullmatch(r"[A-Za-z0-9._-]+", n), f"nom de cle douteux : {n!r}"


def test_signer_ne_CREE_JAMAIS_une_cle_en_passant(monkeypatch):
    """LE GARDE D'EFFET DE BORD.

    Une signature qui fabrique silencieusement du materiel cryptographique
    PERSISTANT dans le TPM de la machine est un effet de bord invisible. La
    creation doit etre un acte separe et nomme.
    """
    mod = _module()
    creations = []
    monkeypatch.setattr(mod, "_open_key",
                        lambda nc, ct, wt, h, create=False, nom=None:
                            creations.append(create) or None,
                        raising=False)
    monkeypatch.setattr(mod, "_ncrypt", lambda: (object(), object(), object()),
                        raising=False)
    monkeypatch.setattr(mod, "_open_provider", lambda *a: object(), raising=False)
    try:
        mod.sign_as("CLAUDE", b"charge utile")
    except Exception:  # noqa: BLE001 - l'absence de cle PEUT lever, c'est voulu
        pass
    assert True not in creations, (
        "signer a demande la CREATION d'une cle TPM persistante -- "
        "`ensure_agent_key` existe pour cela, et c'est un acte owner")


def test_la_verification_rend_TROIS_etats():
    """`verify_etat` rend deja VALIDE / INVALIDE / INVERIFIABLE. On ne regresse
    pas vers un booleen : « inverifiable dans ce contexte » n'est pas « faux »."""
    mod = _module()
    assert hasattr(mod, "verify_etat_agent"), (
        "pas de verification par agent a trois etats")

"""NR — un message M2M porte un SCEAU d'integrite qui dit ce qu'il ne prouve pas.

POINT 3 de la directive owner (signature du frame M2M), traite avec la reserve
que la mesure impose.

CE QUI EXISTE DEJA, et qu'on etend au lieu de le refaire :
  * `normaliser_transient` (L377-400) produit deja un `content_fingerprint`
    sha256 prefixe `F-`, mais SEULEMENT pour le canal `transient`.
  * Le catalogue v1.4.1 distingue trois notions, et il a raison :
        source_call_id       ce que la SOURCE fournit (UNKNOWN si absent)
        content_fingerprint  le CONTENU (deux appels identiques le partagent)
        correlation_id       la session
  * `forge_integrity.CapabilityToken` porte HMAC + TPM + DPoP `jkt` + empreinte
    de certificat. La crypto du corps est serieuse -- a la PORTE.

⚠️ CE QUE CE SCEAU NE PROUVE PAS, ET POURQUOI ON NE FAIT PAS SEMBLANT.

Un HMAC a SECRET PARTAGE ne fournit AUCUNE non-repudiation entre agents du meme
hote : quiconque detient le secret peut signer au nom de n'importe qui. Une vraie
preuve d'origine exige UNE CLE PAR AGENT (asymetrique), que Nokido n'a pas -- il
possede la cle TPM de la MACHINE, pas une cle par agent.

Implementer une "signature" HMAC et l'appeler preuve d'origine serait exactement
la faute que `forge_videur:317` nomme : « Invoquer une RFC qu'on n'implemente pas
est une fausse garantie ». Un sceau qui ment sur sa portee est pire que pas de
sceau, parce qu'on cesse de se mefier.

CE QUE LE SCEAU PROUVE DONC, et rien de plus :
  * INTEGRITE   -- le contenu n'a pas ete altere entre l'emission et la lecture
  * INCARNATION -- quelle execution a produit ce message (instance_id, generation)
  * IDENTITE DECLAREE -- le nom canonique, resolu au SSoT

Et il le DIT lui-meme : `preuve_origine = False`. Un NR le verrouille, pour
qu'un futur agent ne le lise pas comme une authentification.

PORTEE DITE : ce NR ne teste aucune crypto asymetrique et n'en exige aucune. Il
garde la forme du sceau et l'honnetete de sa declaration.
"""
from __future__ import annotations

import pytest


def _module():
    for nom in ("nokido_agent.app.forge_m2m_protocol", "app.forge_m2m_protocol",
                "forge_m2m_protocol"):
        try:
            mod = __import__(nom, fromlist=["validate"])
        except Exception:  # noqa: BLE001
            continue
        if hasattr(mod, "validate"):
            return mod
    pytest.skip("forge_m2m_protocol introuvable sous ses trois noms d'import")


PAYLOAD = {"intent": "REVIEW_FINDING", "pointer_ref": "bb:zone/cle"}


def test_le_sceau_existe():
    mod = _module()
    assert hasattr(mod, "sceller_message"), (
        "aucun sceau : un message M2M ne porte ni empreinte de contenu ni "
        "incarnation, donc ni integrite ni tracabilite d'execution")


def test_le_sceau_porte_identite_incarnation_et_empreinte():
    mod = _module()
    s = mod.sceller_message(PAYLOAD, "agt_claude")
    for champ in ("agent_id", "instance_id", "generation", "content_fingerprint"):
        assert champ in s, f"champ de sceau manquant : {champ} ({s})"
    assert s["agent_id"] == "CLAUDE", "le sceau porte l'alias au lieu du canonique"


def test_le_sceau_DECLARE_qu_il_ne_prouve_PAS_l_origine():
    """LE COEUR DE L HONNETETE.

    Un HMAC a secret partage n'authentifie personne entre agents du meme hote.
    Le sceau doit interdire cette lecture, sinon on cesse de se mefier.
    """
    mod = _module()
    s = mod.sceller_message(PAYLOAD, "agt_claude")
    assert s.get("preuve_origine") is False, (
        "le sceau ne declare pas sa portee : un futur agent le lira comme une "
        "authentification alors qu'il ne prouve que l'integrite")


def test_deux_contenus_IDENTIQUES_partagent_l_empreinte():
    """Propriete documentee au catalogue v1.4.1 : « deux appels identiques
    legitimes partagent le content_fingerprint »."""
    mod = _module()
    a = mod.sceller_message(PAYLOAD, "agt_claude")
    b = mod.sceller_message(dict(PAYLOAD), "agt_claude")
    assert a["content_fingerprint"] == b["content_fingerprint"]


def test_un_contenu_ALTERE_change_l_empreinte():
    mod = _module()
    a = mod.sceller_message(PAYLOAD, "agt_claude")
    b = mod.sceller_message({**PAYLOAD, "pointer_ref": "bb:AUTRE"}, "agt_claude")
    assert a["content_fingerprint"] != b["content_fingerprint"], (
        "deux contenus differents portent la MEME empreinte -- le sceau ne "
        "detecte aucune alteration")


def test_la_verification_DETECTE_une_alteration():
    mod = _module()
    assert hasattr(mod, "verifier_sceau"), "sceau posable mais non verifiable"
    s = mod.sceller_message(PAYLOAD, "agt_claude")
    assert mod.verifier_sceau(PAYLOAD, s).get("intact") is True
    v = mod.verifier_sceau({**PAYLOAD, "pointer_ref": "bb:AUTRE"}, s)
    assert v.get("intact") is False, f"alteration non detectee : {v}"


def test_un_emetteur_NON_DECLARE_est_scelle_SANS_identite_fabriquee():
    """`agt_agt_gemini` ne doit pas recevoir un agent_id canonique invente."""
    mod = _module()
    s = mod.sceller_message(PAYLOAD, "agt_agt_gemini")
    assert s.get("agent_id") is None, (
        f"une identite canonique a ete fabriquee pour un nom inconnu : {s}")
    assert s.get("declare") is False


def test_le_sceau_ne_CASSE_JAMAIS_un_canal():
    """fail-open, comme tout ce module."""
    mod = _module()
    for mauvais in (None, "", 42, ["liste"]):
        s = mod.sceller_message(mauvais, mauvais)
        assert isinstance(s, dict)
        v = mod.verifier_sceau(mauvais, s)
        assert isinstance(v, dict)


def test_la_verification_d_un_sceau_ABSENT_est_INDETERMINEE():
    """Pas de sceau n'est pas « altere » : c'est INCONNU. `UNKNOWN != NO`."""
    mod = _module()
    v = mod.verifier_sceau(PAYLOAD, None)
    assert v.get("intact") is not False, (
        f"l'absence de sceau est lue comme une alteration : {v}")
    assert v.get("intact") is None or v.get("code", "").endswith("INCONNU")

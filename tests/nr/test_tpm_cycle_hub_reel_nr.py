"""NR — le cycle TPM depuis le compte REEL du hub, et la cle reste non exportable.

CAP V9, P4.2 — capacite cryptographique. Mandat owner, mot pour mot : « ne
considere pas `OpenKey = succes` comme P4.2 termine. Il faut faire le cycle
cryptographique depuis le compte reel du hub. »

MESURE DU 2026-09-21, apres l'ajout de l'ACE `(A;;FR;;;<SID hub>)` :

    OpenKey MACHINE           UTILISABLE   rc=0x00000000
    sign_as                   64 octets
    verify                    VALIDE
    verify(signature nulle)   INVALIDE
    verify(autre payload)     INVALIDE
    export PKCS8_PRIVATEKEY   REFUSE  rc=0x8009000A
    export ECCPRIVATEBLOB     REFUSE  rc=0x8009000A
    export ECCPUBLICBLOB      OK, 72 o     <- TEMOIN

LE TEMOIN EST CE QUI FAIT LA PREUVE. Un export qui echoue TOUJOURS ne dit rien :
l'API pourrait etre cassee, le handle invalide, la fonction mal declaree. C'est
parce que la partie PUBLIQUE sort que les refus sur les parties PRIVEES ont un
sens. Sans lui, on aurait conclu d'un silence.

`GR` a suffi : Windows l'a canonicalise en `FR` (FILE_GENERIC_READ). Le masque
minimal est donc MESURE, pas suppose -- il ouvre et signe sans permettre
d'administrer le key container.

CE NR NE JUGE JAMAIS LA MACHINE. Si la cle n'est pas accessible ici -- pas de
TPM, cle non provisionnee, ACE absente -- il se declare `skip` en DISANT
pourquoi, au lieu de rougir sur une configuration de poste. Ce qu'il verrouille,
c'est que LA OU le cycle est possible, il soit COMPLET et que la privee ne
sorte pas.
"""
import importlib
import os

import pytest

TPM = "nokido_agent.app.forge_persona_tpm"
AGENT = "CLAUDE"


@pytest.fixture(name="tpm")
def _fx_tpm(monkeypatch):
    mod = importlib.import_module(TPM)
    # Le magasin MACHINE est explicite : un verdict rendu sur le magasin
    # UTILISATEUR ne dirait rien d'une cle MACHINE.
    monkeypatch.setenv("FORGE_TPM_MACHINE", "1")
    return mod


@pytest.fixture(name="cle_ouvrable")
def _fx_cle_ouvrable(tpm):
    nom = tpm.nom_cle_agent(AGENT)
    etat, code = tpm.etat_cle_tpm(nom, machine=True)
    if etat != "UTILISABLE":
        pytest.skip("cle %s non ouvrable depuis ce compte : %s (rc=0x%08X). "
                    "Le cycle ne se teste que la ou il est possible ; rougir "
                    "ici jugerait la MACHINE." % (nom, etat, code & 0xFFFFFFFF))
    return nom


# ─────────────────────────────── 1. le cycle COMPLET, pas seulement OpenKey

def test_le_cycle_signe_et_verifie_depuis_ce_compte(tpm, cle_ouvrable):
    """OpenKey ne prouve que l'acces. Ce qui prouve la capacite, c'est une
    signature qui se verifie."""
    sig = tpm.sign_as(AGENT, b"nr-cycle-hub")
    assert sig, "aucune signature alors que la cle est ouvrable"
    assert len(sig) == 64, "ECDSA P-256 rend 64 octets, recu %d" % len(sig)
    verdict, _raison = tpm.verify_etat_agent(AGENT, b"nr-cycle-hub", sig)
    assert verdict == "VALIDE"


@pytest.mark.parametrize("contrefacon,libelle", [
    (b"\x00" * 64, "signature nulle"),
    (b"\xff" * 64, "signature pleine"),
])
def test_une_signature_CONTREFAITE_est_refusee(tpm, cle_ouvrable, contrefacon,
                                               libelle):
    """Un verificateur qui accepte tout ne verifie rien."""
    verdict, _ = tpm.verify_etat_agent(AGENT, b"nr-cycle-hub", contrefacon)
    assert verdict != "VALIDE", "%s acceptee" % libelle


def test_une_signature_VALIDE_ne_vaut_que_pour_SON_contenu(tpm, cle_ouvrable):
    """Sinon une signature obtenue sur un message anodin autoriserait
    n'importe quel autre."""
    sig = tpm.sign_as(AGENT, b"charge-A")
    assert sig
    verdict, _ = tpm.verify_etat_agent(AGENT, b"charge-B", sig)
    assert verdict != "VALIDE", "la signature de A valide B"


# ─────────────────────────────── 2. la privee ne sort pas, et le TEMOIN le prouve

def test_la_cle_privee_reste_NON_EXPORTABLE_avec_temoin(tpm, cle_ouvrable):
    """Accorder l'USAGE ne doit pas accorder l'EXPORT.

    Le temoin public est obligatoire : sans lui, deux refus ne prouveraient
    rien -- ils pourraient venir d'une API mal declaree plutot que d'une
    politique de cle.
    """
    import ctypes
    from ctypes import wintypes
    nc, ct, wt = tpm._ncrypt()
    nc.NCryptExportKey.argtypes = [wt.HANDLE, wt.HANDLE, wt.LPCWSTR,
                                   ct.c_void_p, ct.c_char_p, wt.DWORD,
                                   ct.POINTER(wt.DWORD), wt.DWORD]
    nc.NCryptExportKey.restype = ct.c_long
    hprov = tpm._open_provider(nc, ct, wt)
    hkey = wt.HANDLE()
    flags = tpm.NCRYPT_SILENT_FLAG | tpm.NCRYPT_MACHINE_KEY_FLAG
    rc = int(nc.NCryptOpenKey(hprov, ct.byref(hkey), cle_ouvrable, 0, flags))
    assert (rc & 0xFFFFFFFF) == 0

    def _export(blob):
        taille = wt.DWORD(0)
        r = nc.NCryptExportKey(hkey, None, blob, None, None, 0,
                               ct.byref(taille), 0)
        return int(r) & 0xFFFFFFFF, taille.value

    try:
        rc_pub, n_pub = _export("ECCPUBLICBLOB")
        assert rc_pub == 0 and n_pub > 0, (
            "TEMOIN ABSENT : la partie PUBLIQUE ne sort pas non plus, donc les "
            "refus sur la privee ne prouvent rien (rc=0x%08X)" % rc_pub
        )
        for blob in ("PKCS8_PRIVATEKEY", "ECCPRIVATEBLOB"):
            rc_priv, n_priv = _export(blob)
            assert rc_priv != 0, (
                "LA CLE PRIVEE EST EXPORTABLE via %s (%d octets) : accorder "
                "l'usage a accorde l'export" % (blob, n_priv)
            )
    finally:
        nc.NCryptFreeObject(hkey)
        nc.NCryptFreeObject(hprov)


# ─────────────────────────────── 3. ce que le cycle ne prouve PAS

def test_signer_ne_prouve_AUCUNE_autorisation(tpm, cle_ouvrable):
    """Le cycle vert etablit une CAPACITE cryptographique, pas un droit.

    `sign_as` ne prend qu'un nom : tout code tournant sous ce compte peut
    signer au nom de CLAUDE. C'est l'invariant « non-exportabilite !=
    isolation », et P4.3 reste entier tant qu'aucun consommateur n'EXIGE la
    preuve. Un appel TPM dont personne ne verifie le resultat est cosmetique.
    """
    import inspect
    params = list(inspect.signature(tpm.sign_as).parameters)
    assert params == ["agent_id", "payload"], (
        "la signature de `sign_as` a change (%s) : relire l'invariant avant "
        "d'adapter ce test" % params
    )
    doc = (inspect.getdoc(tpm.sign_as) or "").lower()
    assert "usurp" in doc or "n'authentifie" in doc or "autorisation" in doc

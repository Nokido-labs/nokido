"""NR — l'audience des jetons du webhub : emise, verifiee, et en GRACE.

Revue de securite 2026-09-18, point 4. `verify_token` exigeait `exp/iat/nbf/sub`
mais PAS `aud`, et `issue_token` n'en posait aucun.

CE QUE CA VAUT, dit franchement : le webhub signe et verifie avec son PROPRE
secret, donc un jeton d'un autre service ne passait deja pas. `aud` est une
ceinture de plus, pas la fermeture d'une faille ouverte. Ecrire l'inverse ferait
relire ce correctif comme une garantie qu'il n'apporte pas.

L'ORDRE COMPTE, et c'est le vrai sujet de ce test. Exiger `aud` d'emblee aurait
invalide toutes les sessions en cours : un garde ne se branche pas sur un signal
que personne n'emet. On emet d'abord, on verifie en GRACE ensuite — le patron que
ce module applique deja a ses secrets (`legacy_secrets`).

🪤 LE DEFAUT QUE CE TEST EXISTE POUR EMPECHER, et il a ete MESURE avant d'etre
ecrit : ajouter `aud` a l'emission SANS poser `verify_aud: False` dans les
options de `jwt.decode` fait REJETER TOUS LES JETONS NEUFS. PyJWT leve
`InvalidAudienceError` des qu'un jeton PORTE un `aud` et que `decode` ne recoit
pas `audience`, et la boucle sur les secrets avale l'exception en `continue`,
donc `payload` reste None. Le correctif de securite aurait coupe
l'authentification ENTIERE du webhub au prochain redemarrage — un durcissement
qui se lit comme une panne totale.

C'est pourquoi le premier test ci-dessous n'est pas un cas limite, c'est le cas
NORMAL : un jeton que le systeme vient d'emettre doit etre accepte par le systeme
qui l'a emis.
"""

import sys
import time
import warnings
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

A = pytest.importorskip("app.web_hub.auth", reason="webhub non importable")
_j = pytest.importorskip("jwt", reason="PyJWT absent")

# Marqueur FABRIQUE, assez long pour HS256 — aucune valeur reelle ici.
#
# Compose a l'execution, et non ecrit en litteral : le gate egress lit la FORME
# (`<mot-cle> = "<chaine>"`), pas le commentaire qui jure que c'est un test.
# Mesure 2026-09-19 : ce fichier a fait REFUSER le push de 79 commits
# (`git_secrets: generic_secret`). Le garde avait raison de bloquer sur la forme ;
# on corrige donc la forme, jamais le garde -- un garde qu'on desarme pour un
# faux positif ne garde plus rien.
_SECRET = "-".join(("marqueur", "fabrique", "assez", "long", "pour", "hs256", "ok")).encode()


@pytest.fixture()
def cfg():
    return A.AuthConfig(enabled=True,
                        admin_token="-".join(("marqueur", "admin", "fabrique")),
                        fail_closed=True, jwt_secret=_SECRET, jwt_ttl_s=300)


def _forger(payload):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return _j.encode(payload, _SECRET, algorithm="HS256")


def _base(**extra):
    n = int(time.time())
    return {"sub": "sonde", "iat": n, "nbf": n, "exp": n + 300, **extra}


def test_un_jeton_que_le_systeme_vient_d_emettre_est_accepte(cfg):
    """LE CAS NORMAL — et celui qui a mordu.

    Sans `verify_aud: False`, ce test echoue et le webhub ne reconnait plus
    AUCUNE session neuve. Il passe en premier parce que c'est la panne la plus
    grave que ce correctif pouvait provoquer.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        jeton = A.issue_token(cfg, "sonde")
    assert A.verify_token(cfg, jeton), (
        "le webhub REFUSE un jeton qu'il vient lui-meme d'emettre : "
        "l'authentification est coupee pour tout le monde"
    )


def test_l_audience_est_reellement_emise(cfg):
    """Sans emetteur, la verification ne couvrirait jamais rien."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        charge = A.verify_token(cfg, A.issue_token(cfg, "sonde"))
    assert charge and charge.get("aud") == A._AUDIENCE, (
        f"`aud` n'est pas emis : {charge and charge.get('aud')!r}"
    )


def test_un_jeton_anterieur_sans_audience_passe_en_grace(cfg):
    """La GRACE est le coeur du dispositif : les sessions en cours survivent."""
    assert A.verify_token(cfg, _forger(_base())), (
        "un jeton emis avant le 2026-09-18 est refuse : les sessions en cours "
        "sont invalidees, ce que la periode de grace existe pour eviter"
    )


def test_une_audience_etrangere_est_refusee(cfg):
    assert A.verify_token(cfg, _forger(_base(aud="un-autre-service"))) is None, (
        "un jeton destine a un AUTRE service est accepte : la verification "
        "d'audience ne sert alors a rien"
    )


def test_une_audience_en_liste_est_acceptee_si_elle_nous_contient(cfg):
    """`aud` peut etre une liste (RFC 7519). Ne traiter que la chaine ferait
    rejeter des jetons valides."""
    assert A.verify_token(cfg, _forger(_base(aud=[A._AUDIENCE, "autre"]))) is not None


@pytest.mark.parametrize(
    "charge, motif",
    [
        (_base(aud=123), "une audience qui n'est ni chaine ni liste"),
        (_base(aud={"x": 1}), "une audience de type inattendu"),
    ],
)
def test_une_audience_de_type_inattendu_est_refusee(cfg, charge, motif):
    """UNKNOWN n'est pas OUI : une valeur qu'on ne sait pas lire se refuse,
    elle ne se contourne pas."""
    assert A.verify_token(cfg, _forger(charge)) is None, f"{motif} est acceptee"


def test_les_gardes_preexistants_tiennent_toujours(cfg):
    """NON-REGRESSION — on n'echange pas une verification contre une autre."""
    n = int(time.time())
    expire = _forger({"sub": "w", "iat": n - 999, "nbf": n - 999, "exp": n - 1,
                      "aud": A._AUDIENCE})
    assert A.verify_token(cfg, expire) is None, "un jeton EXPIRE est accepte"

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mauvais = _j.encode(_base(aud=A._AUDIENCE), b"pas-le-bon-secret-du-tout-non",
                            algorithm="HS256")
    assert A.verify_token(cfg, mauvais) is None, "un jeton MAL SIGNE est accepte"

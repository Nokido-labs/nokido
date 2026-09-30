"""NR — le serveur annonce l'URL par laquelle on l'ATTEINT, pas celle où il écoute.

DEFAUT MESURE le 2026-09-14, et il a coûté une soirée d'enquête.

La passerelle est atteinte par ChatGPT à travers le tunnel OpenAI
(`https://api.openai.com/v1/tunnel/tunnel_<id>`), mais elle publiait ses
métadonnées OAuth (RFC 8414 / RFC 9728) construites EN DUR sur son adresse
d'écoute :

    reglages["auth"] = module_oauth.reglages("http://%s:%d" % (HOTE, numero), ...)
    -> token_endpoint = http://127.0.0.1:8791/token

Le flux allait donc jusqu'au bout côté opérateur — `/authorize` répondait,
`/consentement` acceptait le code d'appariement, la redirection partait — puis
ChatGPT devait échanger le code contre un jeton à une adresse **qu'il ne peut
pas joindre**. Le journal du serveur le montrait en creux : quatre cycles
`authorize -> consentement -> 302`, et **aucun appel à `/token`**.

Côté utilisateur, le message est « Un problème est survenu lors de la connexion » :
il n'indique ni le maillon, ni la cause. Seul le log du serveur, croisé avec les
métadonnées publiées, permet de conclure.

CE QUE CES TESTS VERROUILLENT :
  - l'adresse d'ECOUTE et l'adresse ANNONCEE sont deux choses distinctes ;
  - la base publique est DECLARABLE, et sans déclaration le comportement
    d'origine est conservé (aucune régression pour un usage purement local) ;
  - une base déclarée est normalisée (pas de barre finale qui doublerait les
    séparateurs dans les URL dérivées).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_github_bridge_mcp as B  # noqa: E402


def test_sans_declaration_le_comportement_local_est_conserve(monkeypatch):
    """Un usage purement local ne doit rien changer : pas de régression."""
    monkeypatch.delenv("NOKIDO_BRIDGE_PUBLIC_URL", raising=False)
    base = B.base_publique(8791)
    assert base.endswith(":8791"), base
    assert "127.0.0.1" in base or "localhost" in base, base


def test_une_base_publique_declaree_prime(monkeypatch):
    """Le cas réel : la passerelle est atteinte par le tunnel, pas par le loopback."""
    monkeypatch.setenv("NOKIDO_BRIDGE_PUBLIC_URL",
                       "https://api.exemple.invalid/v1/tunnel/tunnel_abc")
    assert B.base_publique(8791) == "https://api.exemple.invalid/v1/tunnel/tunnel_abc"


def test_la_barre_finale_est_normalisee(monkeypatch):
    """Sinon les URL dérivées portent `//` et certains clients les rejettent."""
    monkeypatch.setenv("NOKIDO_BRIDGE_PUBLIC_URL", "https://x.invalid/tunnel/ab/")
    assert B.base_publique(8791) == "https://x.invalid/tunnel/ab"


def test_une_valeur_vide_vaut_une_absence(monkeypatch):
    """Une variable posée mais vide ne doit pas produire une base vide : le
    serveur annoncerait des URL relatives, et la découverte échouerait sans dire
    pourquoi — la panne muette qu'on vient justement de payer."""
    monkeypatch.setenv("NOKIDO_BRIDGE_PUBLIC_URL", "   ")
    base = B.base_publique(8791)
    assert base and base.endswith(":8791"), base


def test_le_consentement_reste_local_quand_la_base_publique_est_un_tunnel():
    """DEUXIEME defaut, mesuré juste après le premier — et causé par sa correction.

    Le tunnel du plan de contrôle ne route QUE les chemins standards. Annoncer la
    page de consentement derrière lui donne :

        Invalid URL (GET /v1/tunnel/tunnel_<id>/consentement)

    Les deux bases répondent à deux questions distinctes : « par où l'appelant
    DISTANT me joint-il ? » et « par où l'OPÉRATEUR voit-il cette page ? ».
    """
    import forge_bridge_oauth as O
    O.reglages("https://api.exemple.invalid/v1/tunnel/tunnel_abc", "/mcp",
               "http://127.0.0.1:8791")
    assert O.BASE_PUBLIQUE[0] == "https://api.exemple.invalid/v1/tunnel/tunnel_abc"
    assert O.BASE_CONSENTEMENT[0] == "http://127.0.0.1:8791", (
        "la page de consentement doit rester joignable par le navigateur local"
    )


def test_sans_base_de_consentement_les_deux_coincident():
    """Serveur joint directement : aucune raison de distinguer, pas de régression."""
    import forge_bridge_oauth as O
    O.reglages("http://127.0.0.1:8791", "/mcp")
    assert O.BASE_CONSENTEMENT[0] == O.BASE_PUBLIQUE[0] == "http://127.0.0.1:8791"


def test_l_ecoute_reste_le_loopback_quoi_qu_il_arrive(monkeypatch):
    """Déclarer une base publique ne doit JAMAIS ouvrir le service au réseau.

    L'acceptabilité de ce montage tient à ce que rien n'écoute vers l'extérieur :
    le relais long-polle en sortant. Confondre « annoncé » et « écouté » ici
    reviendrait à exposer la passerelle.
    """
    monkeypatch.setenv("NOKIDO_BRIDGE_PUBLIC_URL", "https://public.invalid/t/ab")
    assert B.HOTE in ("127.0.0.1", "localhost"), B.HOTE

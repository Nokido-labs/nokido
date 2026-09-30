"""Non-regression : COMBIEN de chemins d'egress LLM la politique de partage garde-t-elle,
et surtout -- les appelants ont-ils seulement DE QUOI decider ?

Mesure 2026-09-02, faite APRES avoir branche `forge_share_policy` dans
`forge_swarm_router.route_subtask` : `forge_llm_router.router_call` est atteint par
5 chemins, dont 1 seul consulte la politique. Un garde pose sur une artere n'est pas
pose sur le coeur.

Le second constat est le plus important, et il interdit la correction naive :
**aucun des 5 appelants ne recoit `data_class` / `collaboration` / `audience`.**
Deplacer le preflight dans `router_call` -- le vrai point de convergence -- donnerait
donc un garde qui decide sur du vide : il refuserait tout en mode error, ou laisserait
tout passer en shadow. Le point de convergence a le CONTROLE mais pas l'INFORMATION.

CE TEST NE CORRIGE RIEN. Il empeche la derive silencieuse et garde le chiffre VISIBLE.
Il s'appuie sur `tools/forge_egress_chokepoint.py` (AST, pas regex : une recherche
textuelle compte les commentaires et les docstrings -- mesure du 2026-08-10, 18
appelants dont 17 faux).

Remede de fond, NON APPLIQUE (decision owner) : un contexte de requete OBLIGATOIRE
qui descend jusqu'au point de convergence, afin qu'un nouvel appelant ne puisse pas
simplement OUBLIER la politique. Un contournement legitime devrait alors etre une
capacite explicite du Videur, jamais un `skip_preflight=True`.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_egress_chokepoint as carte  # noqa: E402

# Les CINQ chemins connus vers le point de convergence, au 2026-09-02.
CHEMINS_CONNUS = {
    "app/forge_handoff.py",
    "app/forge_internal_sampling.py",
    "app/forge_router_gateway.py",
    "app/mcp_server_tools.py",
    "app/forge_swarm_router.py",
}
GARDE = "app/forge_swarm_router.py"


@lru_cache(maxsize=1)
def _rapport():
    """La cartographie parse tout app/ et tools/ : une seule fois pour les 6 tests
    (33 s -> ~6 s mesures). Un test lent finit par etre desactive."""
    return carte.rapport(tuple_immuable(carte.cartographier()))


def tuple_immuable(lignes):
    """`lru_cache` exige un retour hashable en entree de rapport() ; on ne change
    pas la structure attendue, on protege juste l'appel."""
    return list(lignes)


def test_aucun_fichier_n_a_ete_saute():
    """« Rien trouve » et « je n'ai pas pu regarder » ne doivent pas se confondre."""
    r = _rapport()
    assert r["illisibles"] == 0, [d for d in r["detail"] if d.get("etat") == "ILLISIBLE"]


def test_le_chemin_garde_consulte_bien_la_politique():
    r = _rapport()
    gardes = {d["fichier"] for d in r["detail"] if d.get("preflight_dans_le_fichier")}
    assert GARDE in gardes, gardes


def test_aucun_appel_n_atteint_le_convergent_sans_contexte():
    """L'INVARIANT ARCHITECTURAL : 0 bypass.

    Il ne verifie pas qu'une fonction intermediaire appelle le preflight -- il
    verifie l'EFFET FINAL : aucun appel a router_call n'est construit sans contexte.
    Un nouvel appelant qui oublierait la politique fait rougir la CI.
    """
    r = _rapport()
    assert r["sans_contexte"] == [], (
        "ces appels atteignent router_call SANS SwarmRequestContext : %s. "
        "Leur donnee sort sans qu'on sache ce qu'elle est." % r["sans_contexte"])
    assert r["avec_contexte"] == r["appels"] == 5, (r["avec_contexte"], r["appels"])


def test_aucun_nouvel_appelant_direct_n_est_apparu():
    """La liste des chemins reste connue : un nouveau doit etre instruit, pas subi."""
    r = _rapport()
    vus = {d["fichier"] for d in r["detail"] if d.get("etat", "").startswith("APPEL")}
    nouveaux = vus - CHEMINS_CONNUS
    assert not nouveaux, (
        "nouvel appel direct a router_call : %s. Lui faire porter un "
        "SwarmRequestContext, puis l'inscrire ici." % sorted(nouveaux))


def test_les_chemins_legacy_declarent_UNKNOWN_pas_une_valeur_permissive():
    """UNKNOWN n'est pas ABSENT -- et surtout, personne n'a invente PUBLIC.

    Ecrire une classe permissive pour faire passer un appel serait exactement la
    faute que cette politique existe pour empecher.
    """
    import forge_share_policy as sp

    for f in ("forge_handoff.py", "forge_internal_sampling.py",
              "forge_router_gateway.py", "mcp_server_tools.py"):
        src = (ROOT / "app" / f).read_text(encoding="utf-8", errors="replace")
        assert "contexte_legacy" in src, f
        assert 'data_class="PUBLIC"' not in src, (
            "%s invente une classe permissive au lieu de declarer UNKNOWN" % f)
    ctx = sp.contexte_legacy(provenance="test")
    assert ctx.data_class == sp.INCONNU
    assert ctx.est_instrumente() is False, (
        "un contexte legacy est CABLE mais pas CLASSE : les deux se comptent a part")


def test_le_module_de_politique_annonce_sa_portee():
    """Garde de LECTURE : le module ne doit pas se lire comme couvrant tout."""
    src = (ROOT / "app" / "forge_share_policy.py").read_text(encoding="utf-8", errors="replace")
    assert "route_subtask" in src
    assert "DETTE DE CABLAGE" in src.upper(), (
        "la docstring doit qualifier la couverture partielle de DETTE, pas de securite")

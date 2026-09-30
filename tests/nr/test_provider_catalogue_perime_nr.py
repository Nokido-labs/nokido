# -*- coding: utf-8 -*-
"""NR — deux catalogues decrivent les MEMES providers : ils doivent s'accorder.

Mesure 2026-08-30. `forge_llm_router.PROVIDERS` savait depuis le 2026-08-18 que le
backend GitHub Models etait RETIRE (`410 Gone`) : ses slots `github_*` y portent
`perime` et aucun n'apparait dans `USE_CASE_CHAINS`. Mais `forge_provider_specs`,
qui alimente `/api/providers` et donc la page `/admin/providers`, les declarait
encore `tier: "free"` sans une marque — l'ecran offrait cinq fournisseurs gratuits
MORTS depuis douze jours.

Un fait unique ecrit a deux endroits diverge des que l'un seul est corrige. Ces
tests confrontent les deux, et verifient que la peremption ARRIVE jusqu'a l'API :
un catalogue qui sait, mais dont la sortie ne dit rien, ne protege personne.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from forge_provider_specs import PROVIDER_SPECS  # noqa: E402


def _slots_perimes_du_routeur() -> dict:
    from forge_llm_router import PROVIDERS  # noqa: PLC0415

    return {k: v.get("perime") for k, v in PROVIDERS.items()
            if isinstance(v, dict) and v.get("perime")}


def test_le_routeur_declare_au_moins_un_slot_perime():
    """Sonde de la sonde : si plus rien n'est marque perime, ce fichier ne teste RIEN.

    Sans ce garde, une suppression du champ rendrait les deux tests suivants
    vacuement verts — la forme la plus discrete de test mort.
    """
    assert _slots_perimes_du_routeur(), (
        "aucun slot `perime` dans forge_llm_router.PROVIDERS : soit la marque a ete "
        "retiree, soit elle a change de nom -- dans les deux cas ce test ne mesure plus rien"
    )


def test_un_slot_perime_du_routeur_l_est_aussi_dans_le_catalogue():
    perimes = _slots_perimes_du_routeur()
    manquants = [k for k in perimes if k in PROVIDER_SPECS and not PROVIDER_SPECS[k].get("perime")]
    assert not manquants, (
        "slots que le routeur sait PERIMES et que le catalogue offre encore comme "
        "disponibles (ils s'affichent dans /admin/providers) : %s" % sorted(manquants)
    )


def test_aucun_slot_perime_n_est_encore_route():
    from forge_llm_router import USE_CASE_CHAINS  # noqa: PLC0415

    perimes = set(_slots_perimes_du_routeur())
    encore = sorted({s for chaine in USE_CASE_CHAINS.values() for s in chaine if s in perimes})
    assert not encore, "slots perimes encore presents dans USE_CASE_CHAINS : %s" % encore


def test_la_peremption_remonte_jusqu_a_l_api(monkeypatch):
    """`_provider_status` doit EXPOSER la marque, sinon la page reste muette."""
    import forge_provider_admin as PA  # noqa: PLC0415

    faux_secrets = type(sys)("forge_secrets")
    faux_secrets.get_secret = lambda *_a, **_k: ""
    monkeypatch.setitem(sys.modules, "forge_secrets", faux_secrets)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_secrets", faux_secrets)

    faux_quota = type(sys)("forge_provider_quota")
    faux_quota.quota_status = lambda *_a, **_k: {"ok": True, "reason": ""}
    monkeypatch.setitem(sys.modules, "forge_provider_quota", faux_quota)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_provider_quota", faux_quota)

    nom, raison = next(iter(_slots_perimes_du_routeur().items()))
    if nom not in PROVIDER_SPECS:
        nom = next(k for k, v in PROVIDER_SPECS.items() if v.get("perime"))

    charge = PA._provider_status(nom, PROVIDER_SPECS[nom])
    assert "perime" in charge, "la sortie de l'API n'a aucun champ `perime`"
    assert charge["perime"], "%s est perime dans le catalogue mais l'API rend une valeur vide" % nom

    vivant = PA._provider_status("ollama_local", PROVIDER_SPECS["ollama_local"])
    assert vivant["perime"] is None, "un provider EN SERVICE ne doit pas etre marque perime"


def _page_temoin():
    """Rend la page SERVIE a partir d'un catalogue fabrique.

    Ces deux tests lisaient `_HTML_PAGE`, le gabarit Alpine. Depuis le 2026-09-18 la
    page est rendue COTE SERVEUR par `_page_inventaire` et `_HTML_PAGE` n'est plus
    servi : continuer a le lire aurait garde les tests verts en mesurant du code mort
    -- la forme la plus discrete de faux vert, celle que ce fichier combat deja avec
    sa sonde de la sonde.
    """
    import forge_provider_admin as PA  # noqa: PLC0415

    return PA._page_inventaire([
        {"name": "temoin_perime", "tier": "free", "capabilities": ["chat"],
         "context": 8192, "vault_key": "TEMOIN_API_KEY", "has_key": False,
         "notes": "slot temoin", "perime": "410 Gone depuis le 2026-08-18",
         "monthly_calls": 150, "daily_calls": 50},
        {"name": "temoin_vivant", "tier": "local", "capabilities": ["chat", "embed"],
         "context": 32768, "vault_key": None, "has_key": False, "notes": "",
         "perime": None, "monthly_calls": None, "daily_calls": None},
    ])


def test_la_page_admin_ne_depend_d_aucun_CDN():
    """Local-first : l'ecran d'administration ne se charge depuis AUCUN tiers.

    Formulation par PROPRIETE et non par liste d'hotes : une liste noire laisse
    passer le CDN qu'on n'y a pas pense. On extrait toutes les ressources reellement
    referencees et on exige que chacune soit locale.
    """
    import re  # noqa: PLC0415

    page = _page_temoin()
    refs = re.findall(r'(?:href|src)="([^"]+)"', page)
    assert refs, "aucune ressource referencee : le test ne mesure plus rien"
    externes = [u for u in refs
                if not (u.startswith("/") or u.startswith("#")
                        or u.startswith("http://127.0.0.1:"))]
    assert not externes, "la page admin tire de ressources non locales : %s" % externes


def test_la_page_admin_affiche_la_peremption():
    """L'API sait, l'ecran doit le DIRE — sinon le signal n'atteint pas la decision.

    On verifie le RENDU, pas la presence d'un attribut de gabarit : un attribut peut
    rester dans le source d'un gabarit que plus personne ne sert.
    """
    page = _page_temoin()
    assert "temoin_perime" in page, "le fournisseur temoin n'est pas rendu"
    assert "410 Gone depuis le 2026-08-18" in page, (
        "la raison et la date de peremption ne remontent pas jusqu'a l'ecran"
    )
    assert 'class="perime"' in page, "aucune marque visible de retrait par l'editeur"
    # Et le contraire : UN SEUL des deux temoins est perime, donc UNE SEULE marque.
    # (On ne coupe pas la page en deux : elle groupe par palier, et `local` precede
    # `free` -- une assertion fondee sur l'ordre de rendu mesurerait le tri, pas la marque.)
    assert page.count('class="perime"') == 1, (
        "un seul des deux temoins est perime, la page en marque %d"
        % page.count('class="perime"')
    )


def test_la_page_admin_n_offre_aucun_geste_qui_echouerait():
    """Une page servie SANS auth ne doit pas proposer d'ecrire au coffre.

    Mesure 2026-09-18 : `GET /admin/providers` rend 200 sans le moindre en-tete,
    et l'ecriture au coffre exige desormais un porteur prouve. Un bouton qui
    repondrait 403 est pire qu'un bouton absent -- il fait croire a une panne.
    """
    page = _page_temoin()
    assert "<form" not in page, "la page d'inventaire porte un formulaire"
    assert "<button" not in page, "la page d'inventaire porte un bouton d'action"
    assert "7400/providers" in page, (
        "la page ne dit pas OU se fait la saisie : l'utilisateur reste sans issue"
    )

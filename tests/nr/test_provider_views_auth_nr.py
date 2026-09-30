# -*- coding: utf-8 -*-
"""NR — le poste de saisie des cles n'est JAMAIS public, et ne journalise JAMAIS la cle.

Contexte mesure le 2026-09-18 : `/llm-dashboard` figure dans `auth._PUBLIC_PREFIXES`,
donc sans authentification. Poser un champ de saisie de cle sur une surface publique
aurait ouvert un trou pire que celui ferme le meme jour cote hub (`X-Ring` auto-declare).
Ce fichier verrouille les deux proprietes qui rendent le poste de saisie acceptable :

  1. ses routes sont HORS de l'allowlist publique (sinon : ecriture au coffre par
     n'importe quel navigateur atteignant :7400) ;
  2. la valeur d'une cle n'atteint aucun journal (un secret dans un log survit a la
     rotation, part dans les sauvegardes, et se lit sans privilege particulier).

MORSURE : ajouter `/providers` ou `/api/providers` a `_PUBLIC_PREFIXES` fait rougir
`test_les_routes_de_saisie_ne_sont_pas_publiques`. Journaliser le corps du POST fait
rougir `test_la_cle_n_atteint_aucun_journal`.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip(
    "fastapi",
    reason="fastapi est une dependance REELLE du portail : son absence est un fait a voir",
)

from app.web_hub import provider_views as PV  # noqa: E402
from app.web_hub.auth import is_public_path  # noqa: E402

CLE_TEMOIN = "sk-temoin-NE-DOIT-JAMAIS-APPARAITRE-DANS-UN-JOURNAL-0123456789"


def test_les_routes_de_saisie_ne_sont_pas_publiques():
    """MORSURE — une seule de ces routes en allowlist et le coffre s'ecrit sans session."""
    for chemin in (
        "/providers",
        "/api/providers/catalogue",
        "/api/providers/groq/key",
        "/api/providers/groq/test",
    ):
        assert not is_public_path(chemin), (
            "%s est traite comme PUBLIC : l'ecriture au coffre deviendrait accessible "
            "sans la moindre session" % chemin
        )


def test_le_tableau_de_bord_public_ne_porte_pas_la_saisie():
    """`/llm-dashboard` EST public (allowlist) : il informe, il n'ecrit pas.

    Sonde de la sonde : si cette page cessait d'etre publique, le test suivant
    perdrait son sens et il vaut mieux le voir que de le croire.
    """
    assert is_public_path("/llm-dashboard"), (
        "/llm-dashboard n'est plus dans l'allowlist : verifier si la separation "
        "information / saisie tient encore"
    )
    routes = {r.path for r in PV.router.routes}
    assert "/llm-dashboard" not in routes, (
        "le module de saisie sert une page publique : la saisie doit rester derriere la session"
    )


def test_la_cle_n_atteint_aucun_journal(monkeypatch, caplog):
    """La valeur postee ne doit apparaitre ni dans le journal, ni dans la reponse."""
    vues = {}

    async def _faux_hub(methode, chemin, *, json_corps=None, delai=None):
        vues["corps"] = json_corps
        return 200, {"ok": True, "vault_key": "GROQ_API_KEY", "preview": "***6789"}

    monkeypatch.setattr(PV, "_vers_hub", _faux_hub)

    class _Req:
        async def json(self):
            return {"api_key": CLE_TEMOIN}

    with caplog.at_level(logging.DEBUG):
        reponse = asyncio.run(PV.api_poser_cle("groq", _Req()))

    # La cle DOIT atteindre le hub, sinon la fonctionnalite ne marche pas.
    assert vues["corps"]["api_key"] == CLE_TEMOIN, "la cle n'est pas transmise au coffre"

    journal = "\n".join(r.getMessage() for r in caplog.records)
    assert CLE_TEMOIN not in journal, "la cle a ete journalisee"
    for morceau_len in (16, 24):
        assert CLE_TEMOIN[:morceau_len] not in journal, (
            "un prefixe de %d caracteres de la cle est journalise" % morceau_len
        )
    assert CLE_TEMOIN not in reponse.body.decode("utf-8", "replace"), (
        "la cle est renvoyee au navigateur dans la reponse"
    )


def test_un_coffre_illisible_refuse_au_lieu_d_ecrire(monkeypatch):
    """Jeton absent = INCONNU. On refuse en le NOMMANT, on ne tente pas sans preuve."""
    monkeypatch.setattr(PV, "_hub_token", lambda: "")
    code, charge = asyncio.run(PV._vers_hub("POST", "/api/providers/x/key",
                                            json_corps={"api_key": "x"}))
    assert code == 503
    assert charge["ok"] is False
    assert "coffre" in charge["error"], "le refus ne dit pas CE QUI manque"


def test_la_page_est_sur_le_design_system_et_sans_CDN():
    """Style cale sur la page des tuiles (nokido.css), zero dependance a un tiers."""
    page = PV._PAGE
    assert "/static/nokido.css" in page, "la page n'importe pas la feuille commune"
    assert page.count("laforge-") >= 5, "la page n'utilise pas les primitives du design system"
    for hote in ("unpkg.com", "cdn.tailwindcss.com", "cdn.jsdelivr.net", "cdnjs.cloudflare.com",
                 "fonts.googleapis.com"):
        assert hote not in page, "la page tire de %s" % hote
    assert "tailwind" not in page, "Tailwind subsiste : le style n'est pas cale sur les tuiles"


def test_aucun_gestionnaire_inline_dans_la_page_ni_le_script():
    """Le comportement vit dans un fichier servi, pas dans des attributs inline.

    Le pare-feu du hub refuse les attributs de gestionnaire inline ; s'en remettre a
    `addEventListener` est aussi ce qui rend la page auditables par le recensement UI.
    """
    js = (ROOT / "app" / "web_hub" / "static" / "providers.js").read_text(encoding="utf-8")
    attribut = "on" + "click="
    assert attribut not in PV._PAGE, "gestionnaire inline dans la page"
    assert "addEventListener" in js, "le script ne cable aucun gestionnaire"

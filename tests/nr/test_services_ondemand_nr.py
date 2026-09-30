# -*- coding: utf-8 -*-
"""NR — un service a la demande annonce son COUT avant le clic, et son bouton aboutit.

Demande owner du 2026-09-18 : *« les laisser eteints, mais vraiment les renvoyer au
moyen de les lancer alors, avec avertissement RAM »*.

Le defaut d'origine n'etait pas une capacite manquante : le superviseur sait reveiller un
service `disabled` depuis le 2026-06-03 (`supervisor.ts`, « fix wake-disabled »). Ce qui
manquait etait le CHEMIN. Une tuile eteinte renvoyait vers `/launcher`, qui ne connaissait
que `graph`, `hub` et `tui_bridge` : un renvoi vers une page sans bouton. C'est ce que
l'owner appelle, a juste titre, une « tuile morte ».

TROIS MORSURES, et chacune ferme une facon differente de refabriquer ce defaut :

1. `test_chaque_service_expose_est_atteignable` — exposer un bouton pour un service que
   `forge_ensure_service` ne nomme pas redonnerait un bouton qui ne peut rien. C'est la
   dette de cablage, prise du cote de l'ecran.
2. `test_chaque_service_expose_annonce_son_cout` — un avertissement vide transformerait
   la promesse en decoration.
3. `test_les_routes_ne_sont_pas_publiques` — allumer plusieurs Go depuis un navigateur
   sans session serait pire que le probleme d'origine.

Hermetique : aucun service demarre, aucun port ouvert, aucun appel au superviseur.
"""
from __future__ import annotations

import inspect
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

pytest.importorskip(
    "fastapi",
    reason="fastapi est une dependance REELLE du portail : son absence est un fait a voir",
)

from app.web_hub import services_views as SV  # noqa: E402
from app.web_hub.auth import is_public_path  # noqa: E402

TOML = ROOT / "proxy_deno" / "core" / "services.toml"


def _services_toml() -> dict:
    if not TOML.exists():
        pytest.skip("services.toml absent")
    d = tomllib.loads(TOML.read_text(encoding="utf-8"))
    return {s["name"]: s for s in d.get("service", []) if s.get("name")}


def test_le_catalogue_n_est_pas_vide():
    """Sonde de la sonde : sur un catalogue vide, tous les tests seraient vacuement verts."""
    assert SV.ONDEMAND, "aucun service a la demande expose : ce fichier ne mesure rien"


@pytest.mark.parametrize("cle", sorted(SV.ONDEMAND))
def test_chaque_service_expose_est_atteignable(cle):
    """MORSURE — un bouton pour un service que la route gouvernee ignore ne peut rien."""
    ens = pytest.importorskip("forge_ensure_service")
    carte = None
    for nom, val in vars(ens).items():
        if isinstance(val, dict) and "hub" in val and "docker" in val:
            carte = val
            break
    assert carte is not None, "carte des services introuvable dans forge_ensure_service"
    assert cle in carte, (
        "%r est propose a l'ecran mais absent de la carte de forge_ensure_service : "
        "le bouton enverrait une demande que personne ne sait router" % cle
    )


@pytest.mark.parametrize("cle", sorted(SV.ONDEMAND))
def test_chaque_service_expose_annonce_son_cout(cle):
    """MORSURE — l'avertissement EST la demande owner ; vide, il ne vaut rien."""
    meta = SV.ONDEMAND[cle]
    assert meta.get("avertissement", "").strip(), (
        "%r n'annonce aucun cout : l'utilisateur decouvrirait la depense apres coup" % cle
    )
    assert meta.get("cout_ram_go", 0) > 0, "%r n'a pas de cout chiffre" % cle
    assert meta.get("port"), "%r n'a pas de port : son etat ne peut pas etre constate" % cle


@pytest.mark.parametrize("cle", sorted(SV.ONDEMAND))
def test_chaque_service_expose_est_bien_eteint_au_boot(cle):
    """Si le service devenait actif au boot, cette section perdrait son objet.

    Le test ne l'exige pas pour figer une politique, mais pour que le jour ou l'un est
    active au demarrage, on le VOIE -- au lieu de laisser un bouton « Demarrer » devant
    un service deja lance.
    """
    ens = pytest.importorskip("forge_ensure_service")
    carte = next((v for v in vars(ens).values()
                  if isinstance(v, dict) and "hub" in v and "docker" in v), None)
    if carte is None or cle not in carte:
        pytest.skip("carte indisponible")
    nom = carte[cle]
    svcs = _services_toml()
    if nom not in svcs:
        pytest.skip("%s absent de services.toml" % nom)
    assert svcs[nom].get("disabled") is True, (
        "%s n'est plus `disabled` : il demarre au boot, et la section « a la demande » "
        "proposerait de lancer ce qui tourne deja" % nom
    )


def test_les_routes_ne_sont_pas_publiques():
    """MORSURE — allumer plusieurs Go sans session serait pire que le defaut d'origine."""
    for chemin in ("/api/services/ondemand",
                   "/api/services/llamacpp_chat/start",
                   "/api/services/llamacpp_chat/stop"):
        assert not is_public_path(chemin), "%s est traite comme PUBLIC" % chemin


def test_le_demarrage_est_deporte_hors_de_la_boucle():
    """`ensure()` est synchrone et parle au superviseur : dans la boucle, il gele tout.

    Ce portail a paye ce defaut plusieurs fois aujourd'hui meme.
    """
    src = inspect.getsource(SV._demander)
    assert "to_thread" in src, (
        "l'appel synchrone au superviseur n'est pas deporte : il bloquerait l'event loop"
    )


def test_la_reponse_ne_pretend_jamais_que_c_est_demarre():
    """REQUESTED != ACHIEVED : le superviseur peut expirer EN AGISSANT."""
    src = inspect.getsource(SV._demander)
    assert "etat_demande" in src, "la reponse ne distingue pas la demande de l'etat atteint"
    assert "port repond" in src, (
        "la reponse ne dit pas a quoi se constate le succes reel"
    )


def test_l_ecran_affiche_l_avertissement_avant_le_clic():
    """Un avertissement seulement dans la confirmation se decouvre trop tard."""
    from app.web_hub.launcher_html import render_launcher
    page = render_launcher("test")
    assert "/api/services/ondemand" in page, "la page n'interroge pas les services"
    assert "avertissement" in page, "la page n'affiche pas l'avertissement"
    assert "Services a la demande" in page, "la section n'existe pas dans la page"

"""NR — une capacite livree dans la distribution est DECLAREE.

Mesure du 2026-09-19. La declaration reelle des services
(`proxy_deno/core/services.toml`, 93 services) est RETENUE a la publication, et
c'est justifie : elle porte la topologie de la machine d'origine — chemins
absolus, nom de compte, interpreteurs. La publier livrerait une carte de cette
machine.

Mais la retenir SANS RIEN METTRE A LA PLACE laisse le code du hub, du pont et du
tunnel partir dans la distribution pendant que rien ne dit au superviseur qu'ils
existent ni comment les lancer. C'est le motif que ce depot applique partout
ailleurs : un mecanisme present mais non cable est une dette, pas une
fonctionnalite. Ici c'est la meme chose, vue depuis l'aval — une CAPACITE LIVREE
MAIS NON DECLAREE.

Mesure complete faite ce jour sur les 5944 fichiers suivis : 189 sont retenus,
dont 9 declarations. Six le sont legitimement (IP, configs client, CI propre a
la machine). Trois posaient ce probleme : `services.toml`,
`deploy/laforge-master.service`, `docs/roadmap_instruits.json`.

Ce test garde le remede pour le premier — le plus structurant, puisque sans lui
AUCUN service ne demarre.
"""

import sys
import tomllib
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
GABARIT = RACINE / "docs" / "services.example.toml"

for _p in (RACINE, RACINE / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Services sans lesquels la distribution ne sert a rien, et que personne ne peut
# deviner : le coeur, et le tunnel dont le code est livre mais la forme inconnue.
ATTENDUS = {"NokidoHub", "NokidoGithubBridgeMCP", "NokidoOpenAITunnel"}


@pytest.fixture(scope="module")
def gabarit():
    assert GABARIT.is_file(), (
        "le gabarit de declaration a disparu : la distribution redevient un lot "
        "de code que le superviseur ne connait pas"
    )
    return tomllib.loads(GABARIT.read_text(encoding="utf-8"))


def test_le_gabarit_est_du_toml_valide(gabarit):
    """Un gabarit qui ne se charge pas est pire qu'absent : il promet."""
    assert gabarit.get("service"), "aucun service declare dans le gabarit"
    assert gabarit.get("vars"), "aucune section [vars] : les chemins seraient en dur"


def test_le_gabarit_declare_ce_qu_on_ne_peut_pas_deviner(gabarit):
    noms = {s.get("name") for s in gabarit["service"]}
    manquants = sorted(ATTENDUS - noms)
    assert not manquants, f"services livres mais non declares dans le gabarit : {manquants}"


def test_chaque_service_du_gabarit_porte_de_quoi_le_lancer(gabarit):
    """Un nom sans commande ni port n'est pas une declaration, c'est une mention."""
    incomplets = [
        s.get("name") for s in gabarit["service"]
        if not s.get("cmd") or not s.get("args") or s.get("port") is None
    ]
    assert not incomplets, f"declarations incompletes : {incomplets}"


def test_le_gabarit_ne_porte_aucune_topologie_de_la_machine_d_origine():
    """La raison meme pour laquelle la declaration reelle est retenue ne doit pas
    revenir par le gabarit."""
    import re

    txt = GABARIT.read_text(encoding="utf-8")
    fuites = []
    if re.search(r"[A-Za-z]:[\\/]{1,2}[A-Za-z]", txt):
        fuites.append("chemin absolu de machine")
    if re.search(r"Users[\\/]{1,2}[A-Za-z0-9_.]+", txt):
        fuites.append("chemin de profil")
    if re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", txt, re.I):
        fuites.append("adresse de courriel")
    assert not fuites, f"le gabarit reintroduit la topologie : {fuites}"


def test_le_gabarit_part_bien_dans_la_distribution():
    """LA MORSURE QUI COMPTE. Un remede retenu par la meme politique que le mal
    ne soigne rien — et ce serait invisible sans ce test."""
    eg = pytest.importorskip("app.forge_git_egress")
    profil = (eg.load_manifest().get("profiles") or {}).get("public") or {}
    motifs = profil.get("blocked_paths") or []
    assert motifs, "politique publique vide : ce test ne mesurerait rien"
    bloque = eg._path_blocked("docs/services.example.toml", motifs)
    assert not bloque, (
        f"le gabarit est RETENU par la politique publique (regle : {bloque}) — "
        "la capacite resterait livree sans declaration"
    )


def test_le_code_des_services_declares_est_lui_aussi_publie():
    """COHERENCE DANS L'AUTRE SENS : declarer un service dont le code est retenu
    produirait une declaration qui ne demarre rien. Les deux moities voyagent
    ensemble ou pas du tout."""
    eg = pytest.importorskip("app.forge_git_egress")
    motifs = ((eg.load_manifest().get("profiles") or {}).get("public") or {}).get("blocked_paths") or []
    porteurs = [
        "tools/nokido_hub.py",
        "tools/forge_bridge_launch.py",
        "tools/forge_github_bridge.py",
        "app/web_hub/app.py",
    ]
    retenus = [f for f in porteurs if (RACINE / f).is_file() and eg._path_blocked(f, motifs)]
    assert not retenus, f"declares dans le gabarit mais code RETENU : {retenus}"

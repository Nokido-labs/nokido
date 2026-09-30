"""NR -- contrat supervisor <-> hub : AUTHZ_DENIED n'est PAS SERVICE_DEAD.

Defaut mesure le 2026-09-02 dans `proxy_deno/core/supervisor.ts` : le gate de
ressource ne testait que `gr.ok`, donc un `401` tombait dans la meme branche
qu'un hub injoignable et le service demarrait quand meme. Rien ne se bloquait --
le frein de ressource **disparaissait en silence**, precisement au moment ou
l'on croyait proteger le corps. Le meme motif touchait la telemetrie GPU, qui
rendait `null` sur un refus, indistinguable d'une absence de mesure.

Ces tests lisent le SOURCE TypeScript. C'est un filet imparfait -- il ne
remplace pas `deno check` -- mais c'est le seul disponible depuis la suite
Python, et `deno` est introuvable depuis le compte sandbox (il y rendrait une
chaine vide, qui se lirait comme « aucune erreur »).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

SUP = ROOT / "proxy_deno" / "core" / "supervisor.ts"

# Appels vers le hub qui n'ont PAS a distinguer 401, et POURQUOI. Toute entree
# ici est une dette assumee et nommee, jamais un oubli.
EXEMPTES = {
    "/admin/run_job": "l'echec est deja journalise (ok=undefined visible)",
    "/api/maintenance/gc": "l'echec est deja journalise (ok=undefined visible)",
    "/health": "doit rester PUBLIC : l'authentifier ferait lire un refus comme "
               "un hub wedge, et le superviseur le tuerait en boucle",
}


@pytest.fixture(scope="module")
def src() -> str:
    assert SUP.exists(), "superviseur introuvable : le reste du test serait vide de sens"
    return SUP.read_text(encoding="utf-8", errors="replace")


def test_le_fichier_est_lisible_et_non_vide(src):
    """Garde-fou de l'instrument : un fichier vide rendrait tout le reste vert."""
    assert len(src) > 50_000


def test_le_gate_de_ressource_distingue_le_refus_de_la_panne(src):
    i = src.find("/api/resource/should_spawn")
    assert i > 0, "gate de ressource introuvable"
    zone = src[i:i + 2000]
    assert "AUTHZ_DENIED" in zone, (
        "le gate ne nomme pas le refus d'acces : un 401 y retomberait dans la "
        "branche « hub indisponible » et desarmerait le frein en silence")
    assert "401" in zone and "403" in zone


def test_le_gate_differe_au_lieu_de_passer_outre(src):
    """Sur AUTHZ_DENIED le service ne doit PAS demarrer comme si de rien n'etait.

    Ancre sur le CODE (`gr.status === 401`) et non sur le mot `AUTHZ_DENIED`,
    qui apparait d'abord dans un commentaire : une premiere version de ce test
    tombait sur la prose et declarait le contrat absent alors qu'il etait la.
    """
    i = src.find("gr.status === 401")
    assert i > 0, "le gate ne teste pas explicitement le code 401"
    zone = src[i:i + 800]
    assert "scheduleDefer" in zone, (
        "un refus d'acces doit differer le demarrage, pas etre ignore")
    assert "return;" in zone, "le flux doit s'arreter apres le defer"


def test_la_telemetrie_distingue_refus_et_absence_de_mesure(src):
    """`return null` sur un 401 est indistinguable d'une absence de donnee."""
    occurrences = [m.start() for m in re.finditer(r"/api/swarm/health", src)]
    assert len(occurrences) >= 2, "les deux sites de telemetrie ont disparu"
    for i in occurrences:
        zone = src[i:i + 1200]
        assert "AUTHZ_DENIED" in zone, (
            "un site de telemetrie rend null sur un refus sans le dire "
            "(offset %d)" % i)


def test_le_gate_indisponible_est_dit_a_voix_haute(src):
    """Le fail-open reste le bon defaut, le SILENCE non.

    Ancre sur le code (`gr.status === 401`) et fenetre large : la version
    precedente partait de la mention de la route et se faisait deborder des
    qu'on ajoutait des commentaires -- un test qui rougit parce qu'on a
    documente le code est un test qui sera desactive.
    """
    i = src.find("gr.status === 401")
    assert i > 0
    zone = src[i:i + 1500]
    assert "fail-open" in zone, "le repli n'est plus nomme"
    assert "indisponible" in zone, "un gate injoignable passe en silence"


def test_chaque_appel_au_hub_est_traite_ou_exempte_avec_sa_raison(src):
    """Balayage : aucun appel vers le hub ne doit ignorer le cas 401 sans
    qu'on ait ecrit POURQUOI. C'est ce qui empeche le motif de revenir par un
    site neuf -- un piege corrige dans UN endroit ne protege que cet endroit."""
    non_traites = []
    for m in re.finditer(r"127\.0\.0\.1:8766([^\s\"'`,)]*)", src):
        route = m.group(1) or "/"
        route = route.split("?")[0].rstrip("`\"';,)") or "/"
        if any(route.startswith(e) for e in EXEMPTES):
            continue
        # L'URI CIBLE d'une preuve DPoP (htu) n'est pas un appel : `_entetesAdminAvecPreuve`
        # la derive pour signer, chaque APPEL qui porte ces entetes reste balaye ici (2026-09-24).
        # Exclusion par la forme de l'appelant, jamais par la route ("/" exempterait tout).
        if re.search(r"_preuveDpopTpm\([^)]*$", src[max(0, m.start() - 120):m.start()]):
            continue
        zone = src[m.start():m.start() + 1400]
        if "AUTHZ_DENIED" not in zone:
            non_traites.append((route, m.start()))
    assert not non_traites, (
        "appels au hub ne distinguant pas le refus de la panne, et absents des "
        "exemptions documentees : %s" % non_traites)


def test_garde_du_garde_htu_dpop_seul_exclu():
    """L'exclusion htu ne doit pas avaler un vrai appel voisin."""
    faux = ('const p = await _preuveDpopTpm(m, "http://127.0.0.1:8766" + c);\n'
            'const r = await fetch("http://127.0.0.1:8766/admin/x", {});\n')
    vus = [m.group(0) for m in re.finditer(r"127\.0\.0\.1:8766([^\s\"'`,)]*)", faux)
           if not re.search(r"_preuveDpopTpm\([^)]*$", faux[max(0, m.start() - 120):m.start()])]
    assert vus == ["127.0.0.1:8766/admin/x"]


def test_les_exemptions_portent_toutes_une_raison():
    for route, raison in EXEMPTES.items():
        assert raison.strip(), route


def test_health_reste_public_et_la_contrainte_est_ecrite():
    """Si quelqu'un authentifie /health, le superviseur tuera le hub en boucle.
    La raison doit vivre a cote de la declaration, pas dans un commit."""
    import forge_authz_shadow as az

    assert "/health" in az.PUBLIC_DECLARE
    motif = az.PUBLIC_DECLARE["/health"].lower()
    for mot in ("supervisor", "boucle"):
        assert mot in motif, (
            "le motif de /health ne dit pas ce qu'on casse en l'authentifiant")


def test_le_superviseur_sonde_toujours_health_sans_jeton(src):
    """Contre-epreuve du test precedent : si cette sonde disparait ou gagne un
    jeton, la contrainte sur /health n'a plus lieu d'etre et doit etre revue."""
    assert "probeHttp(\"http://127.0.0.1:8766/health\")" in src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

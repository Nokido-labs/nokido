"""NR 29/10 (owner, constitution : DISABLED_BY_POLICY != RESOURCE_UNAVAILABLE) -- le census comptait une PROTHESE endormie
comme une surface injoignable : LM Studio (reveille juste-a-temps par forge_agent_proxy, ensure lmstudio) et LiteLLM
(bibliotheque in-process via forge_litellm_bridge, aucun serveur :4000 attendu) sortaient « NON MESURE -- URLError » a
chaque passe. Une prothese qui dort est A_LA_DEMANDE ; une bibliotheque n'est pas une surface reseau.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "app"), str(ROOT)]

import forge_free_tier_census as C  # noqa: E402


def test_lmstudio_endormi_est_a_la_demande():
    etat, motif = C.etat_hors_ligne("lmstudio", -1, "URLError: connexion refusee")
    assert etat == "A_LA_DEMANDE" and "forge_agent_proxy" in motif


def test_litellm_est_une_bibliotheque_pas_une_surface():
    etat, motif = C.etat_hors_ligne("litellm", -1, "URLError")
    assert etat == "BIBLIOTHEQUE" and "forge_litellm_bridge" in motif


def test_un_vrai_fournisseur_en_panne_reste_non_mesure():
    assert C.etat_hors_ligne("together", 401, "HTTP 401 Unauthorized") == ("NON_MESURE", "HTTP 401 Unauthorized")


def test_la_boucle_principale_passe_par_etat_hors_ligne():
    """Chemin reel : main() doit classer par etat_hors_ligne, pas ecrire NON_MESURE en dur."""
    arbre = ast.parse((ROOT / "tools" / "forge_free_tier_census.py").read_text(encoding="utf-8"))
    main = next(n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    appels = {n.func.id for n in ast.walk(main) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "etat_hors_ligne" in appels

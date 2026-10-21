"""NR -- l'applicateur des rapports de verification de roadmap vit dans le depot, et une cloture exige une PREUVE.

Owner 18/10 : « les ecritures C:/tmp, tmp ou D: ne sont pas optimum, et surement source d'oubli de travaux ». L'outil
de la campagne du 17/10 vivait en C:/tmp/appliquer_verif_lot.py (date en dur, verdict PERIME inconnu). Il devient
tools/forge_roadmap_verif_appliquer.py ; sa decision est une fonction pure.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import forge_roadmap_verif_appliquer as ap  # noqa: E402

SRC = "verif bef8362e9 (lot 1)"


def test_fait_prouve_clot_et_fait_sans_preuve_ne_clot_pas():
    assert ap.prefixe("FAIT", ["abc1234"], "", "2026-10-18", SRC).startswith("[CLOS 2026-10-18 : verif")
    assert ap.prefixe("FAIT", [], "", "2026-10-18", SRC).startswith("[VERIF_A_FAIRE 2026-10-18")


def test_perime_clot_seulement_s_il_nomme_ce_qui_remplace():
    assert ap.prefixe("PERIME", ["def5678"], "", "2026-10-18", SRC).startswith("[CLOS PERIME 2026-10-18")
    assert ap.prefixe("PERIME", [], "", "2026-10-18", SRC).startswith("[VERIF_A_FAIRE 2026-10-18")


def test_une_cle_existante_du_tableau_noir_est_une_preuve_de_remplacement():
    """Lot 1 du 18/10 : 3 vieux CURRENT_* « remplace par CURRENT_reprise_20261017_nuit » -- la preuve est une CLE du
    tableau noir, pas un sha ni un fichier. Une cle ABSENTE ne prouve rien."""
    cles = {"CURRENT_reprise_20261017_nuit", "autre"}
    assert ap.preuve_ok("remplace par CURRENT_reprise_20261017_nuit", cles) is True
    assert ap.preuve_ok("remplace par CURRENT_qui_n_existe_pas", cles) is False


def test_partiel_garde_le_reste_et_l_inconnu_ne_clot_jamais():
    assert ap.prefixe("PARTIEL", [], "ecrire le NR x", "2026-10-18", SRC) == \
        "[PARTIEL 2026-10-18 : %s ; reste = ecrire le NR x] " % SRC
    assert ap.prefixe("BIZARRE", ["abc1234"], "", "2026-10-18", SRC).startswith("[VERIF_A_FAIRE")

# -*- coding: utf-8 -*-
"""NR — A0-3b : le backlog qualifie doit ATTEINDRE l'arbitre, et faire agir.

Un capteur peut exister, etre juste, et n'innerver RIEN. C'etait le cas ici :
`forge_memory_snapshot_refresh` est bien cable en NREM1 (`supervisor.ts`), mais la
boucle circadienne ne tirait QUE la phase courante — `currentPhase()` — et NREM1 ne
dure que de 22 h a 2 h. Un superviseur redemarre a 02h05 saute donc la fenetre pour
la journee entiere. Le `debt >= 20h` empeche de re-tirer une phase dans sa propre
fenetre ; il ne RATTRAPAIT pas une fenetre manquee.

⚠️ La dette, elle, EST persistee (`sandbox/circadian_state.json`, load/save autour de
`firePhase`) : elle ne repart pas de zero au redemarrage. C'est bien le rattrapage,
et lui seul, qui manquait. Mesure du 2026-09-05 qui l'a montre — NREM3 et REM venaient
de tirer pendant que deux fenetres plus anciennes restaient en souffrance :

    CREPUSCULE  43.0 h    NREM1  39.0 h  |  NREM3  11.0 h    REM  9.0 h

Consequence : snapshot fige a 36,7 h, donc `backlog = -1 (INCONNU)`, donc
`embed_affame = False`, donc la branche `C_consolidation` STRUCTURELLEMENT
inatteignable — le coder ne pouvait jamais ceder la place a un embedder affame.

L'abstention etait epistemiquement saine (on ne decide pas sans mesure) mais
masquait une INCAPACITE PERMANENTE D'ACTION. C'est cette confusion que le garde
separe : `INCONNU` doit continuer de proteger, et `MESURE` doit rendre l'action
possible. Les deux moities comptent — un garde qui ne testerait que la premiere
laisserait revenir l'incapacite silencieuse.

Hermetique : `arbitrer_pression` est PURE, aucun snapshot reel n'est lu.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

rm = pytest.importorskip("forge_resource_manager")

BASE = dict(rhythm="CONSERVE", coder_up=True, coder_conns=0, chains_active=0,
            embed_wanted=True, embedder_up=False, coder_ram_gb=4.65,
            free_gb=1.0, demande_active=False, inutile_s=999)


def test_backlog_mesure_rend_la_consolidation_atteignable():
    """La moitie qu'on a failli perdre : mesure -> action POSSIBLE."""
    d = rm.arbitrer_pression(backlog=86454, **BASE)
    assert d["strategie"] == "C_consolidation"
    assert d["action"] == "yield_coder"
    assert "86454" in d["raison"], "la raison doit porter le chiffre qui a decide"


def test_backlog_inconnu_protege_toujours():
    """L'autre moitie : sans mesure, on ne cede pas. `-1` = INCONNU, jamais zero."""
    d = rm.arbitrer_pression(backlog=-1, **BASE)
    assert d["action"] != "yield_coder"


def test_backlog_sous_le_seuil_ne_fait_pas_ceder():
    d = rm.arbitrer_pression(backlog=10, **BASE)
    assert d["action"] != "yield_coder"


def test_embedder_deja_up_ne_fait_pas_ceder():
    """`embed_affame` exige que l'embedder soit ABSENT : sinon rien a liberer pour lui."""
    d = rm.arbitrer_pression(backlog=86454, **{**BASE, "embedder_up": True})
    assert d["action"] != "yield_coder"


def test_sans_coder_aucune_consolidation():
    """On ne cede pas un organe absent — et on le DIT, sans parler de protection."""
    d = rm.arbitrer_pression(backlog=86454, **{**BASE, "coder_up": False})
    assert d["action"] == "noop"
    assert "aucun coder" in d["raison"]


def test_le_regulateur_ne_recalcule_jamais_le_backlog():
    """Le producteur MESURE (12,2 s), le regulateur CONSOMME (~7 ms).

    Le chemin chaud ne doit jamais appeler `compteurs()` ni refaire le GROUP BY :
    c'est un balayage de la base de 24,9 Go, celui-la meme qui a mis le hub a terre
    le 23/08 et le 03/09.
    """
    import ast
    import inspect
    import textwrap

    arbre = ast.parse(textwrap.dedent(
        inspect.getsource(rm._backlog_pending_qualifie)))
    appels = {getattr(n.func, "id", "") or getattr(n.func, "attr", "")
              for n in ast.walk(arbre) if isinstance(n, ast.Call)}
    assert "compteurs" not in appels, \
        "le chemin chaud recalcule le backlog : GROUP BY sur 24,9 Go a chaque decision"
    assert "snapshot" in appels, "le consommateur ne lit plus le snapshot"


def test_le_producteur_reste_hors_du_regulateur():
    """Pas de DOUBLE PRODUCTEUR : `forge_resource_manager` ne doit pas rafraichir.

    Deux emetteurs pour un meme signal, c'est deux cadences, deux couts et un
    arbitrage impossible a lire dans le journal.
    """
    src = (ROOT / "app" / "forge_resource_manager.py").read_text(
        encoding="utf-8", errors="replace")
    assert "rafraichir()" not in src, \
        "le regulateur rafraichit le snapshot : il doit le CONSOMMER, pas le produire"


# --- Garde de CABLAGE du rattrapage circadien -------------------------------
# Portee honnete : ces trois cas verifient que le rattrapage est BRANCHE et n'a pas
# ete debranche par une edition ulterieure. Ils ne prouvent PAS son comportement —
# `deno check` type le fichier, rien ici ne l'execute. C'est deliberement le
# symetrique du motif « garde branche sur un signal que personne n'emet » : ici, le
# risque est un emetteur retire sans que le consommateur s'en apercoive.

SUPERVISEUR = ROOT / "proxy_deno" / "core" / "supervisor.ts"


def _ts() -> str:
    return SUPERVISEUR.read_text(encoding="utf-8", errors="replace")


def test_la_boucle_circadienne_rattrape_une_fenetre_manquee():
    src = _ts()
    i = src.index("async function circadianLoop")
    corps = src[i:src.index("\nfunction circadianStatus", i)]
    assert "phaseEnRetard()" in corps, \
        "le rattrapage est debranche : NREM1 redevient injoignable hors 22h-2h"
    assert "CATCHUP" in corps, "un rattrapage doit se distinguer d'un tir normal au journal"


def test_une_phase_jamais_tiree_n_est_pas_un_retard():
    """`UNKNOWN != NO` : un etat vierge ne fabrique pas six rattrapages au boot."""
    src = _ts()
    i = src.index("function phaseEnRetard")
    corps = src[i:src.index("\n}", src.index("return pire", i))]
    assert "if (!ts) continue;" in corps, \
        "phaseEnRetard traite une phase sans horodatage comme un retard mesure"


def test_le_rattrapage_ATTEND_le_hub():
    """DEFAUT MESURE le 2026-09-05, dans l'heure suivant la mise en service du
    rattrapage : le premier CATCHUP a tire NREM1 a 15:49:31, et 33 s plus tard le
    journal montrait « dep :8766 not open yet » sur QUATORZE services. Le POST du
    bloc NREM1 n'avait personne au bout -- la phase a ete marquee TIREE et
    l'emetteur du snapshot n'a rien produit.

    Structurel, pas accidentel : au demarrage la dette est MAXIMALE et le hub pas
    encore la. Et `firePhase` horodate la phase, donc un tir a vide SOLDE la dette
    sans avoir rendu le service (`REQUESTED != ACHIEVED`).
    """
    src = _ts()
    i = src.index("async function circadianLoop")
    corps = src[i:src.index("\nfunction circadianStatus", i)]
    assert "isPortOpen(8766)" in corps, \
        "le rattrapage tire sans verifier que le hub ecoute : il soldera la dette a vide"
    assert "CATCHUP differe" in corps, "un report doit se lire au journal"
    assert corps.index("isPortOpen(8766)") < corps.index("await firePhase(retard.phase)"), \
        "la verification doit PRECEDER le tir"


def test_le_rattrapage_reste_une_phase_par_tick():
    """Une rafale de redemarrages serait pire que le retard qu'elle corrige."""
    src = _ts()
    i = src.index("async function circadianLoop")
    corps = src[i:src.index("\nfunction circadianStatus", i)]
    assert corps.count("firePhase(") == 2, \
        "circadianLoop tire plus d'une phase par tick (courante + rattrapage = 2)"

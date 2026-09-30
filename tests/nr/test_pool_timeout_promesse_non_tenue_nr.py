# -*- coding: utf-8 -*-
"""NR — `with ThreadPoolExecutor()` + `.result(timeout=)` : une promesse que la
sortie du bloc ne tient pas.

Classe `resource-exhaustion-and-availability` du registre de sécurité, ligne C2.1,
instruite le 2026-09-22.

LE DÉFAUT, en une phrase
========================
`ThreadPoolExecutor.__exit__` appelle `shutdown(wait=True)`. Quand `.result(timeout=T)`
expire, on quitte le bloc `with` — et cette sortie **attend la fin de la tâche**,
inconditionnellement. L'appelant n'est donc PAS libéré au bout de T.

    LE GARDE EXISTE, IL EST JUSTE, ET IL GARDE LA MAUVAISE PHASE.

C'est la troisième variante du motif transversal du registre : un budget évalué DANS la
boucle ne protège pas du blocage qui survient EN SORTANT. Déjà payé en S13 (le gate
ui-acceptance a bloqué la CI 1662 s à 0 % de CPU, budget déclaré 480 s).

Enjeu mesuré : `app/forge_embed_router.py:1004` est sur le chemin du RAG, et
`app/forge_goap.py:858` exécute un `asyncio.run` complet derrière un timeout de 120 s.
Un blocage synchrone long tue le hub (mesure du 2026-09-05, 8 morts par jour).

LE REMÈDE, POUR QUAND ON LE POSERA
==================================
Ne pas utiliser `with`. Construire l'exécuteur, puis à la sortie :

    executor.shutdown(wait=False, cancel_futures=True)   # Python >= 3.9

Il n'est PAS appliqué ici : 8 sites dans 7 fichiers, dont deux organes chauds. Un
correctif large posé sans mesure d'impact est précisément ce que cette campagne
documente comme mode d'échec.

CE QUE CE NR EST — un cliquet, pas un verdict
=============================================
Il PLAFONNE le nombre de sites à la mesure du jour. Il n'exige pas zéro : exiger zéro
rendrait le test rouge immédiatement et il serait désarmé dans la semaine. Il empêche la
PROPAGATION pendant que la décision se prend, et il rend le chiffre visible à chaque run.

Périmètre : `app/` et `tools/` seulement. `tests/` est exclu — un instrument ne lit
jamais son propre vocabulaire, et ce fichier contient les motifs qu'il cherche
(cinq fois payé en trois jours).
"""

import re
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : lecture de tous les app/*.py
#   et tools/*.py (l.81)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Cliquet MESURÉ le 2026-09-22 : 36 sites `with ThreadPoolExecutor(...)` dans app/ et
# tools/, dont 8 portent un `.result(timeout=...)`. Les 28 autres n'promettent rien :
# leur attente est assumée, ce n'est pas un défaut.
PLAFOND_PROMESSES_NON_TENUES = 8

_OUVERTURE = re.compile(r"with\s+[\w.]*ThreadPoolExecutor\s*\(")
_PROMESSE = re.compile(r"\.result\s*\(\s*timeout\s*=")


def _corps_du_with(lignes, i):
    """Les lignes du bloc `with` ouvert en `lignes[i]`, par indentation."""
    ind = len(lignes[i]) - len(lignes[i].lstrip())
    corps = []
    for j in range(i + 1, min(i + 40, len(lignes))):
        if lignes[j].strip() and (len(lignes[j]) - len(lignes[j].lstrip())) <= ind:
            break
        corps.append(lignes[j])
    return "\n".join(corps)


def recenser(racine=None):
    """Rend (promesses_non_tenues, attentes_assumees) — chacune une liste de 'fichier:ligne'."""
    racine = Path(racine or ROOT)
    promesses, assumees = [], []
    for d in ("app", "tools"):
        rep = racine / d
        if not rep.is_dir():
            continue
        for p in sorted(rep.glob("*.py")):
            try:
                lignes = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue  # ILLISIBLE != ABSENT ; compté nulle part, et dit par le test
            if not any("ThreadPoolExecutor" in l for l in lignes):
                continue
            for i, l in enumerate(lignes):
                if not _OUVERTURE.search(l):
                    continue
                cible = promesses if _PROMESSE.search(_corps_du_with(lignes, i)) else assumees
                cible.append(f"{d}/{p.name}:{i + 1}")
    return promesses, assumees


def test_le_detecteur_mord_sur_un_site_fabrique(tmp_path):
    """CONTRÔLE NÉGATIF : sans lui, un plafond respecté ne prouverait rien —
    un détecteur qui ne voit rien respecte tous les plafonds."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "faux.py").write_text(
        "from concurrent.futures import ThreadPoolExecutor\n"
        "def f(fn):\n"
        "    with ThreadPoolExecutor(max_workers=1) as ex:\n"
        "        return ex.submit(fn).result(timeout=5)\n",
        encoding="utf-8",
    )
    (tmp_path / "app" / "sain.py").write_text(
        "from concurrent.futures import ThreadPoolExecutor\n"
        "def g(fn):\n"
        "    with ThreadPoolExecutor(max_workers=1) as ex:\n"
        "        return ex.submit(fn).result()\n",
        encoding="utf-8",
    )
    promesses, assumees = recenser(tmp_path)
    assert len(promesses) == 1, f"le détecteur rate la promesse non tenue : {promesses}"
    assert len(assumees) == 1, f"le détecteur accuse une attente assumée : {assumees}"


def test_le_nombre_de_promesses_non_tenues_ne_croit_pas():
    promesses, assumees = recenser()
    # Une borne dit COMBIEN, et le dénominateur sort même en vert.
    print(
        f"[C2.1] {len(promesses) + len(assumees)} sites `with ThreadPoolExecutor` dans "
        f"app/+tools/ · {len(promesses)} avec .result(timeout=) = promesse NON TENUE · "
        f"{len(assumees)} attente assumée (plafond cliquet {PLAFOND_PROMESSES_NON_TENUES})"
    )
    assert len(promesses) <= PLAFOND_PROMESSES_NON_TENUES, (
        f"{len(promesses)} sites promettent un timeout que la sortie du bloc `with` ne "
        f"tient pas, plafond {PLAFOND_PROMESSES_NON_TENUES} (mesuré le 2026-09-22). "
        f"Nouveaux sites : {sorted(set(promesses))}. "
        f"Remède : ne pas utiliser `with`, puis shutdown(wait=False, cancel_futures=True)."
    )


def test_les_organes_chauds_restent_nommes():
    """Si `forge_embed_router` ou `forge_goap` sortent de la liste, c'est une BONNE
    nouvelle — mais elle doit être CONSTATÉE et le registre requalifié, pas subie."""
    promesses, _ = recenser()
    fichiers = {p.rsplit(":", 1)[0] for p in promesses}
    chauds = {"app/forge_embed_router.py", "app/forge_goap.py"} & fichiers
    assert chauds, (
        "ni forge_embed_router ni forge_goap ne portent plus le motif : le défaut C2.1 "
        "a peut-être été corrigé. Relire le registre et requalifier la ligne."
    )
